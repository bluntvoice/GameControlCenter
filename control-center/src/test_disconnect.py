"""Stop/reconnect regressions without a real controller, phone or running adapter."""
import json
from pathlib import Path
import tempfile
import threading
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock,patch

import backend
from backend import Center


class DisconnectTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.center=Center.__new__(Center)
        c=self.center
        c.home=Path(self.temp.name);c.analog=c.home/'analog';c.analog.mkdir()
        c.input_lock=threading.RLock();c.lock=threading.RLock();c.stop=threading.Event()
        c.config=dict(project=str(c.home),pythonw='adapter.exe')
        c.local=dict(controllers=[dict(index=1)])
        c.controller=Mock();c.controller.read.return_value=[dict(index=1)]
        c.event=Mock();c.pid_file=Mock(return_value=123);c.open_component=Mock()

    def test_disconnect_saves_before_shutdown_and_stops_own_reads(self):
        c=self.center
        def quit_adapter(command):
            self.assertEqual(command,'quit')
            self.assertTrue(json.loads((c.home/'config.json').read_text(encoding='utf-8'))['input_disconnected'])
            self.assertEqual(c.read_controllers(),[])
        c.request_pad=Mock(side_effect=quit_adapter)
        c.stop_connection()
        c.controller.read.assert_not_called()
        self.assertEqual(c.local['controllers'],[])

    def test_shutdown_failure_keeps_stopped_preference_and_no_success_event(self):
        c=self.center;c.request_pad=Mock(side_effect=RuntimeError('adapter busy'))
        with self.assertRaisesRegex(RuntimeError,'adapter busy'):c.stop_connection()
        self.assertTrue(c.config['input_disconnected'])
        self.assertEqual(c.read_controllers(),[])
        c.event.assert_not_called()

    def test_stop_fences_a_read_already_in_progress(self):
        c=self.center;entered=threading.Event();release=threading.Event();finished=threading.Event()
        def read():
            entered.set();self.assertTrue(release.wait(3));return []
        c.controller.read.side_effect=read;c.request_pad=Mock()
        poll=threading.Thread(target=c.read_controllers)
        stop=threading.Thread(target=lambda:(c.stop_connection(),finished.set()))
        poll.start();self.assertTrue(entered.wait(2));stop.start()
        try:self.assertFalse(finished.wait(.05))
        finally:release.set();poll.join(3);stop.join(3)
        self.assertTrue(finished.is_set())
        for _ in range(200):self.assertEqual(c.read_controllers(),[])
        self.assertEqual(c.controller.read.call_count,1)

    def test_absent_adapter_is_never_started_to_stop_it(self):
        c=self.center;c.pid_file.return_value=None
        c.stop_connection();c.stop_connection()
        c.open_component.assert_not_called()
        self.assertFalse((c.analog/'control-request.json').exists())

    def test_quit_waits_for_process_exit_without_stealing_focus(self):
        c=self.center;process=Mock();process.alive.side_effect=[True,False,False]
        with patch.object(backend.winprobe,'Process',return_value=process),patch.object(backend.winprobe,'user') as user:
            c.stop_connection()
        request=json.loads((c.analog/'control-request.json').read_text(encoding='utf-8'))
        self.assertEqual(request['command'],'quit')
        user.AllowSetForegroundWindow.assert_not_called();process.close.assert_called_once()
        self.assertEqual(c.read_controllers(),[])

    def test_hung_adapter_is_not_reported_as_stopped(self):
        c=self.center;process=Mock();process.alive.return_value=True
        with patch.object(backend.winprobe,'Process',return_value=process),patch.object(backend.time,'monotonic',side_effect=[0,10]):
            with self.assertRaisesRegex(RuntimeError,'尚未退出'):c.stop_connection()
        self.assertTrue(c.config['input_disconnected']);c.event.assert_not_called()
        process.close.assert_called_once()

    def test_restart_preserves_stopped_state_before_first_controller_poll(self):
        c=self.center;c.config['input_disconnected']=True
        config=dict(c.config,gamescrcpy=str(c.home/'GameScrcpy.exe'))
        with patch.object(backend,'load_config',return_value=config),patch.object(backend,'ProfileStore'),patch.object(backend.winprobe,'Controller') as controller:
            restarted=Center(c.home)
            try:
                self.assertEqual(restarted.read_controllers(),[])
                controller.assert_not_called()
            finally:restarted.csv_file.close()

    def test_failed_reconnect_restores_stopped_mode_and_closes_adapter(self):
        c=self.center;c.config['input_disconnected']=True
        c.stop.wait=Mock(return_value=True)
        process=Mock();process.alive.return_value=False
        with patch.object(backend.winprobe,'Process',return_value=process),patch.object(backend.winprobe,'user'):
            # Cancelling an unfinished start must not be mistaken for success.
            with self.assertRaises(RuntimeError):c.request_pad('start')
        self.assertTrue(c.config['input_disconnected'])

    def test_profile_switch_cannot_reconnect_stopped_console(self):
        c=self.center;c.config['input_disconnected']=True;c.editing_profile=False
        c.profiles=Mock();c.profiles.select.return_value=dict(path='test.json',name='测试方案')
        c.request_pad=Mock()
        with patch.object(backend,'read_json',return_value=dict(manual_pause=False)):
            c.switch_profile('test')
        c.request_pad.assert_called_once_with('pause')
        self.assertTrue(c.config['input_disconnected'])

    def test_explicit_reconnect_reenables_reads_with_acknowledged_start(self):
        c=self.center;c.config['input_disconnected']=True
        def acknowledge(_):
            request=json.loads((c.analog/'control-request.json').read_text(encoding='utf-8'))
            backend.atomic_json(c.analog/'status.json',dict(pid=123,control_request_id=request['id'],armed=True))
            return False
        c.stop.wait=Mock(side_effect=acknowledge)
        with patch.object(backend.winprobe,'user'):c.request_pad('start')
        self.assertFalse(c.config['input_disconnected'])
        self.assertEqual(c.read_controllers(),[dict(index=1)])
        c.controller.read.assert_called_once()

    def test_native_adapter_quit_ipc_exits_without_closing_console_owner(self):
        c=self.center;c.config['pythonw']=sys.executable
        phase=c.analog.parent/'fixture';(phase/'analog').mkdir(parents=True)
        (phase/'analog/settings.json').write_text('{"auto_on_foreground":false}',encoding='utf-8')
        script=c.home/'adapter_fixture.py'
        script.write_text('''import os,sys
from pathlib import Path
import pad_adapter as m
phase=Path(sys.argv[1]);m.PHASE=phase;m.STATUS=phase/'analog/status.json'
m.XInput=type('Pad',(),{'read':lambda self:None})
app=m.App();app.root.withdraw()
(phase/'ready').write_text(str(os.getpid()),encoding='utf-8')
app.root.mainloop()
''',encoding='utf-8')
        child=subprocess.Popen([sys.executable,'-B',str(script),str(phase)],creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline=time.monotonic()+5
            while not (phase/'ready').exists() and time.monotonic()<deadline:time.sleep(.02)
            self.assertTrue((phase/'ready').exists())
            c.analog=phase/'analog'
            (c.analog/'adapter.pid').write_text(str(child.pid),encoding='utf-8')
            c.pid_file=Center.pid_file.__get__(c,Center)
            self.assertEqual(c.pid_file(c.analog/'adapter.pid',sys.executable),child.pid)
            c.stop_connection()
            self.assertEqual(child.wait(timeout=3),0)
            self.assertFalse(c.stop.is_set())
            self.assertEqual(c.read_controllers(),[])
        finally:
            if child.poll() is None:child.terminate();child.wait(timeout=3)


if __name__=='__main__':unittest.main()

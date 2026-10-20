"""Shell-launched descendants must not keep a console action busy."""
import json
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

from app_config import powershell_path
from backend import Center


class ShellLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.center=Center.__new__(Center)
        self.center.config=dict(powershell=powershell_path())

    def script(self,text):
        path=self.root/'fixture.ps1'
        path.write_text("[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)\n"+text,encoding='utf-8')
        return path

    def test_inherited_output_does_not_wait_for_background_child(self):
        # Match Start-Process's inherited handles without a phone or controller.
        child=self.root/'child.py'
        child.write_text('import time;time.sleep(6)',encoding='utf-8')
        script=self.script('$p=Start-Process -FilePath $args[0] -ArgumentList $args[1] -NoNewWindow -PassThru\nWrite-Output $p.Id')
        started=time.monotonic();pid=None
        try:
            pid=int(self.center.ps(script,sys.executable,child))
            self.assertLess(time.monotonic()-started,4)
            import winprobe
            handle=winprobe.Process(pid)
            try:self.assertTrue(handle.alive())
            finally:handle.close()
        finally:
            if pid:
                subprocess.run(['taskkill','/PID',str(pid),'/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW)

    def test_utf8_output_and_errors_are_preserved(self):
        self.assertEqual(self.center.ps(self.script("Write-Output '恢复连接完成'")),'恢复连接完成')
        with self.assertRaisesRegex(RuntimeError,'启动失败'):
            self.center.ps(self.script("[Console]::Error.WriteLine('启动失败');exit 3"))

    def test_shell_timeout_remains_bounded(self):
        started=time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            self.center.ps(self.script('Start-Sleep -Seconds 20'),timeout=.3)
        self.assertLess(time.monotonic()-started,3)

    def test_repeated_stop_resume_via_real_launcher_and_native_adapter(self):
        c=self.center;c.home=self.root/'control-center';c.home.mkdir()
        c.project=self.root;c.analog=self.root/'phase2b-20261015/analog';c.analog.mkdir(parents=True)
        c.input_lock=threading.RLock();c.lock=threading.RLock();c.stop=threading.Event()
        c.local={};c.controller=Mock();c.controller.read.return_value=[];c.event=Mock()
        c.busy=False;c.action='';c.updates=queue.Queue()
        c.config.update(project=str(self.root),pythonw=sys.executable,input_disconnected=True)
        c.config['gamescrcpy']=str(self.root/'GameScrcpy.exe')
        (c.home/'config.json').write_text(json.dumps(c.config),encoding='utf-8')
        (c.analog/'settings.json').write_text('{"auto_on_foreground":true}',encoding='utf-8')
        tools=self.root/'tools/analog';tools.mkdir(parents=True)
        source=Path(__file__).resolve().parents[2]/'tools/analog'
        shutil.copy2(source/'launch.ps1',tools/'launch.ps1')
        # Run the real Tk adapter, replacing only device reads and video discovery.
        (tools/'pad_adapter.py').write_text('''import sys
from pathlib import Path
sys.path.insert(0,SOURCE)
import pad_adapter as m
phase=Path(__file__).resolve().parents[2]/'phase2b-20261015'
m.PHASE=phase;m.STATUS=phase/'analog/status.json'
m.XInput=type('Pad',(),{'read':lambda self:None})
m.find_video=lambda:None
app=m.App();app.root.withdraw();app.root.mainloop()
'''.replace('SOURCE',repr(str(source))),encoding='utf-8')
        c.open_component=lambda key,show=False:c.ps(tools/'launch.ps1')
        def action(name,operation):
            c.action_async(name,operation)
            deadline=time.monotonic()+7
            while c.busy and time.monotonic()<deadline:time.sleep(.02)
            self.assertFalse(c.busy,'Action must release the buttons after completion')
            self.assertEqual(c.action,'')
            c.event.assert_called_with(name+'完成','ok')
        active=None
        try:
            for _ in range(3):
                started=time.monotonic();action('恢复连接',lambda:c.request_pad('start'))
                self.assertLess(time.monotonic()-started,6)
                self.assertFalse(c.config['input_disconnected'])
                active=c.pid_file(c.analog/'adapter.pid',sys.executable)
                self.assertIsNotNone(active)
                action('停止连接',c.stop_connection)
                self.assertTrue(c.config['input_disconnected'])
                self.assertIsNone(c.pid_file(c.analog/'adapter.pid',sys.executable))
                self.assertEqual(c.read_controllers(),[])
                active=None
        finally:
            active=active or c.pid_file(c.analog/'adapter.pid',sys.executable)
            if active:
                subprocess.run(['taskkill','/PID',str(active),'/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW)


if __name__=='__main__':unittest.main()

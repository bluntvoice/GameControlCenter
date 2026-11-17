"""Regress stale ADB 'already connected' without touching a real phone."""
import subprocess
import unittest
from unittest.mock import Mock,patch
from backend import Center

def reply(stdout='',stderr='',code=0):
    return subprocess.CompletedProcess([],code,stdout,stderr)

class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.center=Center.__new__(Center)
        self.center.config=dict(adb='adb.exe',serial='192.0.2.10:5555',gamescrcpy='GameScrcpy.exe')
        self.center.event=Mock()
        self.center.request_pad=Mock();self.center.labels_pid=Mock(return_value=None)
        self.center.save_preferences=Mock(side_effect=self.center.config.update)
        self.center.profiles=Mock();self.center.profiles.load.return_value=dict(path='example.json',name='测试方案')
    def invoke(self,responses):
        with patch('backend.winprobe.windows',return_value=[]),patch('backend.subprocess.run',side_effect=responses) as run:
            self.center.connect_phone()
        return [c.args[0][1:] for c in run.call_args_list]
    def test_online_session_is_preserved(self):
        calls=self.invoke([reply('List of devices attached\n192.0.2.10:5555 device'),reply(''),reply('device\n')])
        self.assertEqual(calls,[['devices','-l'],['mdns','services'],['-s','192.0.2.10:5555','get-state']])
        self.assertEqual(self.center.event.call_args.args[1],'ok')
    def test_offline_already_connected_is_recovered_for_target_only(self):
        calls=self.invoke([reply(''),reply(''),reply('already connected'),reply(stderr='device offline',code=1),reply('disconnected'),reply('connected'),reply('device\n')])
        self.assertEqual(calls[4],['disconnect','192.0.2.10:5555'])
        self.assertEqual(len(calls),7)
        self.assertEqual(self.center.event.call_args.args[1],'ok')
    def test_still_offline_never_reports_success(self):
        with self.assertRaisesRegex(RuntimeError,'仍未在线'):
            self.invoke([reply(''),reply(''),reply('already connected'),reply('offline',code=1),reply(),reply('connected'),reply('offline',code=1)])
        self.assertFalse(any(c.args[1]=='ok' for c in self.center.event.call_args_list))
    def test_unauthorized_requires_phone_authorization_without_reset(self):
        with patch('backend.winprobe.windows',return_value=[]),patch('backend.subprocess.run',side_effect=[reply(''),reply(''),reply('connected'),reply(stderr='device unauthorized',code=1)]) as run:
            with self.assertRaisesRegex(RuntimeError,'尚未授权'):self.center.connect_phone()
        self.assertEqual(run.call_count,4)
    def test_timeout_is_actionable(self):
        with self.assertRaisesRegex(RuntimeError,'连接超时'):
            self.invoke([subprocess.TimeoutExpired('adb',8)])

    def test_minimized_projection_keeps_its_active_transport(self):
        window=dict(title='Phone - 192.0.2.10:5555',visible=True,minimized=True,pid=123)
        process=Mock(path='GameScrcpy.exe')
        connection=dict(serial='192.0.2.10:5555',phone_address='192.0.2.10:5555',device_identity='phone')
        with patch('backend.winprobe.windows',return_value=[window]),patch('backend.winprobe.Process',return_value=process),patch('backend.connect_device',return_value=connection) as connect:
            self.center.connect_phone()
        self.assertEqual(connect.call_args.kwargs['active_serial'],'192.0.2.10:5555')
        self.center.request_pad.assert_not_called()
        process.close.assert_called_once()

if __name__=='__main__':unittest.main()

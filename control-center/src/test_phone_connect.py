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
        self.center.config=dict(adb='adb.exe',serial='192.0.2.10:5555')
        self.center.event=Mock()
    def invoke(self,responses):
        with patch('backend.subprocess.run',side_effect=responses) as run:
            self.center.connect_phone()
        return [c.args[0][1:] for c in run.call_args_list]
    def test_online_session_is_preserved(self):
        calls=self.invoke([reply('already connected'),reply('device\n')])
        self.assertEqual(calls,[['connect','192.0.2.10:5555'],['-s','192.0.2.10:5555','get-state']])
        self.assertEqual(self.center.event.call_args.args[1],'ok')
    def test_offline_already_connected_is_recovered_for_target_only(self):
        calls=self.invoke([reply('already connected'),reply(stderr='device offline',code=1),reply('disconnected'),reply('connected'),reply('device\n')])
        self.assertEqual(calls[2],['disconnect','192.0.2.10:5555'])
        self.assertEqual(len(calls),5)
        self.assertEqual(self.center.event.call_args.args[1],'ok')
    def test_still_offline_never_reports_success(self):
        with self.assertRaisesRegex(RuntimeError,'仍未在线'):
            self.invoke([reply('already connected'),reply('offline'),reply(),reply('connected'),reply('offline')])
        self.assertFalse(any(c.args[1]=='ok' for c in self.center.event.call_args_list))
    def test_unauthorized_requires_phone_authorization_without_reset(self):
        with patch('backend.subprocess.run',side_effect=[reply('connected'),reply(stderr='device unauthorized',code=1)]) as run:
            with self.assertRaisesRegex(RuntimeError,'尚未授权'):self.center.connect_phone()
        self.assertEqual(run.call_count,2)
    def test_timeout_is_actionable(self):
        with self.assertRaisesRegex(RuntimeError,'连接超时'):
            self.invoke([subprocess.TimeoutExpired('adb',8)])

if __name__=='__main__':unittest.main()

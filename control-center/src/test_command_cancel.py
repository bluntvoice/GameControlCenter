"""Slow connection commands must yield to Pause and Stop without a phone."""
import subprocess
import sys
import threading
import time
import unittest
from pad_transport import COMMAND_CONTEXT,run_command

class CommandCancelTests(unittest.TestCase):
    def tearDown(self):COMMAND_CONTEXT.cancel=None
    def test_cancel_reaps_slow_child_before_control_ack_deadline(self):
        cancel=threading.Event();COMMAND_CONTEXT.cancel=cancel
        timer=threading.Timer(.2,cancel.set);timer.start();started=time.monotonic()
        try:
            with self.assertRaisesRegex(RuntimeError,'已取消'):
                run_command([sys.executable,'-c','import time;time.sleep(30)'],capture_output=True,timeout=10)
        finally:timer.cancel()
        self.assertLess(time.monotonic()-started,2)
    def test_command_timeout_still_applies(self):
        COMMAND_CONTEXT.cancel=threading.Event()
        with self.assertRaises(subprocess.TimeoutExpired):
            run_command([sys.executable,'-c','import time;time.sleep(30)'],capture_output=True,timeout=.2)
    def test_normal_output_and_exit_status_are_preserved(self):
        COMMAND_CONTEXT.cancel=threading.Event()
        result=run_command([sys.executable,'-c','print("ready")'],capture_output=True,encoding='utf-8',timeout=3)
        self.assertEqual(result.stdout.strip(),'ready');self.assertEqual(result.returncode,0)

"""Exercise failed ACK and cleanup paths without ADB or injected input."""
import queue
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import pad_adapter
import pad_transport
from touch_queue import TouchQueue
from pad_core import recenter_axis_pair,radial

class CleanupTests(unittest.TestCase):
    def test_measured_rest_offset_becomes_neutral_without_enlarging_deadzone(self):
        center=(-.12558366649,-.0544450209)
        self.assertEqual(recenter_axis_pair(center,center),(0,0))
        self.assertEqual(recenter_axis_pair((-1,-1),center),(-1,-1))
        self.assertEqual(recenter_axis_pair((1,1),center),(1,1))
        self.assertEqual(recenter_axis_pair((.4,-.3)),(.4,-.3))
        # A deliberate movement beyond the original 12% deadzone still responds.
        moved=recenter_axis_pair((center[0]+.15,center[1]),center)
        self.assertGreater(radial(*moved,.12)[0],0)
    def test_idle_uses_heartbeat_but_changed_position_and_release_are_immediate(self):
        self.assertTrue(pad_adapter.frame_due({},None,1,1))
        self.assertFalse(pad_adapter.frame_due({},{},1.008,1))
        self.assertTrue(pad_adapter.frame_due({},{},1.051,1))
        previous={1:(100,200)}
        self.assertFalse(pad_adapter.frame_due(previous,dict(previous),1.008,1))
        self.assertTrue(pad_adapter.frame_due({1:(101,200)},previous,1.008,1))
        self.assertTrue(pad_adapter.frame_due({},previous,1.008,1))
    def test_bad_final_ack_still_closes_every_owned_resource(self):
        transport=pad_transport.Transport.__new__(pad_transport.Transport)
        transport.sock=Mock();sock=transport.sock
        transport.proc=Mock();proc=transport.proc
        transport.log=Mock();log=transport.log;transport.port=12345
        transport.frame=Mock(side_effect=RuntimeError('Unexpected touch acknowledgement'))
        with patch.object(pad_transport,'adb') as adb:
            with self.assertRaisesRegex(RuntimeError,'Unexpected touch acknowledgement'):transport.close()
        sock.close.assert_called_once();proc.wait.assert_called_once();log.close.assert_called_once()
        adb.assert_called_once_with('forward','--remove','tcp:12345',timeout=3)
        self.assertIsNone(transport.sock);self.assertIsNone(transport.proc);self.assertIsNone(transport.port)
    def test_worker_always_reports_closed_when_frame_and_cleanup_both_fail(self):
        worker=pad_adapter.Worker.__new__(pad_adapter.Worker)
        worker.snapshots=TouchQueue()
        worker.reset_pending=False
        worker.events=queue.Queue();worker.stop=threading.Event();worker.lock=threading.Lock();worker.latest={}
        transport=Mock();transport.info=dict(width=2608,height=1200)
        transport.frame.side_effect=TimeoutError('timed out')
        transport.close.side_effect=RuntimeError('bad final ACK')
        with patch.object(pad_adapter,'antimicrox_gate',return_value=dict(allow=True)),patch.object(pad_adapter,'find_video',return_value=123),patch.object(pad_adapter,'run_command',return_value=SimpleNamespace(returncode=0,stdout='{"handle":123}',stderr='')),patch.object(pad_adapter,'Transport',return_value=transport):
            worker.run()
        events=[]
        while not worker.events.empty():events.append(worker.events.get_nowait())
        self.assertEqual([kind for kind,_ in events],['connected','error','error','closed'])
        self.assertIn('timed out',events[1][1]);self.assertIn('bad final ACK',events[2][1])
    def test_delayed_ack_reuses_inflight_request_and_neutral_reset_is_distinct(self):
        transport=pad_transport.Transport.__new__(pad_transport.Transport)
        transport.sock=Mock()
        transport.sock.recv.side_effect=[TimeoutError('brief jitter'),b'\x01']
        transport.frame({1:(100,200)})
        self.assertEqual(transport.sock.sendall.call_count,1)
        transport.sock.recv.side_effect=[b'\xff']
        with self.assertRaises(pad_transport.NeutralRequired):transport.frame({1:(100,200)})

if __name__=='__main__':unittest.main()

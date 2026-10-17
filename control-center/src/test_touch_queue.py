"""Slow ACK replay with fake transport; no phone input or Windows hotkeys."""
import queue,threading,time,unittest
from types import SimpleNamespace
from unittest.mock import patch
from touch_queue import TouchQueue
import pad_adapter

class QueueTests(unittest.TestCase):
    def test_short_down_up_survives_latest_snapshot_overwrite(self):
        q=TouchQueue();q.offer({6:(10,20)},0);q.offer({},.02)
        down=q.take(.08);self.assertEqual(down,{6:(10,20)});q.mark_sent(down,.08)
        self.assertEqual(q.take(.09),down)
        self.assertEqual(q.take(.12),{})
    def test_pause_releases_immediately_and_clears_pending_press(self):
        q=TouchQueue();q.offer({6:(10,20)},0);q.mark_sent(q.take(0),0)
        q.offer({6:(10,20),7:(30,40)},.001)
        q.offer({},.002,active=False)
        self.assertEqual(q.take(.003),{});self.assertFalse(q.edges)
    def test_pause_boundary_must_send_empty_before_a_new_down(self):
        q=TouchQueue();q.offer({6:(10,20)},0);q.mark_sent(q.take(0),0)
        q.offer({},.01,active=False);q.offer({6:(30,40)},.02)
        self.assertEqual(q.take(.03),{})
        q.mark_sent({},.03)
        self.assertEqual(q.take(.04),{6:(30,40)})
    def test_old_taps_expire_and_queue_is_bounded(self):
        q=TouchQueue();q.offer({6:(1,2)},0);q.offer({},.02)
        self.assertEqual(q.take(.4),{});self.assertEqual(q.expired,2)
        for i in range(100):q.offer({6:(1,2)} if i%2==0 else {},1+i*.001)
        self.assertLessEqual(len(q.edges),32)
    def test_stick_updates_do_not_queue_motion_or_replay_old_coordinates(self):
        q=TouchQueue();q.offer({1:(100,200)},0);q.mark_sent(q.take(0),0)
        q.offer({1:(110,200),6:(1,2)},.01)
        q.offer({1:(150,200)},.02)
        down=q.take(.03)
        self.assertEqual(down[1],(150,200));self.assertIn(6,down)
        q.mark_sent(down,.03);q.offer({1:(180,200)},.035)
        self.assertEqual(q.take(.04)[1],(180,200))

class WorkerReplayTests(unittest.TestCase):
    def test_real_worker_sends_tap_after_a_held_up_ack(self):
        worker=pad_adapter.Worker.__new__(pad_adapter.Worker)
        worker.events=queue.Queue();worker.stop=threading.Event();worker.lock=threading.Lock()
        worker.latest={};worker.updated=time.monotonic();worker.reset_pending=False
        worker.snapshots=TouchQueue();worker.frames=0;worker.latency=0
        first=threading.Event();release=threading.Event();done=threading.Event();frames=[]
        class Transport:
            info=dict(width=2608,height=1200)
            def start(self):pass
            def close(self):pass
            def frame(self,points):
                frames.append(dict(points))
                if len(frames)==1:first.set();release.wait(1)
                elif 6 in points:done.set()
                elif done.is_set():worker.stop.set()
        with patch.object(pad_adapter,'antimicrox_gate',return_value=dict(allow=True)),patch.object(pad_adapter,'find_video',return_value=123),patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='{"handle":123}',stderr='')),patch.object(pad_adapter,'Transport',return_value=Transport()):
            thread=threading.Thread(target=worker.run);thread.start()
            try:
                self.assertTrue(first.wait(1))
                worker.update({6:(100,200)})
                worker.update({})
                release.set();thread.join(1)
                self.assertFalse(thread.is_alive())
                self.assertTrue(done.is_set())
                self.assertEqual(frames[0],{});self.assertIn({6:(100,200)},frames)
                self.assertEqual(frames[-1],{})
            finally:release.set();worker.stop.set();thread.join(2)

if __name__=='__main__':unittest.main()

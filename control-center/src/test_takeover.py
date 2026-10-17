"""Isolated acceptance tests: no ADB injection and no real controller hotkeys."""
import ctypes as C
from ctypes import wintypes as W
import importlib
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT/'tools/analog'))
import pad_adapter as module
from input_ownership import decide,inspect_profile
from pad_core import normalized,Mapper,BUTTON_IDS
from touch_queue import TouchQueue
from phoneprobe import latency_parse,battery_parse,layer_pick
import winprobe

class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.processes=[dict(pid=123,visible=True)]
        self.blank=dict(valid=True,name='空白方案-无映射-右摇杆归适配器',slot_count=0,modes=[])
    def test_stopped_or_live_new_is_allowed(self):
        self.assertTrue(decide([],('no-process',''),{})['allow'])
        self.assertTrue(decide(self.processes,('read','<新>'),{})['allow'])
    def test_keyboard_only_merge_does_not_get_permission(self):
        # No mouse output is insufficient: the adapter already owns every button.
        info=dict(valid=True,name='合并方案',slot_count=12,modes=['keyboard'])
        self.assertFalse(decide(self.processes,('read','合并方案'),info)['allow'])
    def test_hidden_live_profile_cannot_be_inferred_from_ini(self):
        self.assertFalse(decide([dict(pid=123,visible=False)],('unreadable',''),self.blank)['allow'])
    def test_only_explicit_zero_slot_blank_is_allowed(self):
        self.assertTrue(decide(self.processes,('read',self.blank['name']),self.blank)['allow'])
        self.assertFalse(decide(self.processes,('read',self.blank['name']),dict(self.blank,slot_count=1))['allow'])
    def test_real_generated_blank_has_no_output(self):
        info=inspect_profile(PROJECT/'phase2b-20261015/profiles/blank-no-keys/blank.amgp')
        self.assertTrue(info['valid']);self.assertEqual(info['slot_count'],0)

class FrameTests(unittest.TestCase):
    def frames(self,start,count=127):
        times=[int((start+i/60)*1e9) for i in range(count)]
        return '16666666\n'+'\n'.join(f'{n}\t{n}\t{n}' for n in times)
    def test_real_rate_not_biased_by_overwritten_ring_gap(self):
        first=latency_parse(self.frames(100))
        later=latency_parse(self.frames(103),first['last_timestamp'])
        self.assertAlmostEqual(first['fps'],60,places=1)
        self.assertAlmostEqual(later['fps'],60,places=1)
    def test_no_new_or_missing_frame_is_unknown_not_zero(self):
        first=latency_parse(self.frames(100))
        self.assertIsNone(latency_parse(self.frames(100),first['last_timestamp'])['fps'])
        self.assertIsNone(latency_parse('16666666\n0\t9223372036854775807\t0')['fps'])
    def test_android17_layer_and_battery(self):
        layer='RequestedLayerState{abc SurfaceView[com.netease.party/.Client](BLAST)#12 parentId=3}'
        self.assertEqual(layer_pick(layer,'com.netease.party'),'abc SurfaceView[com.netease.party/.Client](BLAST)#12')
        self.assertIsNone(layer_pick('no game','com.netease.party'))
        battery=battery_parse('  level: 52\n  scale: 100\n  status: 2\n  temperature: 389\n')
        self.assertEqual(battery['percent'],52);self.assertTrue(battery['charging']);self.assertEqual(battery['temperature'],38.9)

class FakeUser:
    foreground=111
    def GetForegroundWindow(self):return self.foreground
    def GetAncestor(self,*a):return 111
    def SetForegroundWindow(self,h):self.foreground=h;return True
    def IsWindow(self,h):return True
    def IsIconic(self,h):return False

class FakeWorker:
    def __init__(self,events):
        self.events=events;self.latest={};self.stop=threading.Event();self.frames=0;self.latency=0.1
        self.snapshots=TouchQueue()
        self.events.put(('connected',dict(width=2608,height=1200)))
    def update(self,points,active=True):
        self.latest=dict(points);self.snapshots.offer(points,0,active=active)
    def acknowledge_reset(self):self.latest={}

class AdapterLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.phase=Path(self.temp.name)
        (self.phase/'analog').mkdir()
        (self.phase/'analog/settings.json').write_text((PROJECT/'phase2b-20261015/analog/settings.json').read_text(encoding='utf-8'),encoding='utf-8')
        profile=json.loads((Path(__file__).resolve().parents[2]/'examples/超燃竞技场-三技能.json').read_text(encoding='utf-8'))
        self.user=FakeUser();self.clock=10.0
        self.patches=[patch.object(module,'PHASE',self.phase),patch.object(module,'STATUS',self.phase/'analog/status.json'),
            patch.object(module,'user32',self.user),patch.object(module,'Worker',FakeWorker),
            patch.object(module,'find_video',return_value=222),patch.object(module,'current_profile',return_value=(profile,'fixed')),
            patch.object(module,'antimicrox_gate',return_value=dict(allow=True))]
        for p in self.patches:p.start()
        self.app=module.App();self.app.root.withdraw()
        self.app.auto_foreground=False
        self.app.pad=type('Pad',(),{'read':lambda obj:self.state})()
        self.app.show_shield=lambda:setattr(self.app,'shield_hwnd',111)
        self.state=dict(left=(0,0),right=(0,0),buttons=[],packet=0,index=0)
        self.cancel_timers()
    def cancel_timers(self):
        for timer in self.app.root.tk.call('after','info'):self.app.root.after_cancel(timer)
    def advance(self,seconds=.02):
        self.clock+=seconds
        with patch.object(module.time,'monotonic',return_value=self.clock):self.app.tick()
        self.cancel_timers()
    def enable(self):
        self.state['buttons']=['START'];self.advance();self.advance()
        self.assertTrue(self.app.armed)
        self.state['buttons']=[];self.advance(.3);self.assertFalse(self.app.neutral_wait)
    def tearDown(self):
        self.app.root.destroy()
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def test_start_is_edge_triggered_then_pauses_on_next_press(self):
        self.state['buttons']=['START'];self.advance();self.advance();self.advance()
        self.assertTrue(self.app.armed)
        self.state['buttons']=[];self.advance(.3)
        self.state['buttons']=['START'];self.advance()
        self.assertFalse(self.app.armed);self.assertTrue(self.app.worker.stop.is_set())
    def test_focus_suspend_keeps_status_fresh_and_clears_pointer_state(self):
        self.enable();self.state['left']=(.5,.2);self.advance();self.advance()
        self.assertTrue(self.app.points)
        self.user.foreground=999
        for _ in range(4):self.advance(.2)
        self.assertTrue(self.app.armed);self.assertTrue(self.app.focus_suspended)
        self.assertEqual(self.app.worker.latest,{})
        status=json.loads((self.phase/'analog/status.json').read_text(encoding='utf-8'))
        self.assertTrue(status['focus_suspended']);self.assertFalse(status['delivery_enabled'])
        self.assertTrue(status['channel_active']);self.assertEqual(status['points'],{})
        self.assertEqual(self.app.mapper.previous,{})
    def test_resume_held_stick_starts_at_center_without_requiring_other_stick_neutral(self):
        self.enable();self.state['left']=(.5,0);self.advance();self.advance()
        self.user.foreground=999
        for _ in range(4):self.advance(.1)
        self.user.foreground=111;self.advance()
        time.sleep(.02);self.advance(.2)
        self.assertTrue(self.app.neutral_wait);self.assertEqual(self.app.points,{})
        self.advance(.11)
        self.assertFalse(self.app.neutral_wait)
        self.state['right']=(.7,.2);self.advance()
        center=self.app.mapper.wheel['centerPos']
        self.assertEqual(self.app.points[1],normalized((center['x'],center['y'])))
    def test_shield_withdraws_outside_video_and_returns_after_owner_check(self):
        changes=[]
        self.app.shield_delivery=lambda active:changes.append(active)
        self.enable();self.user.foreground=999
        for _ in range(4):self.advance(.1)
        self.assertEqual(changes,[False])
        self.user.foreground=222;self.advance();time.sleep(.02);self.advance(.2)
        self.assertEqual(changes,[False,True]);self.assertTrue(self.app.neutral_wait)
    def test_late_owner_check_does_not_steal_another_app_focus(self):
        self.enable();self.app.focus_suspended=True;self.app.resume_checking=True
        self.user.foreground=999
        self.app.events.put(('ownership_resume',(self.app.session_token,dict(allow=True))))
        self.advance()
        self.assertTrue(self.app.focus_suspended);self.assertFalse(self.app.resume_checking)
        self.assertEqual(self.app.points,{})
    def test_foreground_auto_starts_without_start_button_and_start_is_free(self):
        self.app.auto_foreground=True;self.user.foreground=222
        self.advance(.3);self.advance(.3);self.advance(.3)
        self.assertTrue(self.app.armed);self.assertFalse(self.app.neutral_wait)
        self.state['buttons']=['START'];self.advance()
        self.assertTrue(self.app.armed)
    def test_auto_starts_with_no_gamepad_and_keeps_mouse_on_disconnect(self):
        self.app.auto_foreground=True;self.user.foreground=222;self.state=None
        self.advance(.3);self.advance(.3);self.advance(.3)
        self.assertTrue(self.app.armed);self.assertFalse(self.app.neutral_wait)
        worker=self.app.worker
        self.app.mouse.configure([dict(name='鼠标右键',x=.5,y=.5,mode='once')])
        self.app.mouse.event('down',10,10,100,100,'right');self.advance()
        self.assertIn(19,self.app.points)
        self.state=dict(left=(.6,0),right=(0,0),buttons=[],packet=0,index=0)
        self.advance();self.advance();self.assertIn(1,self.app.points)
        self.state=None;self.advance()
        self.assertIs(self.app.worker,worker);self.assertTrue(self.app.armed)
        self.assertNotIn(1,self.app.points);self.assertFalse(worker.stop.is_set())
        self.app.mouse.event('up',10,10,100,100,'right');self.advance(.1)
        self.app.mouse.event('down',10,10,100,100,'right');self.advance()
        self.assertIn(19,self.app.points)
    def test_reconnecting_pad_does_not_fire_buttons_held_on_reconnect(self):
        self.enable();self.state=None;self.advance();self.assertTrue(self.app.armed)
        self.state=dict(left=(.5,0),right=(0,0),buttons=['RB'],packet=0,index=0)
        self.advance();self.assertIn(1,self.app.points);self.assertNotIn(BUTTON_IDS['RB'],self.app.points)
        self.state['buttons']=[];self.advance();self.state['buttons']=['RB'];self.advance()
        self.assertIn(BUTTON_IDS['RB'],self.app.points)
    def test_auto_does_not_start_outside_projection_or_override_manual_pause(self):
        self.app.auto_foreground=True;self.user.foreground=999
        self.advance(.3);self.assertIsNone(self.app.worker)
        self.app.pause('配置编辑',manual=True);self.user.foreground=222
        self.advance(5);self.assertIsNone(self.app.worker)
        self.app.start();self.advance(.3);self.assertTrue(self.app.armed)
    def test_transport_failure_closes_and_auto_recovers_on_foreground(self):
        self.enable();self.app.auto_foreground=True;self.user.foreground=222
        self.app.events.put(('error','timed out'));self.app.events.put(('closed',None));self.advance()
        self.assertIsNone(self.app.worker);self.assertFalse(self.app.armed)
        self.advance(4.2);self.advance(.3);self.advance(.3)
        self.assertTrue(self.app.armed);self.assertFalse(self.app.neutral_wait)
        self.assertFalse(self.app.manual_pause)
    def test_timeout_hands_foreground_back_before_withdrawing_shield_and_recovers(self):
        self.enable();self.app.auto_foreground=True;self.user.foreground=111
        changes=[];self.app.shield=object()
        def withdraw(active):
            changes.append(active)
            # Reproduce Windows restoring the previous app if its active input
            # shield disappears without first handing foreground to the video.
            if not active and self.user.foreground==111:self.user.foreground=999
        self.app.shield_delivery=withdraw
        self.app.events.put(('error','timed out'));self.advance()
        self.assertEqual(self.user.foreground,222)
        self.assertEqual(changes,[False]);self.assertTrue(self.app.recovery_pending)
        self.app.shield=None
        self.app.events.put(('closed',None));self.advance()
        self.advance(1.2);self.advance(.3);self.advance(.3)
        self.assertTrue(self.app.armed);self.assertFalse(self.app.neutral_wait)
        self.assertFalse(self.app.recovery_pending);self.assertEqual(self.app.reconnects,1)
    def test_timeout_does_not_activate_video_if_user_already_switched_away(self):
        self.enable();self.app.auto_foreground=True;self.user.foreground=999
        self.app.shield=object();self.app.shield_delivery=lambda active:None
        self.app.pause('timed out')
        self.assertEqual(self.user.foreground,999)
        self.app.shield=None;self.app.events.put(('closed',None));self.advance()
        self.advance(3)
        self.assertIsNone(self.app.worker);self.assertTrue(self.app.recovery_pending)
    def test_manual_pause_still_blocks_retry_after_timeout(self):
        self.enable();self.app.auto_foreground=True;self.user.foreground=222
        self.app.events.put(('error','timed out'));self.advance()
        self.app.pause('手动暂停',manual=True)
        self.app.events.put(('closed',None));self.advance();self.advance(5)
        self.assertIsNone(self.app.worker);self.assertTrue(self.app.manual_pause)
        self.assertFalse(self.app.recovery_pending)
    def test_phone_watchdog_reset_keeps_channel_then_resumes_held_stick_without_global_neutral(self):
        self.enable();worker=self.app.worker
        self.state['left']=(.6,.2);self.advance()
        self.app.events.put(('touch_reset',None));self.advance(.2)
        self.assertIs(self.app.worker,worker);self.assertTrue(self.app.armed)
        self.assertTrue(self.app.neutral_wait);self.assertEqual(self.app.points,{})
        self.advance(.3)
        self.assertFalse(self.app.neutral_wait);self.assertEqual(self.app.touch_resets,1)
        self.advance();self.assertIn(1,self.app.points)
    def test_pause_withdraws_shield_before_worker_has_closed(self):
        self.enable();changes=[]
        self.app.shield=object();self.app.shield_delivery=lambda active:changes.append(active)
        self.app.pause('手动暂停',manual=True)
        self.assertEqual(changes,[False]);self.assertTrue(self.app.worker.stop.is_set())
        self.assertFalse(self.app.armed);self.assertTrue(self.app.manual_pause)
        self.app.shield=None
    def test_windows_status_reader_lock_does_not_stop_input_tick(self):
        self.enable();path=self.phase/'analog/status.json'
        kernel=C.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,C.c_void_p,W.DWORD,W.DWORD,W.HANDLE]
        kernel.CreateFileW.restype=W.HANDLE;kernel.CloseHandle.argtypes=[W.HANDLE]
        handle=kernel.CreateFileW(str(path),0x80000000,3,None,3,0,None)
        self.assertNotEqual(handle,W.HANDLE(-1).value)
        try:
            self.clock+=1
            with patch.object(module.time,'monotonic',return_value=self.clock):self.app.tick()
            self.assertTrue(self.app.root.tk.call('after','info'))
            self.assertTrue(self.app.armed)
            self.cancel_timers()
        finally:kernel.CloseHandle(handle)
        self.advance(.2)
        self.assertTrue(json.loads(path.read_text(encoding='utf-8'))['armed'])

class ContinuousResumeTests(unittest.TestCase):
    def mapper(self,radius=75):
        profile=dict(keyMapNodes=[dict(type='KMT_STEER_WHEEL',centerPos=dict(x=.2,y=.7),
            leftOffset=radius/2608,rightOffset=radius/2608,upOffset=radius/1200,downOffset=radius/1200),
            dict(type='KMT_CLICK',key='Key_4',pos=dict(x=.8,y=.5)),
            dict(type='KMT_CLICK',key='Key_3',pos=dict(x=.9,y=.6))])
        return Mapper(profile,2608,1200,dict(left_deadzone=.1,right_deadzone=.12,right_curve=1.5,camera_px_per_sec=800,skill_radius_px=90))
    def test_full_left_stick_reaches_configured_travel_despite_inner_deadzone(self):
        for radius in (20,75):
            mapper=self.mapper(radius);state=dict(left=(1,0),right=(0,0),buttons=[])
            first=mapper.frame(state,0);full=mapper.frame(state,.02)
            self.assertEqual(first[1],normalized((.2,.7)))
            self.assertEqual(full[1],normalized((.2+radius/2608,.7)))
    def test_resume_filters_only_buttons_held_before_resume_not_other_controls(self):
        mapper=self.mapper();state=dict(left=(.8,.1),right=(.5,.2),buttons=['Y'])
        mapper.guard_resume(state);frame=mapper.frame(state,0)
        self.assertIn(1,frame);self.assertNotIn(BUTTON_IDS['Y'],frame)
        state['buttons']=['Y','X'];frame=mapper.frame(state,.02)
        self.assertIn(BUTTON_IDS['X'],frame);self.assertNotIn(BUTTON_IDS['Y'],frame)
        state['buttons']=[];mapper.frame(state,.04)
        state['buttons']=['Y'];frame=mapper.frame(state,.06)
        self.assertIn(BUTTON_IDS['Y'],frame)

class NativeProcessTests(unittest.TestCase):
    def test_nonzero_exit_code_is_observable_without_crashing_an_app(self):
        child=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(.25);raise SystemExit(3)'],creationflags=subprocess.CREATE_NO_WINDOW)
        handle=winprobe.Process(child.pid)
        try:
            self.assertTrue(handle.alive());child.wait(timeout=3);self.assertEqual(handle.exit_code(),3)
        finally:handle.close()
    def test_unresponsive_window_probe_is_bounded(self):
        code='import tkinter as t,time; r=t.Tk();r.withdraw();r.update();print(r.winfo_id(),flush=True);time.sleep(2.0)'
        child=subprocess.Popen([sys.executable,'-B','-c',code],stdout=subprocess.PIPE,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            hwnd=int(child.stdout.readline().strip());begin=time.monotonic()
            self.assertFalse(winprobe.responds(hwnd,100));self.assertLess(time.monotonic()-begin,1)
            child.wait(timeout=4)
        finally:
            if child.poll() is None:child.terminate();child.wait(timeout=2)
            child.stdout.close()

if __name__=='__main__':unittest.main(verbosity=2)

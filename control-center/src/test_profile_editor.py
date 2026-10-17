"""Profile persistence, switch ordering, geometry, and merged input regressions."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock,patch
from backend import Center
from profile_store import ProfileStore,native_from_controls,validate_name
from profile_editor import drop_position
from pad_core import Mapper,BUTTON_IDS
from mouse_touch import MouseChannels,merge

PROJECT=Path(__file__).resolve().parents[2]
LEGACY=(Path(__file__).resolve().parents[2]/'examples/超燃竞技场-三技能.json')
SETTINGS=json.loads((PROJECT/'phase2b-20261015/analog/settings.json').read_text(encoding='utf-8'))
def control(name,x=.5,y=.6,**kw):return dict(name=name,x=x,y=y,mode='hold',radius=75,hz=10,**kw)
def state(buttons=(),left=(0,0),right=(0,0)):return dict(buttons=buttons,left=left,right=right)

class ProfileEditorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.keymap=self.root/'keymap';self.keymap.mkdir()
        shutil.copy2(LEGACY,self.keymap/LEGACY.name)
        self.store=ProfileStore(self.root,self.keymap);self.store.ensure()
    def tearDown(self):self.temp.cleanup()
    def test_registration_preserves_calibrated_profile_and_behavior(self):
        self.assertEqual((self.keymap/LEGACY.name).read_bytes(),LEGACY.read_bytes())
        profile,_=self.store.active_runtime();old=json.loads(LEGACY.read_bytes())
        before=Mapper(old,2608,1200,SETTINGS);after=Mapper(profile,2608,1200,SETTINGS)
        for i in range(35):
            s=state(buttons=['X','Y','A'],left=(.4,.7),right=(.5,-.2))
            self.assertEqual(before.frame(s,i*.02),after.frame(s,i*.02))
    def test_blank_profile_subset_has_no_phantom_bindings(self):
        entry=self.store.save('中文 新方案',[control('A')]);self.store.select(entry['id'])
        profile,_=self.store.active_runtime();m=Mapper(profile,2608,1200,SETTINGS)
        self.assertEqual(set(m.frame(state(['A','LB','X'],(.5,.2),(.2,.3)),0)),{BUTTON_IDS['A']})
    def test_once_and_repeat_are_per_binding(self):
        controls=[dict(control('A'),mode='once'),dict(control('LB'),mode='repeat',hz=10)]
        entry=self.store.save('触发测试',controls);self.store.select(entry['id']);p,_=self.store.active_runtime();m=Mapper(p,2608,1200,SETTINGS)
        held=state(['A','LB']);self.assertEqual(len(m.frame(held,0)),2)
        self.assertEqual(m.frame(held,.06),{})
        self.assertEqual(set(m.frame(held,.11)),{BUTTON_IDS['LB']})
        m.frame(state(),.13);self.assertIn(BUTTON_IDS['A'],m.frame(held,.14))
    def test_normal_defaults_to_one_repeat_to_ten_without_changing_hold_duration(self):
        controls=[control('A'),dict(control('X'),mode='once'),dict(control('LB'),mode='repeat')]
        controls[2].pop('hz')
        entry=self.store.save('默认次数',controls)
        self.assertEqual([c['hz'] for c in entry['controls']],[1,1,10])
        self.assertEqual(controls[0]['hz'],10)  # Save must not mutate the caller's draft.
        self.store.select(entry['id']);p,_=self.store.active_runtime();m=Mapper(p,2608,1200,SETTINGS)
        held=state(['A','X','LB']);m.frame(held,0)
        self.assertEqual(set(m.frame(held,.06)),{BUTTON_IDS['A']})
        self.assertEqual(set(m.frame(held,.11)),{BUTTON_IDS['A'],BUTTON_IDS['LB']})
        self.assertEqual(set(m.frame(held,1.06)),{BUTTON_IDS['A']})
        self.assertEqual(m.frame(state(),1.07),{})
    def test_existing_custom_repeat_frequency_is_preserved(self):
        entry=self.store.save('自定连点',[dict(control('LB'),mode='repeat',hz=6)])
        self.assertEqual(entry['controls'][0]['hz'],6)
    def test_both_mouse_buttons_fixed_and_left_free_fallback(self):
        mouse=MouseChannels();mouse.event('down',20,40,100,100)
        self.assertEqual(mouse.frame(0)[20],(13107,26214))
        mouse.configure([control('鼠标左键',.8,.4),control('鼠标右键',.3,.7)])
        mouse.event('down',1,1,100,100);mouse.event('down',1,1,100,100,'right')
        points=mouse.frame(0);self.assertEqual(set(points),{20,19})
        self.assertEqual(points[20],(52428,26214));self.assertEqual(points[19],(19660,45874))
        mouse.event('move',99,99,100,100);self.assertEqual(mouse.frame(.01),points)
        mouse.event('up',1,1,100,100);mouse.event('up',1,1,100,100,'right')
        self.assertEqual(mouse.frame(.02),points);self.assertEqual(mouse.frame(.05),{})
        merged=merge({i:(0,0) for i in range(1,15)},points)
        self.assertEqual(len(merged),10);self.assertTrue({20,19}<=merged.keys())
    def test_save_conflict_and_unsafe_names_do_not_overwrite(self):
        entry=self.store.save('冲突测试',[control('A')]);path=Path(entry['path']);path.write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'外部修改'):self.store.save(entry['name'],entry['controls'],entry['id'],entry['sha256'])
        self.assertEqual(path.read_text(encoding='utf-8'),'{}')
        for name in ['../escape','CON','name.','LPT2','a/b']:
            with self.assertRaises(ValueError):validate_name(name)
    def test_each_edit_has_backup_and_preserves_original_scheme(self):
        entry=self.store.save('新手柄',[control('A')]);old=Path(entry['path']).read_bytes()
        entry['controls'][0]['x']=.8
        self.store.save(entry['name'],entry['controls'],entry['id'],entry['sha256'])
        self.assertTrue(any(p.read_bytes()==old for p in self.store.backups.rglob('新手柄.json')))
        self.assertEqual((self.keymap/LEGACY.name).read_bytes(),LEGACY.read_bytes())
    def test_mouse_right_unmapped_and_reset_leave_no_touch(self):
        mouse=MouseChannels();mouse.event('down',1,1,100,100,'right');self.assertEqual(mouse.frame(0),{})
        mouse.event('down',1,1,100,100);mouse.frame(0);mouse.reset();self.assertEqual(mouse.frame(.2),{})
    def test_multiple_bindings_at_same_position_keep_independent_valid_pointer_ids(self):
        entry=self.store.save('同位置多绑定',[control('LB'),control('鼠标左键'),control('鼠标右键')])
        self.assertEqual(len(self.store.load(entry['id'])['controls']),3)
        self.store.select(entry['id']);profile,_=self.store.active_runtime()
        mapper=Mapper(profile,2608,1200,SETTINGS);mouse=MouseChannels();mouse.configure(entry['controls'])
        mouse.event('down',10,10,100,100);mouse.event('down',10,10,100,100,'right')
        points=merge(mapper.frame(state(['LB']),0),mouse.frame(0))
        self.assertEqual(len(points),3);self.assertEqual(len(set(points.values())),1)
        self.assertTrue(all(1<=ident<=20 for ident in points))
        mouse.event('up',10,10,100,100);self.assertEqual(set(mouse.frame(.06)),{19})
    def test_mouse_once_releases_while_held_and_requires_new_press(self):
        for button,name,ident in [('left','鼠标左键',20),('right','鼠标右键',19)]:
            mouse=MouseChannels();mouse.configure([dict(control(name,.8,.4),mode='once')])
            mouse.event('down',10,10,100,100,button)
            self.assertIn(ident,mouse.frame(0));self.assertEqual(mouse.frame(.06),{})
            self.assertEqual(mouse.frame(.5),{})
            mouse.event('up',10,10,100,100,button);mouse.frame(.51)
            mouse.event('down',10,10,100,100,button);self.assertIn(ident,mouse.frame(.52))
    def test_mouse_repeat_uses_saved_frequency_and_stops_on_release(self):
        mouse=MouseChannels();mouse.configure([dict(control('鼠标右键'),mode='repeat',hz=5)])
        mouse.event('down',10,10,100,100,'right')
        self.assertIn(19,mouse.frame(0));self.assertEqual(mouse.frame(.06),{})
        self.assertEqual(mouse.frame(.11),{});self.assertIn(19,mouse.frame(.21))
        mouse.event('up',10,10,100,100,'right');self.assertEqual(mouse.frame(.22),{})
        mouse.reset();self.assertEqual(mouse.frame(.41),{})
    def test_mouse_aim_drags_from_target_with_scaled_range(self):
        mouse=MouseChannels();mouse.configure([dict(control('鼠标左键',.5,.5),mode='aim',radius=90)])
        mouse.event('down',100,100,1200,600);self.assertEqual(mouse.frame(0)[20],(32768,32768))
        mouse.event('move',110,100,1200,600);self.assertEqual(mouse.frame(.01)[20],(33314,32768))
        mouse.event('move',400,100,1200,600);self.assertEqual(mouse.frame(.02)[20],(35225,32768))
        mouse.event('up',400,100,1200,600);self.assertEqual(mouse.frame(.06),{})
        mouse.reset();self.assertEqual(mouse.frame(.1),{})
    def test_drag_coordinates_exclude_frame_and_scale(self):
        self.assertEqual(drop_position((200,300,1000,500),700,550),(.5,.5))
        self.assertEqual(drop_position((100,150,500,250),350,275),(.5,.5))
        for point in [(199,400),(1200,400),(300,800),(300,299)]:self.assertIsNone(drop_position((200,300,1000,500),*point))
    def test_unsupported_duplicate_or_nonfinite_control_rejected(self):
        for controls in [[control('A'),control('A')],[control('Unknown')],[control('A',float('nan'))],[control('A',1.2)]]:
            with self.assertRaises(ValueError):self.store.save('不允许',controls)
    def test_switch_releases_then_changes_then_resumes(self):
        entry=self.store.save('第二套',[control('A')]);center=Center.__new__(Center)
        center.editing_profile=False;center.profiles=self.store;center.analog=self.root
        center.save_preferences=Mock();center.event=Mock();calls=[]
        def request(command):
            calls.append((command,self.store.entry()['id']))
        center.request_pad=request
        with patch('backend.read_json',return_value=dict(manual_pause=False)):
            center.switch_profile(entry['id'])
        self.assertEqual(calls,[('pause','arena-3skills'),('start',entry['id'])])
        with patch('backend.read_json',return_value=dict(manual_pause=True)):
            calls.clear();center.switch_profile('arena-3skills')
        self.assertEqual(calls,[('pause',entry['id'])])
    def test_editing_and_bad_target_cannot_change_active_scheme(self):
        center=Center.__new__(Center);center.profiles=self.store;center.editing_profile=True;center.request_pad=Mock()
        with self.assertRaisesRegex(RuntimeError,'结束方案编辑'):center.switch_profile('arena-3skills')
        center.editing_profile=False
        with self.assertRaises(ValueError):center.switch_profile('no such profile')
        center.request_pad.assert_not_called()

if __name__=='__main__':unittest.main()

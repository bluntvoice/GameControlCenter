"""Independent hit circles, mouse gestures and immutable running-version checks."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from backend import Center
from mouse_touch import MouseChannels
from profile_editor import control_at,ProfileEditor
from profile_store import validate_controls
from version_info import running_version

HOME=Path(__file__).resolve().parents[1]
def key(name='A',x=.5,y=.5,hit_radius=100):
    return dict(name=name,x=x,y=y,mode='hold',radius=90,hz=10,hit_radius=hit_radius)

class CoverageTests(unittest.TestCase):
    def test_inside_snaps_and_outside_keeps_free_pointer(self):
        mouse=MouseChannels();mouse.configure([key()])
        mouse.event('down',660,600,1200,1200)
        self.assertEqual(mouse.frame(0)[20],(32768,32768))
        mouse.reset();mouse.event('down',710,600,1200,1200)
        self.assertEqual(mouse.frame(0)[20],(38775,32768))
    def test_radius_scales_with_projection_height(self):
        for width,height in [(2400,1200),(1200,600)]:
            mouse=MouseChannels();mouse.configure([key()])
            mouse.event('down',width*.5+60*height/1200,height*.5,width,height)
            self.assertEqual(mouse.frame(0)[20],(32768,32768))
    def test_drag_keeps_relative_movement_after_snapping(self):
        mouse=MouseChannels();mouse.configure([key()]);mouse.event('down',650,600,1200,1200)
        self.assertEqual(mouse.frame(0)[20],(32768,32768))
        mouse.event('move',750,660,1200,1200)
        self.assertEqual(mouse.frame(.02)[20],(38229,36044))
        mouse.event('up',750,660,1200,1200);self.assertEqual(mouse.frame(.05),{})
        mouse.event('down',100,100,1200,1200);self.assertEqual(mouse.frame(.1)[20],(5461,5461))
    def test_overlapping_circles_choose_nearest_and_fixed_mouse_wins(self):
        mouse=MouseChannels();mouse.configure([key('A',.5,.5),key('B',.55,.5)])
        mouse.event('down',650,600,1200,1200);self.assertEqual(mouse.frame(0)[20],(36044,32768))
        mouse.configure([key('A'),key('鼠标左键',.8,.2)])
        mouse.event('down',600,600,1200,1200);self.assertEqual(mouse.frame(0)[20],(52428,13107))
    def test_zero_and_missing_radius_preserve_existing_mouse_behavior(self):
        for item in [key(hit_radius=0),{k:v for k,v in key().items() if k!='hit_radius'}]:
            mouse=MouseChannels();mouse.configure([item]);mouse.event('down',650,600,1200,1200)
            self.assertEqual(mouse.frame(0)[20],(35498,32768))
    def test_edit_selection_uses_circle_and_not_skill_aim_radius(self):
        item=key(hit_radius=200)
        self.assertEqual(control_at([item],1000,600,580,300),'A')
        item['hit_radius']=20;item['radius']=400
        self.assertIsNone(control_at([item],1000,600,580,300))
        item['hit_radius']=200
        self.assertEqual(control_at([item],500,300,290,150),'A')
    def test_invalid_radius_is_rejected(self):
        for radius in [-1,401,float('nan'),float('inf'),'50']:
            with self.assertRaises(ValueError):validate_controls([key(hit_radius=radius)])
    def test_unchanged_video_bounds_do_not_keep_raising_palette(self):
        editor=ProfileEditor.__new__(ProfileEditor)
        editor.overlay=Mock();editor.palette=Mock();editor.surface=dict(surface=2,video=1,width=2000,height=1000)
        editor.last_bounds=None;editor.draw=Mock()
        def get_rect(handle,pointer):
            rect=C.cast(pointer,C.POINTER(W.RECT)).contents
            rect.left=100;rect.top=200;rect.right=1100;rect.bottom=700;return True
        user=SimpleNamespace(IsWindow=lambda h:True,IsWindowVisible=lambda h:True,IsIconic=lambda h:False,GetWindowRect=get_rect,
            GetAncestor=lambda h,kind:h,GetWindow=lambda h,kind:0,SetWindowPos=Mock())
        with patch('profile_editor.winprobe.user',user):
            editor.update_bounds();editor.update_bounds()
        editor.palette.lift.assert_not_called();user.SetWindowPos.assert_not_called()
        self.assertEqual(editor.draw.call_count,1)

class VersionTests(unittest.TestCase):
    def test_reads_running_release_instead_of_shared_preferences(self):
        with tempfile.TemporaryDirectory(dir=HOME/'build/temp') as folder:
            root=Path(folder)/'0.2.3';root.mkdir();(root/'release.json').write_text(json.dumps(dict(version='0.2.3')),encoding='utf-8')
            with patch('version_info.sys.executable',str(root/'GameControlCenter.exe')),patch('version_info.sys.frozen',True,create=True):
                self.assertEqual(running_version(),'0.2.3')
                (root/'release.json').write_text(json.dumps(dict(version='9.9.9')),encoding='utf-8')
                self.assertEqual(running_version(),'版本未知')
    def test_source_reports_development_version(self):
        with patch('version_info.sys.frozen',False,create=True):self.assertEqual(running_version(),'开发版')

if __name__=='__main__':unittest.main()

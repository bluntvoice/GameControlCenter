"""Projection layout regressions without connecting a phone or moving user windows."""
import unittest
from unittest.mock import Mock,patch

from backend import Center
from video_layout import VideoLayoutMemory,restore_rect,valid_layout
import winprobe


def geometry(**values):
    result=dict(rect=[200,100,1000,500],client=[960,460],work=[0,0,2560,1400],dpi=96,normal=True)
    result.update(values)
    return result


class LayoutTests(unittest.TestCase):
    def test_reconnect_restores_user_size_and_position_once(self):
        saved=geometry();memory=VideoLayoutMemory(saved)
        large=geometry(rect=[0,0,2200,1100],client=[2160,1060])
        self.assertEqual(memory.observe(11,large,0),('restore',saved['rect']))
        self.assertIsNone(memory.observe(11,large,1))
        memory.observe(None,None,2)
        self.assertEqual(memory.observe(12,large,3),('restore',saved['rect']))

    def test_user_resize_is_debounced_and_survives_reopen(self):
        memory=VideoLayoutMemory(geometry());memory.observe(11,geometry(),0)
        changed=geometry(rect=[430,260,900,450],client=[860,410])
        self.assertIsNone(memory.observe(11,changed,3))
        self.assertIsNone(memory.observe(11,changed,3.8))
        action=memory.observe(11,changed,4.1)
        self.assertEqual(action[0],'save');self.assertEqual(action[1]['rect'],changed['rect'])
        self.assertEqual(VideoLayoutMemory(action[1]).observe(12,geometry(),10)[1],changed['rect'])

    def test_fullscreen_maximized_and_minimized_do_not_overwrite_normal(self):
        saved=geometry();memory=VideoLayoutMemory(saved);memory.observe(11,saved,0)
        special=geometry(rect=[0,0,2560,1440],client=[2560,1440],normal=False)
        for now in (3,4,10):self.assertIsNone(memory.observe(11,special,now))
        self.assertEqual(memory.saved,saved)

    def test_first_run_uses_smaller_proportional_window(self):
        current=geometry(rect=[0,0,2200,1100],client=[2160,1060])
        x,y,w,h=restore_rect(None,current)
        self.assertLessEqual(w,1100);self.assertLess(h,1000)
        self.assertAlmostEqual((w-40)/(h-40),2160/1060,places=2)
        self.assertGreaterEqual(x,0);self.assertGreaterEqual(y,0)

    def test_dpi_change_scales_size_without_stretching(self):
        target=restore_rect(geometry(),geometry(dpi=144))
        self.assertEqual(target,[200,100,1500,750])

    def test_missing_monitor_and_smaller_work_area_keep_whole_window_accessible(self):
        saved=geometry(rect=[-1800,100,1600,800],work=[-1920,0,1920,1080],client=[1560,760])
        target=restore_rect(saved,geometry(work=[0,0,1280,680]))
        x,y,w,h=target
        self.assertGreaterEqual(x,0);self.assertGreaterEqual(y,0)
        self.assertLessEqual(x+w,1280);self.assertLessEqual(y+h,680)
        self.assertAlmostEqual(w/h,2,places=2)

    def test_negative_coordinates_on_connected_monitor_are_preserved(self):
        saved=geometry(rect=[-1800,100,1000,500],work=[-1920,0,1920,1040])
        self.assertEqual(restore_rect(saved,geometry(work=saved['work'])),saved['rect'])

    def test_rotation_fits_remembered_box_using_current_content_aspect(self):
        current=geometry(rect=[0,0,500,1000],client=[460,960])
        x,y,w,h=restore_rect(geometry(),current)
        self.assertLessEqual(w,1000);self.assertLessEqual(h,500)
        self.assertAlmostEqual((w-40)/(h-40),460/960,places=2)

    def test_invalid_saved_data_falls_back_to_safe_default(self):
        for value in (None,{},geometry(dpi=0),geometry(rect=[0,0,True,500]),geometry(client=[0,460])):
            self.assertFalse(valid_layout(value))
            target=VideoLayoutMemory(value).observe(11,geometry(),0)[1]
            self.assertGreater(target[2],0);self.assertLess(target[2],2560)

    def test_only_configured_phone_and_verified_process_are_managed(self):
        center=Center.__new__(Center);center.editing_profile=False
        center.config=dict(serial='usb-phone');center.video_layout=VideoLayoutMemory(geometry())
        center.event=Mock();center.save_preference=Mock()
        windows=[dict(pid=8,hwnd=88,title='Phone - usb-phone'),dict(pid=7,hwnd=77,title='Phone - another-phone')]
        with patch.object(winprobe,'video_geometry') as probe,patch.object(winprobe,'restore_video_geometry') as restore:
            center.remember_video_window(windows,7)
            probe.assert_not_called();restore.assert_not_called()
            windows.append(dict(pid=7,hwnd=99,title='Phone - usb-phone'))
            probe.return_value=geometry();restore.return_value=True
            center.remember_video_window(windows,7)
            restore.assert_called_once_with(99,[200,100,1000,500])

    def test_placement_editor_does_not_move_or_record_video(self):
        center=Center.__new__(Center);center.editing_profile=True
        with patch.object(winprobe,'video_geometry') as probe:
            center.remember_video_window([],None);probe.assert_not_called()

    def test_restore_never_activates_or_changes_z_order(self):
        with patch.object(winprobe.user,'SetWindowPos',return_value=1) as move:
            self.assertTrue(winprobe.restore_video_geometry(99,[200,100,1000,500]))
            move.assert_called_once_with(99,None,200,100,1000,500,0x14)


if __name__=='__main__':unittest.main()

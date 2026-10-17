"""Tk handler integration in an isolated temporary library; no phone or OS input."""
import json
from pathlib import Path
import shutil
import tempfile
import threading
import queue
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from backend import Center
from profile_store import ProfileStore
from profile_editor import ProfileEditor,keep_editor_above
from mini_status import MiniSelect,BG,FG

HOME=Path(__file__).resolve().parents[1]
class EditorUiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=HOME/'build/temp');self.folder=Path(self.temp.name)
        keymap=self.folder/'keymap';keymap.mkdir()
        shutil.copy2((Path(__file__).resolve().parents[2]/'examples/超燃竞技场-三技能.json'),keymap/'超燃竞技场-三技能.json')
        store=ProfileStore(self.folder,keymap);store.ensure()
        self.root=tk.Tk();self.root.withdraw()
        backend=SimpleNamespace(profiles=store,runtime=self.folder,busy=False,editing_profile=False,event=Mock())
        self.app=SimpleNamespace(root=self.root,backend=backend,action=Mock(),minimize_main=Mock(),show_main=Mock())
        self.editor=ProfileEditor(self.app,self.root)
    def tearDown(self):
        self.root.destroy();self.temp.cleanup()
    def test_range_caption_distinguishes_stick_travel_from_mouse_coverage(self):
        editor=self.editor
        editor.new();editor.draft['controls']=[dict(name='左摇杆',x=.2,y=.7,mode='hold',radius=75,hz=1,hit_radius=1)]
        editor.select('左摇杆')
        self.assertEqual(editor.range_caption.get(),'左杆行程(px)')
        self.assertEqual(editor.hit_radius.get(),'1')
    def test_overlay_place_move_properties_save_and_reopen(self):
        editor=self.editor;editor.new();editor.name.set('拖动保存测试')
        def bounds():
            editor.bounds=(500,300,1000,500);editor.overlay.geometry('1000x500+500+300');editor.draw()
        editor.update_bounds=bounds;editor.open_overlay();editor.overlay.withdraw();editor.palette.withdraw()
        self.app.minimize_main.assert_called_once()
        self.assertEqual([str(b.cget('text')) for b in editor.mode_buttons],['按住','单次点击','连续点击','按住瞄准'])
        self.assertFalse(any(isinstance(w,tk.ttk.Combobox) for row in editor.palette.winfo_children() for w in row.winfo_children()))
        for name,x,y in [('A',1000,550),('左摇杆',700,650),('鼠标右键',1400,700)]:
            editor.dragging=name;editor.drag_end(SimpleNamespace(widget=editor.canvas,x_root=x,y_root=y))
        self.assertEqual(len(editor.draft['controls']),3)
        self.assertEqual(editor.draft['controls'][0]['x'],.5)
        editor.dragging='A';editor.drag_end(SimpleNamespace(widget=editor.canvas,x_root=1100,y_root=550))
        self.assertEqual(len(editor.draft['controls']),3);self.assertEqual(editor.draft['controls'][0]['x'],.6)
        editor.select('A');editor.mode_buttons[3].invoke();editor.radius.set('120');editor.hit_radius.set('85');editor.apply_properties()
        self.assertEqual(editor.draft['controls'][0]['mode'],'aim')
        editor.save();self.assertTrue(editor.draft['id']);self.assertTrue(Path(editor.draft['path']).exists())
        saved=editor.store.load(editor.draft['id']);self.assertEqual(len(saved['controls']),3)
        self.assertEqual(saved['controls'][0]['hit_radius'],85)
        editor.finish(resume=False);self.assertIsNone(editor.overlay);self.assertFalse(self.app.backend.editing_profile)
        editor.load(saved['id']);self.assertEqual(editor.draft['controls'][0]['radius'],120)
        self.assertTrue((self.folder/'editor-draft.json').exists())
    def test_remove_and_restore_draft(self):
        editor=self.editor;editor.new();editor.draft['controls']=[dict(name='A',x=.5,y=.5,mode='hold',radius=75,hz=10)]
        editor.snapshot();editor.selected='A';editor.remove();self.assertEqual(editor.draft['controls'],[])
        editor.draft['controls']=[dict(name='B',x=.3,y=.7,mode='once',radius=75,hz=10)]
        editor.snapshot();editor.new();editor.restore_draft();self.assertEqual(editor.draft['controls'][0]['name'],'B')
    def test_mouse_defaults_to_once_and_all_modes_survive_save_and_reload(self):
        editor=self.editor;editor.new();editor.name.set('鼠标类型测试');editor.bounds=(100,100,1000,500)
        for index,name in enumerate(('鼠标左键','鼠标右键')):
            editor.dragging=name;editor.drag_end(SimpleNamespace(widget=editor.frame,x_root=500+index*100,y_root=350))
            self.assertEqual(editor.mode.get(),'单次点击')
        editor.update_bounds=lambda:None;editor.open_overlay();editor.overlay.withdraw();editor.palette.withdraw()
        for name in ('鼠标左键','鼠标右键'):
            editor.select(name)
            for index,mode in enumerate(('hold','once','repeat','aim')):
                editor.mode_buttons[index].invoke()
                self.assertEqual(next(c for c in editor.draft['controls'] if c['name']==name)['mode'],mode)
                self.assertEqual(editor.hz.get(),'10' if mode=='repeat' else '1')
            editor.mode.set('单次点击');editor.change_mode()
        editor.save();ident=editor.draft['id'];self.assertTrue(ident)
        editor.load(ident);self.assertTrue(all(c['mode']=='once' for c in editor.draft['controls']))
        editor.finish(resume=False)
    def test_frequency_defaults_and_enabled_state_follow_mode_in_both_panels(self):
        editor=self.editor;editor.new();editor.name.set('频率类型测试')
        editor.draft['controls']=[dict(name='A',x=.5,y=.5,mode='hold',radius=75,hz=10,hit_radius=0)]
        editor.update_bounds=lambda:None;editor.open_overlay();editor.select('A')
        self.assertEqual(editor.hz.get(),'1');self.assertEqual(editor.frequency_caption.get(),'触发次数')
        for widget in (editor.frequency_input,editor.palette_frequency_input):self.assertEqual(str(widget.cget('state')),'disabled')
        editor.mode_buttons[2].invoke()
        self.assertEqual(editor.hz.get(),'10');self.assertEqual(editor.draft['controls'][0]['hz'],10)
        self.assertEqual(editor.frequency_caption.get(),'连点次数/秒')
        for widget in (editor.frequency_input,editor.palette_frequency_input):self.assertEqual(str(widget.cget('state')),'normal')
        editor.hz.set('7');editor.apply_properties();editor.select('A')
        self.assertEqual(float(editor.hz.get()),7)
        for index in (0,1,3):
            editor.mode_buttons[index].invoke()
            self.assertEqual(editor.hz.get(),'1');self.assertEqual(editor.draft['controls'][0]['hz'],1)
            self.assertEqual(str(editor.palette_frequency_input.cget('state')),'disabled')
        editor.mode_buttons[2].invoke();self.assertEqual(editor.hz.get(),'10')
        editor.finish(resume=False)
    def test_coverage_previews_and_saves_without_separate_apply_click(self):
        editor=self.editor;editor.new();editor.name.set('覆盖即时预览')
        editor.draft['controls']=[dict(name='A',x=.5,y=.5,mode='hold',radius=75,hz=10,hit_radius=0)]
        def bounds():
            editor.bounds=(100,100,1000,500);editor.draw()
        editor.update_bounds=bounds;editor.open_overlay();editor.select('A')
        editor.hit_radius.set('84')
        self.assertEqual(editor.draft['controls'][0]['hit_radius'],84)
        circles=[i for i in editor.canvas.find_all() if editor.canvas.type(i)=='oval' and editor.canvas.itemcget(i,'outline')=='#EACB88']
        self.assertEqual(len(circles),1)
        box=editor.canvas.coords(circles[0]);self.assertAlmostEqual(box[2]-box[0],70)
        editor.save();self.assertEqual(editor.store.load(editor.draft['id'])['controls'][0]['hit_radius'],84)
        editor.finish(resume=False)
    def test_invalid_pending_coverage_blocks_save_without_losing_valid_draft(self):
        editor=self.editor;editor.new();editor.name.set('覆盖校验')
        editor.draft['controls']=[dict(name='A',x=.5,y=.5,mode='hold',radius=75,hz=10,hit_radius=30)]
        editor.select('A');editor.hit_radius.set('90');editor.hit_radius.set('999');editor.save()
        self.assertIsNone(editor.draft['id']);self.assertEqual(editor.draft['controls'][0]['hit_radius'],90)
        self.assertIn('0～400',editor.note.get())
    def test_startup_error_is_recorded_and_retry_still_works(self):
        editor=self.editor;editor.preparing=True;editor.backend.editing_profile=True
        editor.polling.put(('error',('手机当前为竖屏','portrait traceback')));editor.poll()
        self.assertFalse(editor.preparing);self.assertFalse(editor.backend.editing_profile)
        self.assertIn('手机当前为竖屏',editor.note.get())
        editor.backend.event.assert_called_with('投屏摆放启动失败：手机当前为竖屏','bad',detail='portrait traceback')
        def open_overlay():
            editor.overlay=tk.Toplevel(self.root);editor.palette=tk.Toplevel(self.root)
            editor.bounds=(100,100,800,400)
        editor.open_overlay=open_overlay;editor.backend.editing_profile=True
        editor.polling.put(('ready',dict(width=2608,height=1200)));editor.poll()
        self.assertIsNotNone(editor.overlay);self.assertTrue(editor.backend.editing_profile)
        editor.finish(resume=False)
    def test_partial_window_failure_cleans_up_without_resuming_input(self):
        editor=self.editor
        def broken_overlay():
            editor.overlay=tk.Toplevel(self.root)
            raise tk.TclError('test native window failure')
        editor.open_overlay=broken_overlay;editor.preparing=True;editor.backend.editing_profile=True
        editor.polling.put(('ready',dict(width=2608,height=1200)));editor.poll()
        self.assertIsNone(editor.overlay);self.assertIsNone(editor.palette)
        self.assertFalse(editor.backend.editing_profile);self.assertFalse(editor.preparing)
        self.assertIn('test native window failure',editor.note.get())
        self.assertIn('TclError',editor.backend.event.call_args.kwargs['detail'])
        self.app.action.assert_not_called();self.app.show_main.assert_called_once()
    def test_lost_video_keeps_actual_error_after_cleanup(self):
        editor=self.editor;editor.overlay=tk.Toplevel(self.root);editor.palette=tk.Toplevel(self.root)
        editor.surface=dict(surface=0,video=0,width=2608,height=1200)
        editor.backend.editing_profile=True;editor.resume_after=True
        editor.update_bounds()
        self.assertIsNone(editor.overlay);self.assertFalse(editor.backend.editing_profile)
        self.assertIn('投屏窗口已关闭或最小化',editor.note.get())
        self.app.action.assert_not_called()
    def test_portrait_display_has_actionable_error(self):
        from pad_transport import display_info
        text='mOverrideDisplayInfo=DisplayInfo{displayId 0, real 1200 x 2608, rotation 0}'
        with patch('pad_transport.adb',return_value=text):
            with self.assertRaisesRegex(RuntimeError,'进入游戏横屏'):display_info()
    def test_dark_picker_menu_selection_and_disabled_state(self):
        value=tk.StringVar(value='超燃竞技场-三技能');callback=Mock()
        picker=MiniSelect(self.root,value,callback)
        picker.configure(values=['超燃竞技场-三技能','新方案'],state='readonly')
        self.assertEqual(picker.cget('bg'),BG);self.assertEqual(picker.cget('fg'),FG)
        self.assertEqual(str(picker.popup.cget('bg')),BG);self.assertEqual(str(picker.popup.cget('fg')),FG)
        picker.popup.invoke(1);self.assertEqual(value.get(),'新方案');callback.assert_called_once()
        picker.configure(state='disabled');self.assertEqual(str(picker.cget('state')),'disabled')
    def test_console_layout_and_narrow_strip_controls_fit(self):
        import main
        backend=self.app.backend
        backend.config=dict(serial='192.0.2.10:5555',mini_visible=False,mini_size=[432,84])
        backend.home=self.folder;backend.session=self.folder;backend.start=Mock()
        backend.lock=threading.RLock();backend.local={};backend.phone={};backend.series=[];backend.updates=queue.Queue()
        with patch.object(main,'Center',return_value=backend),patch.object(main,'TrayIcon',return_value=Mock()),patch.object(main,'running_version',return_value='0.2.3'):
            app=main.App();app.root.update()
            self.assertEqual(app.version_label.cget('text'),'v0.2.3')
            backend.request_pad=Mock()
            app.mini.update(dict(controllers=[],adapter=dict(state='已暂停',tone='ok'),gamescrcpy=dict(tone='ok'),video_window=True),dict(connected=True))
            self.assertEqual(app.mini.adapter_button.cget('text'),'已暂停')
            self.assertEqual(app.mini.body.cget('fg'),FG)
            with patch.object(app,'action',side_effect=lambda name,action:action()):
                app.mini.adapter_button.invoke();backend.request_pad.assert_called_once_with('start')
                backend.editing_profile=True
                app.mini.update({},{});app.mini.adapter_button.invoke()
                self.assertEqual(backend.request_pad.call_count,1)
                backend.editing_profile=False
            app.update_pad_status([dict(index=0)])
            self.assertIn('已连接',app.pad_text.cget('text'))
            app.update_pad_status([]);self.assertEqual(app.pad_text.cget('text'),'未检测到手柄')
            app.minimize_main();app.root.update()
            self.assertEqual(app.root.state(),'iconic')
            self.assertFalse(app.root.bind('<Unmap>'))
            app.show_main();app.root.update()
            app.root.tk.call(app.root.protocol('WM_DELETE_WINDOW'));app.root.update()
            self.assertEqual(app.root.state(),'withdrawn')
            app.show_main();app.root.update()
            self.assertGreaterEqual(app.chart.winfo_height(),app.chart.winfo_reqheight(),str([(str(w),w.winfo_width(),w.winfo_height()) for w in (app.root,app.notebook,app.chart.master,app.chart)]))
            self.assertLessEqual(app.chart.winfo_rooty()+app.chart.winfo_height(),app.root.winfo_rooty()+app.root.winfo_height())
            app.notebook.select(app.editor_tab);app.root.update_idletasks()
            name_row=app.editor.name_entry.master
            for child in name_row.winfo_children():
                self.assertLessEqual(child.winfo_x()+child.winfo_width(),name_row.winfo_width()+2)
            header=app.mini.scheme_combo.master
            app.mini.window.deiconify();app.mini.window.update_idletasks()
            self.assertLessEqual(app.mini.scheme_combo.winfo_x()+app.mini.scheme_combo.winfo_width(),header.winfo_width())
            self.assertLessEqual(app.mini.adapter_button.winfo_rootx()+app.mini.adapter_button.winfo_width(),app.mini.window.winfo_rootx()+app.mini.window.winfo_width())
            app.mini.window.withdraw();app.root.destroy()

class EditorStackTests(unittest.TestCase):
    def test_covered_palette_is_restacked_without_moving_or_activating(self):
        user=Mock();order=[10,20,30];calls=[]
        user.IsWindowVisible.return_value=True
        user.GetWindow.side_effect=lambda hwnd,kind:order[order.index(hwnd)-1] if order.index(hwnd)>0 else 0
        def place(handle,after,x,y,w,h,flags):
            calls.append((handle,after,flags));order.remove(handle);order.insert(0,handle);return True
        user.SetWindowPos.side_effect=place
        with patch('profile_editor.winprobe.user',user):
            self.assertTrue(keep_editor_above(10,20,30))
            self.assertEqual(order,[30,20,10])
            self.assertFalse(keep_editor_above(10,20,30))
        self.assertEqual(calls,[(20,-1,0x13),(30,-1,0x13)])
    def test_native_palette_survives_main_minimize_and_recovers_stacking(self):
        root=tk.Tk();root.withdraw()
        video=tk.Toplevel(root);overlay=tk.Toplevel(root);palette=tk.Toplevel(root)
        try:
            for window in (video,overlay,palette):window.attributes('-topmost',True)
            root.update()
            user=__import__('winprobe').user
            handles=[user.GetAncestor(window.winfo_id(),2) for window in (video,overlay,palette)]
            root.deiconify();root.update();root.iconify();root.update()
            self.assertTrue(user.IsWindowVisible(handles[1]))
            self.assertTrue(user.IsWindowVisible(handles[2]))
            foreground=user.GetForegroundWindow()
            user.SetWindowPos(handles[0],-1,0,0,0,0,0x13)
            self.assertTrue(keep_editor_above(*handles))
            self.assertFalse(keep_editor_above(*handles))
            self.assertEqual(user.GetForegroundWindow(),foreground)
        finally:root.destroy()

if __name__=='__main__':unittest.main()

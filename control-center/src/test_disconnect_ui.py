"""Exercise the real Tk stop button in a temporary console with no device polling."""
import json
from pathlib import Path
import tempfile
import shutil
import threading
import time
import tkinter.font as tkfont
import unittest
from unittest.mock import Mock,patch

import backend
import main


class DisconnectUiTests(unittest.TestCase):
    def test_stop_button_keeps_ui_alive_and_fits_at_minimum_width(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);home=root/'control-center';home.mkdir()
            shutil.copytree(Path(__file__).resolve().parents[2]/'examples',root/'examples')
            config=dict(project=str(root),gamescrcpy=str(root/'GameScrcpy.exe'),serial='test-phone',
                powershell='pwsh.exe',adb='adb.exe',antimicrox='',pythonw='pythonw.exe',
                sample_seconds=2,fps_low_threshold=48,labels_enabled=False,mini_visible=False)
            with patch.object(backend,'load_config',return_value=config),patch.object(backend.winprobe,'Controller'):
                center=backend.Center(home)
            center.controller=Mock()
            center.start=Mock();center.pid_file=Mock(return_value=None)
            with patch.object(main,'Center',return_value=center),patch.object(main,'TrayIcon'),patch.object(main,'MiniStatus'):
                app=main.App()
            app.root.title('停止连接回归检查（隔离）')
            try:
                app.root.geometry('960x760');app.root.deiconify();app.root.update_idletasks()
                app.disconnect_button.invoke()
                deadline=time.monotonic()+3
                while center.busy and time.monotonic()<deadline:
                    app.root.update();time.sleep(.01)
                self.assertFalse(center.busy)
                self.assertTrue(center.config['input_disconnected'])
                self.assertTrue(app.root.winfo_exists())
                self.assertEqual(center.read_controllers(),[])
                center.controller.read.assert_not_called()
                self.assertTrue(json.loads((home/'config.json').read_text(encoding='utf-8'))['input_disconnected'])
                app.tick();app.root.update_idletasks()
                self.assertEqual(app.connect_button.cget('text'),'恢复连接')
                for button in (app.disconnect_button,app.connect_button):
                    font=tkfont.Font(root=app.root,font=button.cget('font'))
                    self.assertGreaterEqual(button.winfo_width(),font.measure(button.cget('text'))+12)
                    self.assertGreaterEqual(button.winfo_height(),font.metrics('linespace')+8)
                    self.assertLessEqual(button.winfo_x()+button.winfo_width(),button.master.winfo_width())
            finally:
                for timer in app.root.tk.call('after','info'):app.root.after_cancel(timer)
                app.root.destroy();center.csv_file.close()


if __name__=='__main__':unittest.main()

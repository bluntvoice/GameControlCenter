"""Portable configuration and sample initialization, with no device connection."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import app_config
from profile_store import ProfileStore

ROOT=Path(__file__).resolve().parents[2]

class PortableTests(unittest.TestCase):
    def test_source_root_is_independent_of_working_directory(self):
        self.assertEqual(app_config.project_root(),ROOT)
    def test_frozen_roots_match_both_package_entry_points(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve()
            for exe in [root/'control-center/releases/0.3.0/GameControlCenter.exe',root/'tools/analog/GamePadAdapter.exe']:
                with patch.object(app_config.sys,'frozen',True,create=True),patch.object(app_config.sys,'executable',str(exe)):
                    self.assertEqual(app_config.project_root(),root)
    def test_moved_configuration_rebases_only_project_path(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp)/'control-center';home.mkdir()
            (home/'config.json').write_text(json.dumps(dict(project='OLD_LOCATION',serial='USB-EXAMPLE',gamescrcpy=str(Path(temp)/'GameScrcpy.exe'))),encoding='utf-8')
            config=app_config.load_config(home)
            self.assertEqual(Path(config['project']),home.parent.resolve())
            self.assertEqual(config['serial'],'USB-EXAMPLE')
            self.assertEqual(Path(config['adb']),home.parent/'adb.exe')
    def test_example_initialization_preserves_existing_keymap(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);keymap=root/'keymap';keymap.mkdir()
            data=(ROOT/'examples/超燃竞技场-三技能.json').read_bytes()
            target=keymap/'超燃竞技场-三技能.json';target.write_bytes(data)
            store=ProfileStore(root,keymap);store.ensure()
            self.assertEqual(target.read_bytes(),data)
            self.assertEqual(store.load()['status'],'待游戏校对')
    def test_new_install_seeds_normalized_controls_and_neutral_center(self):
        import shutil
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);shutil.copytree(ROOT/'examples',root/'examples')
            store=ProfileStore(root,root/'keymap');store.ensure()
            profile,_=store.active_runtime()
            self.assertGreater(len(profile['_adapter']['controls']),0)
            self.assertEqual(store.load()['status'],'待游戏校对')
            settings=json.loads((ROOT/'defaults/adapter-settings.json').read_text(encoding='utf-8'))
            self.assertEqual(settings['right_center'],[0,0])
    def test_adapter_uses_packaged_binary_when_present(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config=dict(project=temp,pythonw='pythonw.exe')
            self.assertEqual(app_config.adapter_executable(config),'pythonw.exe')
            exe=root/'tools/analog/GamePadAdapter.exe';exe.parent.mkdir(parents=True);exe.touch()
            self.assertEqual(app_config.adapter_executable(config),str(exe))

if __name__=='__main__':unittest.main()

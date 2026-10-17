"""Offline executable smoke check. Never starts ADB, another app or input hooks."""
import json
from pathlib import Path
import sys
import zipfile
from app_config import project_root

def run():
    root=project_root()
    required=['examples/超燃竞技场-三技能.json','defaults/adapter-settings.json',
        'tools/analog/video_surface.ps1','tools/phase2b_controller_labels.ps1',
        'phase2b-20261015/analog/build/pad-touch.jar','control-center/src/fps_watch.ps1']
    for item in required:
        if not (root/item).is_file():raise RuntimeError('Missing packaged file: '+item)
    with zipfile.ZipFile(root/'phase2b-20261015/analog/build/pad-touch.jar') as jar:
        if not jar.read('classes.dex').startswith(b'dex\n'):raise RuntimeError('Invalid Android companion')
    report=dict(ok=True,version='0.3.0',project=str(root),executable=Path(sys.executable).name,device_actions=False)
    folder=root/'control-center/runtime';folder.mkdir(parents=True,exist_ok=True)
    (folder/(Path(sys.executable).stem+'-package-check.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

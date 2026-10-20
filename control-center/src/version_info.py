"""Report the running release, independently of shared user preferences."""
import json
from pathlib import Path
import re
import sys

def running_version():
    if not getattr(sys,'frozen',False):return '开发版'
    folder=Path(sys.executable).resolve().parent
    try:
        release=json.loads((folder/'release.json').read_text(encoding='utf-8-sig'))
        if release.get('development') is True and folder.name.startswith('dev-'):return '开发版'
        version=release['version']
        if re.fullmatch(r'\d+\.\d+\.\d+',version) and folder.name==version:return version
    except (OSError,ValueError,KeyError,TypeError):pass
    return '版本未知'

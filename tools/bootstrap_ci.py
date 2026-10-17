"""Install a pinned, standalone PowerShell for the Windows build runner."""
from pathlib import Path
import urllib.request
import zipfile

folder=Path('.cache/pwsh');folder.mkdir(parents=True,exist_ok=True)
archive=folder/'powershell.zip'
urllib.request.urlretrieve('https://github.com/PowerShell/PowerShell/releases/download/v7.6.4/PowerShell-7.6.4-win-x64.zip',archive)
with zipfile.ZipFile(archive) as source:source.extractall(folder)

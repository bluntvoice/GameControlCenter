[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$OutputEncoding=[Console]::OutputEncoding
if($PSVersionTable.PSVersion -lt [version]'7.6.4'){throw 'PowerShell >=7.6.4 required'}
$ErrorActionPreference='Stop'
$exe=Join-Path $PSScriptRoot 'control-center/releases/0.3.0/GameControlCenter.exe'
if(-not(Test-Path -LiteralPath $exe)){throw 'Executable not found. Extract the complete release first.'}
$link=Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) '手机游戏控制台 0.3.0.lnk'
if(Test-Path -LiteralPath $link){throw '同名快捷方式已存在，未覆盖。'}
$shortcut=(New-Object -ComObject WScript.Shell).CreateShortcut($link)
$shortcut.TargetPath=$exe;$shortcut.WorkingDirectory=$PSScriptRoot;$shortcut.IconLocation=$exe+',0'
$shortcut.Description='手机游戏控制台 0.3.0';$shortcut.Save()
Write-Output $link

param([string]$Python='python',[string]$Java='java',[switch]$SkipTests)
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$OutputEncoding=[Console]::OutputEncoding
if($PSVersionTable.PSVersion -lt [version]'7.6.4'){throw 'PowerShell >=7.6.4 required'}
$ErrorActionPreference='Stop'
$root=$PSScriptRoot
$version=([IO.File]::ReadAllText((Join-Path $root 'control-center/VERSION'),[Text.Encoding]::UTF8)).Trim()
if($version -notmatch '^\d+\.\d+\.\d+$'){throw 'Invalid version'}
$output=Join-Path $root "dist/GameControlCenter-$version-windows-x64"
if(Test-Path -LiteralPath $output){throw 'Output exists. Preserve it before building again.'}
$work=Join-Path $root 'build'
New-Item -ItemType Directory -Path (Join-Path $work 'temp'),(Join-Path $root 'control-center/build/temp') -Force | Out-Null
$oldTemp=$env:TEMP;$oldTmp=$env:TMP;$oldPath=$env:PYTHONPATH;$oldCache=$env:PYINSTALLER_CONFIG_DIR
try{
 $env:PYTHONIOENCODING='utf-8';$env:PYTHONDONTWRITEBYTECODE='1'
 $env:PYTHONPATH=(Join-Path $root 'tools/analog')+';'+(Join-Path $root 'control-center/src')
 $env:TEMP=Join-Path $work 'temp';$env:TMP=$env:TEMP;$env:PYINSTALLER_CONFIG_DIR=Join-Path $work 'pyinstaller-cache'
 New-Item -ItemType Directory -Path (Join-Path $root 'phase2b-20261015/analog') -Force | Out-Null
 $settings=Join-Path $root 'phase2b-20261015/analog/settings.json'
 if(-not(Test-Path -LiteralPath $settings)){Copy-Item -LiteralPath (Join-Path $root 'defaults/adapter-settings.json') -Destination $settings}
 if(-not $SkipTests){
  & $Python -B -m unittest discover -s (Join-Path $root 'control-center/src') -p 'test_*.py'
  if($LASTEXITCODE -ne 0){throw 'Tests failed'}
 }
 & (Join-Path $root 'tools/analog/build.ps1') -Java $Java
 & $Python -B (Join-Path $root 'control-center/src/make_assets.py')
 if($LASTEXITCODE -ne 0){throw 'Icon rendering failed'}
 $numeric=($version -replace '\.',',')+',0'
 $versionSource="VSVersionInfo(ffi=FixedFileInfo(filevers=($numeric),prodvers=($numeric),mask=0x3f,flags=0,OS=0x40004,fileType=1,subtype=0,date=(0,0)),kids=[StringFileInfo([StringTable('040904B0',[StringStruct('ProductName','GameControlCenter'),StringStruct('FileVersion','$version'),StringStruct('ProductVersion','$version')])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])"
 [IO.File]::WriteAllText((Join-Path $work 'version.txt'),$versionSource,[Text.UTF8Encoding]::new($false))
 foreach($app in @(@{Name='GameControlCenter';Source='control-center/src/main.py'},@{Name='GamePadAdapter';Source='tools/analog/pad_adapter.py'})){
  & $Python -B -m PyInstaller --noconfirm --windowed --onedir --name $app.Name --icon (Join-Path $root 'control-center/assets/center.ico') --version-file (Join-Path $work 'version.txt') --distpath (Join-Path $work 'dist') --workpath (Join-Path $work 'work') --specpath (Join-Path $work 'spec') --paths (Join-Path $root 'control-center/src') --paths (Join-Path $root 'tools/analog') (Join-Path $root $app.Source)
  if($LASTEXITCODE -ne 0){throw "Build failed: $($app.Name)"}
 }
 New-Item -ItemType Directory -Path $output -Force | Out-Null
 foreach($item in @('README.md','CHANGELOG.md','LICENSE','THIRD_PARTY_NOTICES.md','Start.ps1','CreateShortcut.ps1','defaults','examples')){
  Copy-Item -LiteralPath (Join-Path $root $item) -Destination $output -Recurse
 }
 foreach($folder in @('control-center/src','control-center/assets','tools')){
  $target=Join-Path $output $folder;New-Item -ItemType Directory -Path $target -Force | Out-Null
  Get-ChildItem -LiteralPath (Join-Path $root $folder) -File | Where-Object {$_.Extension -in '.ps1','.cs','.java'} | Copy-Item -Destination $target
 }
 Copy-Item -LiteralPath (Join-Path $root 'control-center/assets/lucide') -Destination (Join-Path $output 'control-center/assets/lucide') -Recurse
 Copy-Item -LiteralPath (Join-Path $root 'control-center/assets/center.ico') -Destination (Join-Path $output 'control-center/assets/center.ico')
 Copy-Item -LiteralPath (Join-Path $root 'control-center/assets/center.png') -Destination (Join-Path $output 'control-center/assets/center.png')
 Copy-Item -LiteralPath (Join-Path $root 'control-center/config.example.json') -Destination (Join-Path $output 'control-center/config.example.json')
 $analog=Join-Path $output 'tools/analog';New-Item -ItemType Directory -Path $analog -Force | Out-Null
 Get-ChildItem -LiteralPath (Join-Path $root 'tools/analog') -Filter '*.ps1' -File | Copy-Item -Destination $analog
 Get-ChildItem -LiteralPath (Join-Path $work 'dist/GamePadAdapter') -Force | Copy-Item -Destination $analog -Recurse
 $release=Join-Path $output "control-center/releases/$version";New-Item -ItemType Directory -Path $release -Force | Out-Null
 Get-ChildItem -LiteralPath (Join-Path $work 'dist/GameControlCenter') -Force | Copy-Item -Destination $release -Recurse
 $phase=Join-Path $output 'phase2b-20261015'
 New-Item -ItemType Directory -Path (Join-Path $phase 'analog/build'),(Join-Path $phase 'profiles/blank-no-keys'),(Join-Path $phase 'evidence') -Force | Out-Null
 Copy-Item -LiteralPath (Join-Path $root 'phase2b-20261015/analog/build/pad-touch.jar') -Destination (Join-Path $phase 'analog/build/pad-touch.jar')
 Copy-Item -LiteralPath (Join-Path $root 'phase2b-20261015/profiles/blank-no-keys/blank.amgp') -Destination (Join-Path $phase 'profiles/blank-no-keys/blank.amgp')
 Copy-Item -LiteralPath (Join-Path $root 'phase2b-20261015/controller-labels.json') -Destination $phase
 $manifest=@{version=$version;executable='GameControlCenter.exe';sha256=(Get-FileHash -LiteralPath (Join-Path $release 'GameControlCenter.exe')).Hash}
 [IO.File]::WriteAllText((Join-Path $release 'release.json'),($manifest|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
 $pythonHome=Split-Path (Get-Command $Python -ErrorAction Stop).Source -Parent
 $pythonLicense=Join-Path $pythonHome 'LICENSE.txt'
 if(-not(Test-Path -LiteralPath $pythonLicense)){throw 'Python LICENSE.txt not found; preserve runtime license before distributing'}
 Copy-Item -LiteralPath $pythonLicense -Destination (Join-Path $output 'PYTHON-LICENSE.txt')
 Copy-Item -LiteralPath (Join-Path $root 'tools/licenses/TCL-LICENSE.txt') -Destination (Join-Path $output 'TCL-LICENSE.txt')
 $pyinstallerLicense=& $Python -B -c 'from importlib.metadata import distribution; d=distribution("pyinstaller"); print(next(str(d.locate_file(p)) for p in d.files if str(p).endswith("licenses/COPYING.txt")))'
 if($LASTEXITCODE -ne 0 -or -not(Test-Path -LiteralPath $pyinstallerLicense)){throw 'PyInstaller COPYING.txt not found'}
 Copy-Item -LiteralPath $pyinstallerLicense -Destination (Join-Path $output 'PYINSTALLER-COPYING.txt')
 foreach($exe in @((Join-Path $release 'GameControlCenter.exe'),(Join-Path $analog 'GamePadAdapter.exe'))){
  $process=Start-Process -FilePath $exe -ArgumentList '--verify-package' -WorkingDirectory $output -WindowStyle Hidden -PassThru
  if(-not $process.WaitForExit(30000)){throw 'Offline package check timed out'}
  if($process.ExitCode -ne 0){throw "Offline package check failed: $exe"}
  $report=Join-Path $output ('control-center/runtime/'+[IO.Path]::GetFileNameWithoutExtension($exe)+'-package-check.json')
  $check=Get-Content -LiteralPath $report -Raw -Encoding utf8 | ConvertFrom-Json
  if(-not $check.ok -or $check.version -ne $version){throw 'Package check report mismatch'}
 }
 # Remove only generated offline-check reports, so no machine path is shipped.
 foreach($name in @('GameControlCenter','GamePadAdapter')){
  Remove-Item -LiteralPath (Join-Path $output "control-center/runtime/$name-package-check.json")
 }
 $archive=Join-Path $root "dist/GameControlCenter-$version-windows-x64.zip"
 Compress-Archive -LiteralPath $output -DestinationPath $archive
 $hash=(Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
 [IO.File]::WriteAllText((Join-Path $root 'dist/SHA256SUMS.txt'),"$hash  $([IO.Path]::GetFileName($archive))`n",[Text.UTF8Encoding]::new($false))
 [pscustomobject]@{version=$version;archive=$archive;sha256=$hash}|ConvertTo-Json
}finally{$env:TEMP=$oldTemp;$env:TMP=$oldTmp;$env:PYTHONPATH=$oldPath;$env:PYINSTALLER_CONFIG_DIR=$oldCache}

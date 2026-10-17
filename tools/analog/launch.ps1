param([switch]$AutoStart,[switch]$ShowWindow,[switch]$StartPaused)
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$OutputEncoding=[Console]::OutputEncoding
if($PSVersionTable.PSVersion -lt [version]'7.6.4'){throw 'PowerShell >=7.6.4 required'}
$ErrorActionPreference='Stop'
$root=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$config=Get-Content -LiteralPath (Join-Path $root 'control-center/config.json') -Raw -Encoding utf8 | ConvertFrom-Json
$runtime=Join-Path $root 'phase2b-20261015/analog'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$exe=Join-Path $PSScriptRoot 'GamePadAdapter.exe'
$packaged=Test-Path -LiteralPath $exe
$program=if($packaged){$exe}else{$config.pythonw}
$pidFile=Join-Path $runtime 'adapter.pid'
if(Test-Path -LiteralPath $pidFile){
 $oldId=[int][IO.File]::ReadAllText($pidFile,[Text.Encoding]::UTF8)
 $old=Get-CimInstance Win32_Process -Filter "ProcessId=$oldId" -ErrorAction SilentlyContinue
 if($old -and $old.ExecutablePath -eq $program -and ($packaged -or $old.CommandLine -like '*tools*analog*pad_adapter.py*')){
  if($ShowWindow){
   $request=@{id=[guid]::NewGuid().ToString('N');command='show';at=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000}
   [IO.File]::WriteAllText((Join-Path $runtime 'control-request.json'),($request|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
  }
  Write-Output '已复用现有适配器。';return
 }
}
if(-not (Test-Path -LiteralPath $program)){throw 'Adapter runtime missing; build the portable package or configure pythonw'}
$arguments=@()
if(-not $packaged){$arguments=@('-B',('"'+(Join-Path $PSScriptRoot 'pad_adapter.py')+'"'))}
if($AutoStart){$arguments+='--start'}
if($StartPaused){$arguments+='--paused'}
if(-not $ShowWindow){$arguments+='--hidden'}
$options=@{FilePath=$program;WorkingDirectory=$root;WindowStyle='Hidden';PassThru=$true;
 RedirectStandardOutput=(Join-Path $runtime 'adapter.stdout.log');RedirectStandardError=(Join-Path $runtime 'adapter.stderr.log')}
if($arguments.Count){$options.ArgumentList=$arguments}
$proc=Start-Process @options
[IO.File]::WriteAllText($pidFile,[string]$proc.Id,[Text.UTF8Encoding]::new($false))
Write-Output "双摇杆适配器已打开，PID=$($proc.Id)"

[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$OutputEncoding=[Console]::OutputEncoding
if($PSVersionTable.PSVersion -lt [version]'7.6.4'){throw 'PowerShell >=7.6.4 required'}
$version='0.3.0'
$exe=Join-Path $PSScriptRoot "control-center/releases/$version/GameControlCenter.exe"
if(-not(Test-Path -LiteralPath $exe)){throw '请先下载并完整解压 Windows Release，或从源码构建。'}
Start-Process -FilePath $exe -WorkingDirectory $PSScriptRoot -WindowStyle Hidden

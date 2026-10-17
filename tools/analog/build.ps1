param([string]$Java='java',[string]$Cache)
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$OutputEncoding=[Console]::OutputEncoding
if($PSVersionTable.PSVersion -lt [version]'7.6.4'){throw 'PowerShell >=7.6.4 required'}
$ErrorActionPreference='Stop'
$root=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if(-not $Cache){$Cache=Join-Path $root '.cache/android-tools'}
$build=Join-Path $root 'phase2b-20261015/analog/build'
New-Item -ItemType Directory -Path $build,$Cache -Force | Out-Null
$dependencies=@(
 @{Name='ecj-4.6.1.jar';Url='https://repo.maven.apache.org/maven2/org/eclipse/jdt/core/compiler/ecj/4.6.1/ecj-4.6.1.jar';Sha='9CDDDA75F4A1B4469E73F44E7B61A3E897D0F657DF4797F9106FFE88C4EEADE0'},
 @{Name='r8-3.3.75.jar';Url='https://storage.googleapis.com/r8-releases/raw/3.3.75/r8.jar';Sha='2359201406AEB6ABABB6BAF40298730B998321049C5753DA6A0B050EFAA0B393'}
)
foreach($dependency in $dependencies){
 $path=Join-Path $Cache $dependency.Name
 if(-not(Test-Path -LiteralPath $path)){Invoke-WebRequest -Uri $dependency.Url -OutFile $path}
 if((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $dependency.Sha){throw "Dependency hash mismatch: $($dependency.Name)"}
}
& $Java -jar (Join-Path $Cache 'ecj-4.6.1.jar') -1.8 -encoding UTF-8 -d $build (Join-Path $PSScriptRoot 'PadTouchServer.java')
if($LASTEXITCODE -ne 0){throw 'Java compilation failed'}
& $Java -cp (Join-Path $Cache 'r8-3.3.75.jar') com.android.tools.r8.D8 --min-api 29 --output $build (Join-Path $build 'PadTouchServer.class')
if($LASTEXITCODE -ne 0){throw 'DEX compilation failed'}
Add-Type -AssemblyName System.IO.Compression
$jar=Join-Path $build 'pad-touch.jar'
$file=[IO.File]::Open($jar,[IO.FileMode]::Create)
try{
 $archive=[IO.Compression.ZipArchive]::new($file,[IO.Compression.ZipArchiveMode]::Create,$true)
 try{[void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive,(Join-Path $build 'classes.dex'),'classes.dex')}
 finally{$archive.Dispose()}
}finally{$file.Dispose()}
Get-FileHash -LiteralPath $jar -Algorithm SHA256

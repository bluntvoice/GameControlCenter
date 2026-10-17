param([Parameter(Mandatory)][string]$OutputPath,[Parameter(Mandatory)][int]$OwnerId,[Parameter(Mandatory)][string]$StopPath)
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$OutputEncoding=[Console]::OutputEncoding
if($PSVersionTable.PSVersion -lt [version]'7.6.4'){throw 'PowerShell >=7.6.4 required'}
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes
Add-Type @'
using System;using System.Runtime.InteropServices;public class FpsWindows {
 public delegate bool Visit(IntPtr h,IntPtr p);
 [DllImport("user32.dll")]public static extern bool EnumWindows(Visit fn,IntPtr p);
 [DllImport("user32.dll")]public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);
}
'@
$root=[Windows.Automation.AutomationElement]::RootElement
while((Get-Process -Id $OwnerId -ErrorAction SilentlyContinue) -and -not (Test-Path -LiteralPath $StopPath)){
 $record=[ordered]@{at=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000;pid=$PID;fps=$null;gamescrcpy_pid=$null;state='软件未运行'}
 try{
  $apps=@(Get-Process -Name GameScrcpy -ErrorAction SilentlyContinue)
  if($apps.Count -eq 1){
   $record.gamescrcpy_pid=$apps[0].Id
   $condition=[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ProcessIdProperty,[int]$apps[0].Id)
   $elements=$root.FindAll([Windows.Automation.TreeScope]::Children,$condition)
   $labels=@($elements | Where-Object {$_.Current.ClassName -eq 'QLabel' -and $_.Current.Name -match '^FPS[:：]\s*\d+\s*$'})
   if($labels.Count -eq 0){
    # Qt tool labels may disappear from RootElement while their video window is
    # minimized. Direct HWND access can still read the native label value.
    $script:labelHandles=[Collections.Generic.List[IntPtr]]::new()
    $script:fpsOwner=[uint32]$apps[0].Id
    $callback=[FpsWindows+Visit]{param($h,$p)
     [uint32]$owner=0;[void][FpsWindows]::GetWindowThreadProcessId($h,[ref]$owner)
     if($owner -eq $script:fpsOwner){$script:labelHandles.Add($h)}
     return $true
    }
    [void][FpsWindows]::EnumWindows($callback,[IntPtr]::Zero)
    $labels=@(foreach($handle in $script:labelHandles){
     try{$item=[Windows.Automation.AutomationElement]::FromHandle($handle);if($item.Current.ClassName -eq 'QLabel' -and $item.Current.Name -match '^FPS[:：]\s*\d+\s*$'){$item}}catch{}
    })
   }
   if($labels.Count -eq 1){
    $record.fps=[int]([regex]::Match($labels[0].Current.Name,'\d+').Value)
    $record.state='软件原生 FPS'
   }else{$record.state='暂无投屏 FPS'}
  }elseif($apps.Count -gt 1){$record.state='多个投屏进程，无法唯一确认 FPS'}
 }catch{$record.state='FPS 读取失败';$record.error=$_.Exception.Message}
 try{
  $temporary=$OutputPath+'.tmp'
  [IO.File]::WriteAllText($temporary,($record|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
  [IO.File]::Move($temporary,$OutputPath,$true)
 }catch{}
 Start-Sleep -Milliseconds 1000
}

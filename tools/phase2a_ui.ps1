param([string]$ProcessName='antimicrox',[string]$Action='snapshot',[string]$Name,[string]$Id,[string]$Value,[int]$Index=0,[string]$Evidence)
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$OutputEncoding=[Console]::OutputEncoding
if($PSVersionTable.PSVersion -lt [version]'7.6.4'){throw 'PowerShell >=7.6.4 required'}
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$pids=@(Get-Process -Name $ProcessName -ErrorAction Stop | ForEach-Object Id)
$root=[System.Windows.Automation.AutomationElement]::RootElement
$windows=@($root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition) | Where-Object {$_.Current.ProcessId -in $pids})
$elements=@()
foreach($w in $windows){$elements+=$w; $elements+=@($w.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition))}
for($attempt=0;$attempt -lt 4 -and $elements.Count -lt 15;$attempt++){
 Start-Sleep -Milliseconds 200
 $windows=@($root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition) | Where-Object {$_.Current.ProcessId -in $pids})
 $elements=@()
 foreach($w in $windows){try{$elements+=$w;$elements+=@($w.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition))}catch{}}
}
if($Action -eq 'snapshot'){
 $rows=@($elements | Where-Object { $null -ne $_ } | ForEach-Object {
   $v=''; try{$v=$_.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value}catch{}
   [ordered]@{Name=$_.Current.Name; Id=$_.Current.AutomationId; Type=$_.Current.ControlType.ProgrammaticName; Class=$_.Current.ClassName; PID=$_.Current.ProcessId; Enabled=$_.Current.IsEnabled; Offscreen=$_.Current.IsOffscreen; Value=$v; Help=$_.Current.HelpText; Rect=$_.Current.BoundingRectangle.ToString()}
 })
 $json=ConvertTo-Json -InputObject $rows -Depth 4
 if($Evidence){[IO.File]::WriteAllText($Evidence,$json,[Text.UTF8Encoding]::new($false))}
 $json
}else{
 $matches=@($elements | Where-Object {(-not $Name -or $_.Current.Name -eq $Name) -and (-not $Id -or $_.Current.AutomationId -eq $Id)})
 if($matches.Count -le $Index){throw "UI target missing: elements=$($elements.Count), matches=$($matches.Count), index=$Index, id=$Id"}
 $element=$matches[$Index]
 switch($Action){
  'invoke' {$element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()}
  'value' {$element.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($Value)}
  'select' {$element.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()}
  'expand' {$element.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern).Expand()}
  'focus' {$element.SetFocus()}
  'click' {
   if($element.Current.IsOffscreen -or -not $element.Current.IsEnabled){throw 'UI target not visible/enabled'}
   $rect=$element.Current.BoundingRectangle
   if($rect.Width -lt 2 -or $rect.Height -lt 2){throw 'Invalid target rectangle'}
   Add-Type @'
using System;using System.Runtime.InteropServices;public class ConfigClick2A{[StructLayout(LayoutKind.Sequential)]public struct P{public int x,y;} [DllImport("user32.dll")]public static extern bool SetCursorPos(int x,int y);[DllImport("user32.dll")]public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);[DllImport("user32.dll")]public static extern bool SetForegroundWindow(IntPtr h);[DllImport("user32.dll")]public static extern IntPtr GetForegroundWindow();[DllImport("user32.dll")]public static extern IntPtr WindowFromPoint(P p);[DllImport("user32.dll")]public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);}
'@
   $ownerPid=$element.Current.ProcessId
   [uint32]$foregroundPid=0
   [void][ConfigClick2A]::GetWindowThreadProcessId([ConfigClick2A]::GetForegroundWindow(),[ref]$foregroundPid)
   if($foregroundPid -ne $ownerPid){[void][ConfigClick2A]::SetForegroundWindow((Get-Process -Id $ownerPid).MainWindowHandle);throw 'Activated application; open its popup again before clicking'}
   Start-Sleep -Milliseconds 150
   $pt=[ConfigClick2A+P]::new();$pt.x=[int]($rect.X+$rect.Width/2);$pt.y=[int]($rect.Y+$rect.Height/2)
   $under=[ConfigClick2A]::WindowFromPoint($pt);[uint32]$pointPid=0
   [void][ConfigClick2A]::GetWindowThreadProcessId($under,[ref]$pointPid)
   if($pointPid -ne $ownerPid){throw 'Another process covers UI target; no input sent'}
   [void][ConfigClick2A]::SetCursorPos($pt.x,$pt.y)
   [ConfigClick2A]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
   [ConfigClick2A]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
  }
  default {throw 'Unknown action'}
 }
 [pscustomobject]@{Action=$Action;Name=$element.Current.Name;Id=$element.Current.AutomationId;PID=$element.Current.ProcessId}
}

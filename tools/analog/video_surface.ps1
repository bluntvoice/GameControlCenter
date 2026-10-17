param([long]$VideoHandle)
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$OutputEncoding=[Console]::OutputEncoding
if($PSVersionTable.PSVersion -lt [version]'7.6.4'){throw 'PowerShell >=7.6.4 required'}
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes
$root=[Windows.Automation.AutomationElement]::FromHandle([IntPtr]$VideoHandle)
$edit=$root.FindFirst([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ClassNameProperty,'KeyMapEditView'))
if($edit -and -not $edit.Current.IsOffscreen){throw '键位编辑中，等待退出编辑器后自动控制'}
$surface=$root.FindFirst([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ClassNameProperty,'D3D11VideoWidget'))
if(-not $surface -or $surface.Current.NativeWindowHandle -eq 0){throw 'Cannot identify native video surface'}
[ordered]@{handle=$surface.Current.NativeWindowHandle;class=$surface.Current.ClassName}|ConvertTo-Json -Compress

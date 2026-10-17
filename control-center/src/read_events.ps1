param([Parameter(Mandatory)][string]$Since)
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$OutputEncoding=[Console]::OutputEncoding
if($PSVersionTable.PSVersion -lt [version]'7.6.4'){throw 'PowerShell >=7.6.4 required'}
$sinceTime=[datetime]::Parse($Since).ToLocalTime()
$events=@(Get-WinEvent -FilterHashtable @{LogName='Application';Id=@(1000,1002);StartTime=$sinceTime} -ErrorAction SilentlyContinue)
$records=@(foreach($event in $events){
 [xml]$xml=$event.ToXml();$fields=@{}
 foreach($data in $xml.Event.EventData.Data){$fields[[string]$data.Name]=[string]$data.'#text'}
 $app=$fields.AppName
 if($app -notin @('GameScrcpy.exe','antimicrox.exe','pythonw.exe','pwsh.exe')){continue}
 $processValue=$fields.ProcessId
 $processIdValue=$null
 if($processValue -match '^0x'){$processIdValue=[Convert]::ToInt32($processValue.Substring(2),16)}
 elseif($processValue -match '^\d+$'){$processIdValue=[int]$processValue}
 [ordered]@{record_id=$event.RecordId;event_id=$event.Id;pid=$processIdValue;app=$app;app_path=$fields.AppPath;exception_code=$fields.ExceptionCode;time=$event.TimeCreated.ToString('o')}
})
ConvertTo-Json -InputObject $records -Depth 5 -Compress

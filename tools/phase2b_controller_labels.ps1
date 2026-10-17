param([switch]$Stop)
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$OutputEncoding=[Console]::OutputEncoding
if($PSVersionTable.PSVersion -lt [version]'7.6.4'){throw 'PowerShell >=7.6.4 required'}
$project=Split-Path $PSScriptRoot -Parent
$phase=Join-Path $project 'phase2b-20261015'
$pidFile=Join-Path $phase 'evidence/controller-labels.pid'
$statusFile=Join-Path $phase 'evidence/controller-labels-status.json'
if($Stop){
 if(Test-Path -LiteralPath $pidFile){
  $helperId=[int][IO.File]::ReadAllText($pidFile,[Text.Encoding]::UTF8)
  $instance=Get-CimInstance Win32_Process -Filter "ProcessId=$helperId" -ErrorAction SilentlyContinue
  if($instance -and $instance.CommandLine -like '*phase2b_controller_labels.ps1*'){
   $proc=Get-Process -Id $helperId -ErrorAction Stop
   [void]$proc.CloseMainWindow()
  }
 }
 exit
}
$mutex=[Threading.Mutex]::new($false,'Local\GameControlProfiles_ControllerLabels2B')
if(-not $mutex.WaitOne(0)){exit}
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase,UIAutomationClient,UIAutomationTypes
Add-Type -Path (Join-Path $PSScriptRoot 'label_feedback.cs')
Add-Type @'
using System;using System.Runtime.InteropServices;
public class LabelWindow2B {
 [DllImport("user32.dll")]public static extern int GetWindowLong(IntPtr h,int n);
 [DllImport("user32.dll")]public static extern int SetWindowLong(IntPtr h,int n,int v);
 [DllImport("user32.dll")]public static extern bool IsIconic(IntPtr h);
 [DllImport("user32.dll")]public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")]public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);
}
'@
[xml]$markup=@'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" Title="手柄名称提示" Width="600" Height="300" WindowStyle="None" AllowsTransparency="True" Background="Transparent" Topmost="True" ShowInTaskbar="False" ShowActivated="False" Focusable="False" ResizeMode="NoResize" UseLayoutRounding="True">
 <Canvas Name="Labels" IsHitTestVisible="False" ClipToBounds="True"/>
</Window>
'@
$window=[Windows.Markup.XamlReader]::Load([Xml.XmlNodeReader]::new($markup))
$canvas=$window.FindName('Labels')
$brushConverter=[Windows.Media.BrushConverter]::new()
$settings=Get-Content -LiteralPath (Join-Path $phase 'analog/settings.json') -Encoding utf8 -Raw | ConvertFrom-Json
$feedback=[LabelFeedbackSampler]::new($settings.left_deadzone,$settings.right_deadzone)
$script:feedbackLabels=@{};$script:gamePid=0;$script:analogPid=0
$script:activeLabels=@();$script:activationCounts=@{};$script:lastFeedbackReport=[datetime]::MinValue
$window.Add_SourceInitialized({
 $hwnd=[Windows.Interop.WindowInteropHelper]::new($window).Handle
 $style=[LabelWindow2B]::GetWindowLong($hwnd,-20)
 [void][LabelWindow2B]::SetWindowLong($hwnd,-20,(($style -band (-bnot 0x40000)) -bor 0x80 -bor 0x20 -bor 0x08000000 -bor 0x80000))
})
[IO.File]::WriteAllText($pidFile,[string]$PID,[Text.UTF8Encoding]::new($false))
$script:lastStatus=''
function Write-LabelStatus($state,$detail,$count){
 $body=[ordered]@{state=$state;detail=$detail;labels=$count;pid=$PID;mode='read-only click-through; no input interception';feedback='gamepad and mouse; native sampling 8ms; visual refresh 33ms';active_labels=$script:activeLabels;activation_counts=$script:activationCounts;feedback_error=$script:feedbackError;at=(Get-Date).ToString('o')}
 $key="$state|$detail|$count|$script:feedbackError|$($script:activeLabels -join ',')|$($script:activationCounts|ConvertTo-Json -Compress)"
 if($key -ne $script:lastStatus){
  try{[IO.File]::WriteAllText($statusFile,($body|ConvertTo-Json),[Text.UTF8Encoding]::new($false));$script:lastStatus=$key}catch{}
 }
}
function Add-Label([string]$text,[string]$color,[double]$x,[double]$y,[string]$key='',[double]$hitRadius=0){
 $block=[Windows.Controls.TextBlock]::new();$block.Text=$text;$block.FontSize=13;$block.FontWeight='SemiBold'
 $block.FontFamily=[Windows.Media.FontFamily]::new('Microsoft YaHei UI')
 $block.Foreground=$brushConverter.ConvertFromString($color)
 $border=[Windows.Controls.Border]::new();$border.Background=$brushConverter.ConvertFromString('#E6101E2B')
 $border.BorderBrush=$brushConverter.ConvertFromString($color);$border.BorderThickness=[Windows.Thickness]::new(2)
 $border.CornerRadius=[Windows.CornerRadius]::new(5);$border.Padding=[Windows.Thickness]::new(5,2,5,2);$border.Child=$block
 $border.Measure([Windows.Size]::new([double]::PositiveInfinity,[double]::PositiveInfinity))
 $width=$border.DesiredSize.Width;$height=$border.DesiredSize.Height
 $left=[Math]::Max(0,[Math]::Min($x,$window.Width-$width-2))
 $top=[Math]::Max(0,[Math]::Min($y,$window.Height-$height-2))
 for($try=0;$try -lt 18;$try++){
  $box=[Windows.Rect]::new($left,$top,$width+4,$height+4)
  if(-not @($script:occupied | Where-Object {$_.IntersectsWith($box)}).Count){break}
  $top=[Math]::Max(0,$top-$height-5)
 }
 if(([Math]::Abs($left-$x)+[Math]::Abs($top-$y)) -gt 5 -and -not $text.StartsWith('手柄标识')){
  $line=[Windows.Shapes.Line]::new();$line.X1=$x-9;$line.Y1=$y+31;$line.X2=$left+8;$line.Y2=$top+$height/2
  $line.Stroke=$brushConverter.ConvertFromString($color);$line.Opacity=0.7;$line.StrokeThickness=1
  [void]$canvas.Children.Add($line)
 }
 $script:occupied+=,$box
 [Windows.Controls.Canvas]::SetLeft($border,$left)
 [Windows.Controls.Canvas]::SetTop($border,$top)
 [void]$canvas.Children.Add($border)
 if($key){
  $border.Opacity=0.82
  $script:feedbackLabels[$key]=@{border=$border;block=$block;normal=$block.Foreground;active=$brushConverter.ConvertFromString($color);x=$x-9;y=$y+31;level=-1;hitRadius=$hitRadius}
 }
}
$feedbackTimer=[Windows.Threading.DispatcherTimer]::new();$feedbackTimer.Interval=[TimeSpan]::FromMilliseconds(33)
$feedbackTimer.Add_Tick({
 if($window.Opacity -eq 0 -or $script:feedbackLabels.Count -eq 0){return}
 try{
  $snapshot=$feedback.Read();$mouseKey=''
  if($snapshot.MouseActive -and $snapshot.MousePid -in @($script:gamePid,$script:analogPid)){
   $matrix=[Windows.PresentationSource]::FromVisual($window).CompositionTarget.TransformFromDevice
   $mouse=$matrix.Transform([Windows.Point]::new($snapshot.MouseX,$snapshot.MouseY))
   $mx=$mouse.X-$window.Left;$my=$mouse.Y-$window.Top
   $closest=[double]::PositiveInfinity
   if($mx -ge 0 -and $my -ge 0 -and $mx -le $window.Width -and $my -le $window.Height){
    foreach($key in $script:feedbackLabels.Keys){
     $item=$script:feedbackLabels[$key];$distance=[Math]::Sqrt([Math]::Pow($mx-$item.x,2)+[Math]::Pow($my-$item.y,2))
     $limit=if($item.hitRadius -gt 0){$item.hitRadius}else{[Math]::Max(22,[Math]::Min(55,$window.Width*0.03))}
     if($distance -lt $closest -and $distance -le $limit){$closest=$distance;$mouseKey=$key}
    }
   }
  }
  $active=@()
  foreach($key in $script:feedbackLabels.Keys){
   $item=$script:feedbackLabels[$key];$level=0.0
   if($snapshot.Levels.ContainsKey($key)){$level=$snapshot.Levels[$key]}
   if($key -eq $mouseKey){$level=1.0}
   $level=[Math]::Round($level,2)
   if($level -gt 0){$active+=$key}
   if($level -gt 0 -and $item.level -le 0){$script:activationCounts[$key]=1+[int]$script:activationCounts[$key]}
   if($level -eq $item.level){continue};$item.level=$level
   if($level -gt 0){
    $item.border.Background=$item.active;$item.border.BorderBrush=[Windows.Media.Brushes]::White
    $item.block.Foreground=$brushConverter.ConvertFromString('#081522');$item.block.FontWeight='Bold'
    $item.border.Opacity=0.72+0.28*$level
   }else{
    $item.border.Background=$brushConverter.ConvertFromString('#E6101E2B');$item.border.BorderBrush=$item.normal
    $item.block.Foreground=$item.normal;$item.block.FontWeight='SemiBold';$item.border.Opacity=0.82
   }
  }
  $script:activeLabels=@($active|Sort-Object)
  if(((Get-Date)-$script:lastFeedbackReport).TotalMilliseconds -ge 200){
   $script:lastFeedbackReport=Get-Date
   Write-LabelStatus 'visible' $script:currentProfileName $script:feedbackLabels.Count
  }
 }catch{$script:feedbackError=$_.Exception.Message}
})
$timer=[Windows.Threading.DispatcherTimer]::new();$timer.Interval=[TimeSpan]::FromMilliseconds(900)
$timer.Add_Tick({
 try{
  $gs=Get-Process -Name GameScrcpy -ErrorAction SilentlyContinue | Select-Object -First 1
  $script:gamePid=if($gs){$gs.Id}else{0};$script:analogPid=0
  if(-not $gs){$window.Opacity=0;Write-LabelStatus 'hidden' 'GameScrcpy not running' 0;return}
  [uint32]$foregroundPid=0;[void][LabelWindow2B]::GetWindowThreadProcessId([LabelWindow2B]::GetForegroundWindow(),[ref]$foregroundPid)
  $analogActive=$false
  $analogStatus=Join-Path $phase 'analog/status.json'
  if($foregroundPid -ne $gs.Id -and (Test-Path -LiteralPath $analogStatus)){
   try{
    $status=Get-Content -LiteralPath $analogStatus -Raw -Encoding utf8 | ConvertFrom-Json
    if($status.armed -and $status.pid -eq $foregroundPid -and ((Get-Date)-[datetime]$status.at).TotalSeconds -lt 2){
     $owner=Get-CimInstance Win32_Process -Filter "ProcessId=$foregroundPid" -ErrorAction Stop
     $analogActive=$owner.CommandLine -like '*tools*analog*pad_adapter.py*'
     if($analogActive){$script:analogPid=$foregroundPid}
    }
   }catch{}
  }
  if($foregroundPid -ne $gs.Id -and -not $analogActive){$window.Opacity=0;Write-LabelStatus 'hidden' 'GameScrcpy not foreground' 0;return}
  $root=[Windows.Automation.AutomationElement]::RootElement
  $condition=[Windows.Automation.AndCondition]::new(
   [Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ProcessIdProperty,[int]$gs.Id),
   [Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ClassNameProperty,'VideoForm'))
  $form=$root.FindFirst([Windows.Automation.TreeScope]::Children,$condition)
  if(-not $form -or [LabelWindow2B]::IsIconic([IntPtr]$form.Current.NativeWindowHandle)){$window.Opacity=0;return}
  $video=$form.FindFirst([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ClassNameProperty,'D3D11VideoWidget'))
  if(-not $video -or $video.Current.IsOffscreen){$window.Opacity=0;return}
  $rect=$video.Current.BoundingRectangle
  if($rect.Width -lt 100 -or $rect.Height -lt 100){$window.Opacity=0;return}
  $config=Get-Content -LiteralPath (Join-Path $project 'control-center/config.json') -Encoding utf8 -Raw | ConvertFrom-Json
  $apps=@{gamescrcpy=(Split-Path $config.gamescrcpy -Parent)}
  $serial=$form.Current.Name -replace '^Phone - ','' -replace ':','_'
  $ini=[IO.File]::ReadAllText((Join-Path $apps.gamescrcpy 'config/userdata.ini'),[Text.Encoding]::UTF8)
  $section=[regex]::Match($ini,'(?ms)^\['+[regex]::Escape($serial)+'\]\s*\r?\n(?<body>.*?)(?=^\[|\z)').Groups['body'].Value
  $file=[regex]::Match($section,'(?m)^KeyMap=(.+)$').Groups[1].Value.Trim()
  $profilePath=Join-Path $apps.gamescrcpy "keymap/$file"
  $libraryPath=Join-Path $phase 'profiles/library.json'
  $entry=$null
  if(Test-Path -LiteralPath $libraryPath){
   $library=Get-Content -LiteralPath $libraryPath -Raw -Encoding utf8 | ConvertFrom-Json
   $entry=$library.profiles|Where-Object id -eq $library.active|Select-Object -First 1
   if(-not $entry){$window.Opacity=0;return}
   $profilePath=$entry.path;$file=$entry.name
  }elseif($file -notin @('party_arena_3skills_controller.json','超燃竞技场-三技能.json')){$window.Opacity=0;Write-LabelStatus 'hidden' "Other scheme: $file" 0;return}
  $script:currentProfileName=$file
  $profile=Get-Content -LiteralPath $profilePath -Encoding utf8 -Raw | ConvertFrom-Json
  $names=Get-Content -LiteralPath (Join-Path $phase 'controller-labels.json') -Encoding utf8 -Raw | ConvertFrom-Json -AsHashtable
  $extra=@{Key_BracketLeft='LS';Key_BracketRight='RS';Key_Return='Start';Key_Backspace='Back';LeftButton='鼠标左键';RightButton='鼠标右键'}
  foreach($key in $extra.Keys){$names[$key]=@{pad=$extra[$key];action='';color='#C9DEEC'}}
  $matrix=[Windows.PresentationSource]::FromVisual($window).CompositionTarget.TransformFromDevice
  $point=$matrix.Transform([Windows.Point]::new($rect.X,$rect.Y))
  $window.Left=$point.X;$window.Top=$point.Y;$window.Width=$rect.Width*$matrix.M11;$window.Height=$rect.Height*$matrix.M22
  $layoutKey="$file|$rect|$((Get-Item -LiteralPath $profilePath).LastWriteTimeUtc.Ticks)|$((Get-Item -LiteralPath (Join-Path $phase 'controller-labels.json')).LastWriteTimeUtc.Ticks)"
  if($layoutKey -eq $script:lastLayoutKey){$window.Opacity=1;Write-LabelStatus 'visible' $file $script:feedbackLabels.Count;return}
  $canvas.Children.Clear();$script:feedbackLabels=@{};$count=0;$script:occupied=@()
  foreach($node in $profile.keyMapNodes){
   $key=$node.key;$position=$node.pos
   if($node.type -eq 'KMT_STEER_WHEEL'){$key='wheel';$position=$node.centerPos}
   elseif($node.type -eq 'KMT_CAMERA_MOVE'){$key='camera'}
   elseif($node.type -eq 'KMT_FREE_LOOK'){$position=$node.startPos}
   if(-not $names.ContainsKey($key)){continue}
   $label=$names[$key];$bridge=if($key.StartsWith('Key_F')){' · '+$key.Substring(4)}else{''}
   $text=if([string]::IsNullOrWhiteSpace($label.action)){$label.pad+$bridge}else{$label.pad+' · '+$label.action+$bridge}
   $radius=0
   if($entry -and $key -notin @('wheel','camera')){
    $control=$entry.controls|Where-Object name -eq $label.pad|Select-Object -First 1
    if($control.hit_radius -gt 0){
     $radius=[double]$control.hit_radius*$window.Height/1200
     $circle=[Windows.Shapes.Ellipse]::new();$circle.Width=$radius*2;$circle.Height=$radius*2
     $circle.Stroke=$brushConverter.ConvertFromString('#EACB88');$circle.StrokeThickness=1.5;$circle.Opacity=0.65
     $circle.StrokeDashArray=[Windows.Media.DoubleCollection]::new([double[]]@(4,3))
     [Windows.Controls.Canvas]::SetLeft($circle,$position.x*$window.Width-$radius)
     [Windows.Controls.Canvas]::SetTop($circle,$position.y*$window.Height-$radius)
     [void]$canvas.Children.Add($circle)
    }
   }
   Add-Label $text $label.color ($position.x*$window.Width+9) ($position.y*$window.Height-31) $key $radius
   $count++
  }
  $script:lastLayoutKey=$layoutKey
  $window.Opacity=1;Write-LabelStatus 'visible' $file $count
 }catch{$window.Opacity=0;Write-LabelStatus 'retry' $_.Exception.Message 0}
})
$window.Add_Closed({$timer.Stop();$feedbackTimer.Stop();Write-LabelStatus 'stopped' 'Overlay closed' 0})
try{$timer.Start();$feedbackTimer.Start();[void]$window.ShowDialog()}finally{$feedback.Dispose();$mutex.ReleaseMutex();$mutex.Dispose()}

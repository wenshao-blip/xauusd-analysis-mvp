$runner = Join-Path $PSScriptRoot 'run_scheduled.cmd'
$scheduledAction = "cmd.exe /d /c `"`"$runner`"`""

# 北京时间三个固定会话；程序内部仍会核验工作日、行情新鲜度与去重键。
foreach ($slot in @('08:30','15:00','20:00')) {
  $name = $slot.Replace(':','')
  schtasks.exe /Create /F /TN "AurumSignal-$name" /TR $scheduledAction /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST $slot | Out-Host
}

# 移除旧任务，避免重复生成。
foreach ($name in @('AurumSignal-Every2Hours','AurumSignal-2100','AurumSignal-0400','AurumSignal-1000','AurumSignal-1600')) {
  schtasks.exe /Delete /F /TN $name 2>$null | Out-Null
}

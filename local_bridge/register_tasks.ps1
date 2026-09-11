$runner = Join-Path $PSScriptRoot 'run_scheduled.cmd'
$supplementalRunner = Join-Path $PSScriptRoot 'run_supplemental.cmd'
$scheduledAction = "cmd.exe /d /c `"`"$runner`"`""
$supplementalAction = "cmd.exe /d /c `"`"$supplementalRunner`"`""

# 00:00, 02:00 ... 22:00: 每两小时生成、结算和更新网页。
schtasks.exe /Create /F /TN 'AurumSignal-Every2Hours' /TR $scheduledAction /SC HOURLY /MO 2 /ST 00:00 | Out-Host

# 21:00 不在两小时序列内，保留为美盘完整报告时点。
schtasks.exe /Create /F /TN 'AurumSignal-2100' /TR $supplementalAction /SC DAILY /ST 21:00 | Out-Host

# 移除旧的三次固定任务，避免同一时点重复运行。
foreach ($name in @('AurumSignal-0400','AurumSignal-1000','AurumSignal-1600')) {
  schtasks.exe /Delete /F /TN $name 2>$null | Out-Null
}

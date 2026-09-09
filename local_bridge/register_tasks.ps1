$runner = Join-Path $PSScriptRoot 'run_scheduled.cmd'
foreach ($time in @('04:00','10:00','16:00')) {
  $suffix = $time.Replace(':','')
  schtasks.exe /Create /F /TN "AurumSignal-$suffix" /TR "`"$runner`"" /SC DAILY /ST $time | Out-Host
}

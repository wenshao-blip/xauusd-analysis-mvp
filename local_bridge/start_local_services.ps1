$root = Split-Path -Parent $PSScriptRoot
$python = 'C:\Users\15693\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$bridge = Join-Path $PSScriptRoot 'control_server.py'
$vinext = Join-Path $root 'node_modules\.bin\vinext.cmd'

if (-not (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)) {
  Start-Process -FilePath $python -ArgumentList ('"' + $bridge + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
}
if (-not (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue)) {
  Start-Process -FilePath 'cmd.exe' -ArgumentList '/d','/c',('""' + $vinext + '" dev --host 127.0.0.1 --port 3000"') -WorkingDirectory $root -WindowStyle Hidden
}

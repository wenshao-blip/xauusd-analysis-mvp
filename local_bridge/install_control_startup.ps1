$source = Join-Path $PSScriptRoot 'AurumSignal-ControlServer.vbs'
$target = Join-Path ([Environment]::GetFolderPath('Startup')) 'AurumSignal-ControlServer.vbs'
$content = Get-Content -Raw -Encoding UTF8 -LiteralPath $source
# Windows Script Host needs Unicode here because the project path contains Chinese characters.
Set-Content -LiteralPath $target -Value $content -Encoding Unicode
Start-Process -FilePath 'wscript.exe' -ArgumentList ('"' + $target + '"') -WindowStyle Hidden

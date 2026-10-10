# start_silent.ps1 -- start AINSNBOT (Easel web + OpenClaw gateway) with NO visible window.
# ASCII only on purpose: PowerShell 5.1 reads no-BOM files as ANSI, Chinese literals break it.
# Logs:  D:\@kaifa\aiyouhu\outputs\logs\launch.log  (launcher actions)
#        D:\@kaifa\aiyouhu\outputs\logs\web-silent.log  (web stdout/stderr)
$ErrorActionPreference = 'Continue'
$App  = 'D:\@kaifa\aiyouhu'
$Node = 'C:\Users\20200\node24\node-v24.21.0-win-x64'
$OutDir = Join-Path $App 'outputs\logs'
$Log    = Join-Path $OutDir 'web-silent.log'
$LaunchLog = Join-Path $OutDir 'launch.log'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

function L($m) {
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m"
  Add-Content -LiteralPath $LaunchLog -Value $line -Encoding UTF8
}
function Test-Web {
  try { return (Invoke-WebRequest 'http://127.0.0.1:7860/' -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 }
  catch { return $false }
}

$env:PATH = "$App\.venv\Scripts;$Node;C:\Users\20200\AppData\Local\hermes\git\cmd;C:\Users\20200\bin;$env:PATH"
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

if (Test-Web) {
  L 'web already listening on 7860 -> reopen browser only'
  Start-Process 'http://127.0.0.1:7860'
  exit 0
}

# 1) OpenClaw gateway (idempotent, itself hidden)
$gp = Join-Path $App 'scripts\gateway.ps1'
if (Test-Path $gp) {
  Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -Wait -ArgumentList @(
    '-NoProfile','-ExecutionPolicy','Bypass','-File',$gp,'start'
  )
  L 'gateway.ps1 start finished'
}

# 2) web, hidden, stdout/stderr to log files
$exe = Join-Path $App '.venv\Scripts\easel.exe'
if (-not (Test-Path $exe)) { L "ABORT missing $exe"; exit 1 }
Start-Process -FilePath $exe -ArgumentList 'web' -WorkingDirectory $App -WindowStyle Hidden `
  -RedirectStandardOutput $Log -RedirectStandardError ($Log + '.err')
L 'web launched (hidden)'

# 3) wait until ready, then open the browser (up to 90s)
$ready = $false
for ($i = 0; $i -lt 45; $i++) {
  Start-Sleep -Seconds 2
  if (Test-Web) { $ready = $true; break }
}
if ($ready) {
  Start-Process 'http://127.0.0.1:7860'
  L 'web ready -> browser opened'
} else {
  L 'web NOT ready after 90s -- check web-silent.log'
}

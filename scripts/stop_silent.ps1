# stop_silent.ps1 -- stop the AINSNBOT web (port 7860 owner + its easel/app.py wrappers).
# The OpenClaw gateway is a separate background process and is left running (same as before).
$ErrorActionPreference = 'Continue'
$killed = @()

$owners = (Get-NetTCPConnection -LocalPort 7860 -State Listen -ErrorAction SilentlyContinue).OwningProcess
foreach ($p in ($owners | Sort-Object -Unique)) {
  if ($p) {
    try { Stop-Process -Id $p -Force -ErrorAction Stop; $killed += "port-owner $p" } catch {}
  }
}

$procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
  $_.CommandLine -and ($_.CommandLine -match 'aiyouhu') -and
  (($_.CommandLine -match 'app\.py') -or ($_.CommandLine -match 'easel\.exe') -or ($_.CommandLine -match 'easel" web'))
}
foreach ($proc in $procs) {
  try { Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop; $killed += ("$($proc.Name) $($proc.ProcessId)") } catch {}
}

Start-Sleep -Seconds 2
$still = (Get-NetTCPConnection -LocalPort 7860 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count
if ($killed.Count -gt 0) { "stopped: " + ($killed -join ', ') } else { "nothing was running" }
"port 7860 listeners now: $still"

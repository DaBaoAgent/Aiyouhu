# wait_web.ps1 -- poll the AINSNBOT web front end until it answers, or time out.
# Exit 0 = ready, exit 1 = not ready within -Seconds.
# ASCII only (PowerShell 5.1 reads no-BOM files as ANSI).
param([int]$Seconds = 90, [int]$Port = 7860)
$deadline = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $deadline) {
  try {
    $r = Invoke-WebRequest "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 3
    if ($r.StatusCode -eq 200) { exit 0 }
  } catch { }
  Start-Sleep -Seconds 2
}
exit 1

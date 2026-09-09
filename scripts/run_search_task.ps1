# Runs one discovery pass and appends the output to data\logs\run_search_<date>.log.
# Registered as the Windows scheduled task "JobAgent Daily Search" (see scripts\install_task.ps1).
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$script = Join-Path $root "scripts\run_search.py"
$logDir = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("run_search_{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))
Set-Location $root
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') starting discovery run ===" | Out-File -FilePath $log -Append -Encoding utf8
& $python $script 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
"=== finished with exit code $LASTEXITCODE ===" | Out-File -FilePath $log -Append -Encoding utf8
exit $LASTEXITCODE

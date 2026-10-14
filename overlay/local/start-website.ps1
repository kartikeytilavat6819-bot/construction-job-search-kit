# Starts the career-ops website in the background at Windows logon ("career-ops website" task).
# Reachable only from this computer: http://127.0.0.1:3000
# Also starts two small local helpers (each exits at once if it is already running):
#   local\chrome-autofill\docs_server.py   read-only PDF helper for the Autofill Chrome extension (127.0.0.1:3001)
#   local\resume-builder\editor_server.py  Resume Editor (127.0.0.1:3002)
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
$env:NEXT_TELEMETRY_DISABLED = '1'
$root = Split-Path $PSScriptRoot -Parent

# pythonw.exe runs Python without a console window; fall back to python.exe (hidden window) if it isn't there.
$py = if (Get-Command 'pythonw.exe' -ErrorAction SilentlyContinue) { 'pythonw.exe' } else { 'python.exe' }
foreach ($helper in @('local\chrome-autofill\docs_server.py', 'local\resume-builder\editor_server.py')) {
    $path = Join-Path $root $helper
    if (Test-Path $path) {
        try { Start-Process $py -ArgumentList ('"' + $path + '"') -WorkingDirectory $root -WindowStyle Hidden } catch {}
    }
}

try {
    if ((Invoke-WebRequest 'http://127.0.0.1:3000' -UseBasicParsing -TimeoutSec 3).StatusCode -lt 500) { exit 0 }  # already running
} catch {}
Set-Location (Join-Path $root 'web')
$log = Join-Path $root 'data\logs\website.log'
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
node server.mjs start *>> $log

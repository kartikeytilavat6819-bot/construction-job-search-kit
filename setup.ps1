# career-ops starter kit: one-time setup (safe to run again; it never overwrites your personal files).
#
#   Double-click SETUP.cmd, or:  powershell -ExecutionPolicy Bypass -File setup.ps1 [-InstallDir C:\path] [-SkipPrereqs] [-NoTasks]
#
# What it does:
#   1. Installs anything missing: Git, Node.js, Python, VS Code + Claude Code extension, Google Chrome, TinyTeX (LaTeX).
#   2. Downloads career-ops (the open-source job-search agent) at the exact version this kit was tested on.
#   3. Copies the kit's extra tools (local\ scripts, website changes, shortcuts) on top.
#   4. Copies the starter profile files (construction management) ONLY where you don't have one yet.
#   5. Installs the code libraries and builds the website.
#   6. Schedules: the website at logon (http://127.0.0.1:3000) and a job scan at 7 AM and 5 PM.
#   7. Opens the folder in VS Code. Then open Claude Code and type:  Read local/START-HERE.md and set me up
param(
    [string]$InstallDir = (Join-Path $env:USERPROFILE 'career-ops'),
    [switch]$SkipPrereqs,
    [switch]$NoTasks,
    [switch]$NoOpen      # testing: no Desktop shortcut, don't open VS Code
)
$ErrorActionPreference = 'Stop'
$Kit = $PSScriptRoot
$Commit = (Get-Content (Join-Path $Kit 'patches\UPSTREAM_COMMIT.txt') -TotalCount 1).Trim()
$Upstream = 'https://github.com/career-ops-hq/career-ops.git'

function Step([string]$msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok([string]$msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Warn([string]$msg) { Write-Host "    $msg" -ForegroundColor Yellow }
function Have([string]$cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    $tt = Join-Path $env:APPDATA 'TinyTeX\bin\windows'
    if (Test-Path $tt) { $env:Path += ";$tt" }
}
function Run([string]$exe, [string[]]$argv, [string]$where = $null) {
    if ($where) { Push-Location $where }
    try {
        & $exe @argv
        if ($LASTEXITCODE -ne 0) { throw "$exe $($argv -join ' ') failed (exit $LASTEXITCODE)" }
    } finally { if ($where) { Pop-Location } }
}
function Winget([string]$id, [string]$name) {
    if (-not (Have 'winget')) { throw "winget is missing. Install '$name' by hand, then run SETUP.cmd again." }
    Write-Host "    installing $name ..."
    & winget install --id $id -e --silent --accept-source-agreements --accept-package-agreements | Out-Host
    Refresh-Path
}
function Python-Ok {
    # The Microsoft Store "python" stub exists on fresh Windows but is not a real Python.
    try { $v = & python -c "import sys; print(sys.version_info >= (3, 10))" 2>$null; return ($v -eq 'True') } catch { return $false }
}
function Node-Ok {
    try { $v = (& node -v) -replace '^v', ''; return ([version]$v -ge [version]'22.6.0') } catch { return $false }
}
function Chrome-Path {
    foreach ($p in "$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") {
        if (Test-Path $p) { return $p }
    }
    return $null
}

Write-Host "career-ops starter kit setup" -ForegroundColor White
Write-Host "Install folder: $InstallDir"
Get-ChildItem $Kit -Recurse -File | Unblock-File -ErrorAction SilentlyContinue   # files from a downloaded ZIP
Refresh-Path

# ---------------------------------------------------------------- 1. prerequisites
if (-not $SkipPrereqs) {
    Step 'Checking the programs career-ops needs'
    if (Have 'git') { Ok 'Git ok' } else { Winget 'Git.Git' 'Git' }
    if (Node-Ok) { Ok "Node.js $(node -v) ok" } else { Winget 'OpenJS.NodeJS.LTS' 'Node.js LTS' }
    if (Python-Ok) { Ok "$(python --version) ok" } else { Winget 'Python.Python.3.12' 'Python 3.12' }
    if (Have 'code') { Ok 'VS Code ok' } else { Winget 'Microsoft.VisualStudioCode' 'Visual Studio Code' }
    if (Chrome-Path) { Ok 'Google Chrome ok' } else { Winget 'Google.Chrome' 'Google Chrome' }
    if (Have 'pdflatex') { Ok 'LaTeX ok' } else {
        Write-Host '    installing TinyTeX (LaTeX, used to build one-page resume PDFs) ...'
        $bat = Join-Path $env:TEMP 'install-tinytex.bat'
        Invoke-WebRequest 'https://yihui.org/tinytex/install-bin-windows.bat' -OutFile $bat -UseBasicParsing
        & cmd /c "`"$bat`"" | Out-Host
        Refresh-Path
    }
    if (Have 'tlmgr') {
        & tlmgr install enumitem lm geometry hyperref 2>&1 | Out-Null   # packages the resume template uses
    }
    foreach ($c in 'git', 'node', 'npm', 'python') {
        if (-not (Have $c)) { throw "'$c' still isn't available. Close this window, open a new one and run SETUP.cmd again (new installs need a fresh window)." }
    }
    if (Have 'code') {
        & code --install-extension anthropic.claude-code --force 2>&1 | Out-Null
        Ok 'Claude Code extension for VS Code ok'
    }
}

# ---------------------------------------------------------------- 2. career-ops itself
Step "Downloading career-ops (version $($Commit.Substring(0, 8)))"
if (Test-Path (Join-Path $InstallDir '.git')) {
    Ok 'already downloaded, keeping your copy'
} else {
    Run 'git' @('clone', '--quiet', $Upstream, $InstallDir)
    Run 'git' @('-C', $InstallDir, 'checkout', '--quiet', '-b', 'starter-kit', $Commit)
    Ok "downloaded to $InstallDir"
}

# ---------------------------------------------------------------- 3. kit tools (always refreshed)
Step 'Adding the starter-kit tools'
& robocopy (Join-Path $Kit 'overlay') $InstallDir /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "copying the kit tools failed (robocopy $LASTEXITCODE)" }
Ok 'local\ scripts, website changes and shortcuts copied'

# ---------------------------------------------------------------- 4. personal files (only if missing)
Step 'Creating your personal files (only the ones you do not have yet)'
$tplRoot = Join-Path $Kit 'templates'
Get-ChildItem $tplRoot -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($tplRoot.Length + 1)
    $dest = Join-Path $InstallDir $rel
    if (Test-Path $dest) { Write-Host "    keep   $rel" }
    else {
        New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null
        Copy-Item $_.FullName $dest
        Write-Host "    new    $rel" -ForegroundColor Green
    }
}
New-Item -ItemType Directory -Force (Join-Path $InstallDir 'data\logs'), (Join-Path $InstallDir 'local\secrets') | Out-Null

# ---------------------------------------------------------------- 5. libraries + website build
Step 'Installing code libraries (a few minutes the first time)'
$env:NEXT_TELEMETRY_DISABLED = '1'
Run 'npm' @('install', '--no-audit', '--no-fund', '--loglevel=error') $InstallDir
Run 'npx' @('playwright', 'install', 'chromium') $InstallDir
Run 'python' @('-m', 'pip', 'install', '--user', '--quiet', '--disable-pip-version-check', '-r', (Join-Path $Kit 'requirements.txt'))
Run 'python' @('-m', 'playwright', 'install', 'chromium')   # used by the Jacobs job-board reader
Ok 'libraries installed'

Step 'Building the career-ops website'
$web = Join-Path $InstallDir 'web'
Run 'npm' @('ci', '--no-audit', '--no-fund', '--loglevel=error') $web
Run 'npm' @('run', 'build') $web
Ok 'website built'

Step 'Setting up plugins (Word export + H-1B sponsor history)'
Push-Location $InstallDir
try {
    & node plugins.mjs add docx --confirm 2>&1 | Out-Host
    & node plugins/h1b-sponsor/install-h1b-index.mjs 2>&1 | Out-Host   # public H-1B filing index, checked offline afterwards
} catch { Warn "plugin setup had a problem (not fatal): $_" }
Pop-Location

Step 'Health check'
Push-Location $InstallDir
try { & node doctor.mjs | Out-Host } catch { Warn "doctor.mjs reported a problem: $_" }
Pop-Location

# ---------------------------------------------------------------- 6. scheduled tasks
if (-not $NoTasks) {
    Step 'Scheduling the website (at logon) and the job scan (7 AM and 5 PM)'
    $ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $conhost = "$env:SystemRoot\System32\conhost.exe"
    function Task-Action([string]$script) {
        $argLine = "--headless `"$ps`" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$(Join-Path $InstallDir "local\$script")`""
        New-ScheduledTaskAction -Execute $conhost -Argument $argLine -WorkingDirectory $InstallDir
    }
    $me = "$env:USERDOMAIN\$env:USERNAME"
    $principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
    try {
        $set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
        Register-ScheduledTask -TaskName 'career-ops website' -Action (Task-Action 'start-website.ps1') `
            -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $me) -Principal $principal -Settings $set -Force | Out-Null
        $set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
        Register-ScheduledTask -TaskName 'career-ops daily scan' -Action (Task-Action 'daily-scan.ps1') `
            -Trigger @((New-ScheduledTaskTrigger -Daily -At '7:00 AM'), (New-ScheduledTaskTrigger -Daily -At '5:00 PM')) `
            -Principal $principal -Settings $set -Force | Out-Null
        Ok 'tasks created (check them any time: Task Scheduler > career-ops ...)'
        Start-ScheduledTask -TaskName 'career-ops website'
    } catch {
        Warn "Could not create scheduled tasks ($_). Use 'Start career-ops.cmd' and 'Scan for jobs.cmd' in $InstallDir instead."
    }
}

# ---------------------------------------------------------------- 7. shortcut + finish
if (-not $NoOpen) { try {
    $lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'career-ops.lnk'
    $sh = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $sh.TargetPath = $InstallDir; $sh.Save()
} catch {} }

Write-Host "`nSetup finished." -ForegroundColor Green
Write-Host @"

Next:
  1. VS Code is opening the career-ops folder. Click the Claude icon (or press Ctrl+Esc), sign in with your Claude account.
  2. Put your current resume (PDF or Word) in:  $InstallDir\documents\
  3. Type to Claude:   Read local/START-HERE.md and set me up
     Claude walks you through the rest (about 30-45 minutes).

Website: http://127.0.0.1:3000  (starts by itself when you log in; 'Start career-ops.cmd' starts it by hand)
"@
if (-not $NoOpen -and (Have 'code')) { Start-Process 'code' -ArgumentList "`"$InstallDir`"" -WindowStyle Hidden }

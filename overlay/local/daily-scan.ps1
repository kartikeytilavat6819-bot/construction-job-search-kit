# Unattended daily run for Windows Task Scheduler ("career-ops daily scan").
# Scans every company board (no AI tokens), screens and ranks the new jobs for free, runs the job sieve,
# pulls Gmail / LinkedIn-alert leads and Calendar interviews when those plugins are enabled, logs everything
# to data\logs\, and shows a Windows notification with the result.
$ErrorActionPreference = 'Continue'
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
$env:PYTHONIOENCODING = 'utf-8'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$logDir = Join-Path $root 'data\logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir ("daily-scan-{0:yyyy-MM-dd_HHmm}.log" -f (Get-Date))

function Notify([string]$title, [string]$body) {
    try {
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
        $text = $xml.GetElementsByTagName('text')
        $text.Item(0).AppendChild($xml.CreateTextNode($title)) | Out-Null
        $text.Item(1).AppendChild($xml.CreateTextNode($body)) | Out-Null
        $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
    } catch { Add-Content $log "notify failed: $_" }
}

function Run([string]$label, [string[]]$nodeArgs) {
    Add-Content $log "`n===== $label  $(Get-Date -Format s)"
    $out = & node @nodeArgs 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
    Add-Content $log $out
    return @{ out = ($out -join "`n"); code = $code }
}

# True when config/plugins.yml has "<id>:" with "enabled: true" inside its block.
# (plugins.mjs exits with an error for a disabled plugin, so disabled ones are skipped quietly here.)
function PluginEnabled([string]$id) {
    $cfg = Join-Path $root 'config\plugins.yml'
    if (-not (Test-Path $cfg)) { return $false }
    $lines = @(Get-Content $cfg)
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match ('^(\s*)' + [regex]::Escape($id) + ':\s*(#.*)?$')) {
            $indent = $Matches[1].Length
            for ($j = $i + 1; $j -lt $lines.Count; $j++) {
                $l = $lines[$j]
                if ($l.Trim() -eq '' -or $l.TrimStart().StartsWith('#')) { continue }
                if (($l.Length - $l.TrimStart().Length) -le $indent) { break }
                if ($l -match '^\s*enabled:\s*true\b') { return $true }
            }
            return $false
        }
    }
    return $false
}

$portals = Get-Content (Join-Path $root 'portals.yml') -Raw

# Prefetch iCIMS boards one at a time (no time limit) into local\cache, so the scan's 20 s
# per-parser limit is never hit when many iCIMS boards run in parallel.
$icims = [regex]::Matches($portals, '(?m)careers_url:\s*(https://\S*icims\.com\S*)\s*\r?\n\s*scan_method:\s*local_parser\s*\r?\n\s*parser:[^\n]*icims_jobs\.py') | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique
if ($icims) {
    Add-Content $log "`n===== icims prefetch  $(Get-Date -Format s)"
    $pre = & python local\icims_jobs.py --prefetch @icims 2>&1 | ForEach-Object { "$_" }
    Add-Content $log $pre
}

# Same for global Workday boards read through local\workday_us_jobs.py (restricted by a Workday facet, e.g. US
# only). Every such portals.yml entry is prefetched with its own args, e.g.
#   parser: {command: python, script: local/workday_us_jobs.py, args: ["{careers_url}", "Location_Country=<id>"], format: jobs-json-v1}
$workday = [regex]::Matches($portals, '(?m)careers_url:\s*(https://\S+)\s*\r?\n\s*scan_method:\s*local_parser\s*\r?\n\s*parser:[^\n]*workday_us_jobs\.py[^\n]*args:\s*\[([^\]]*)\]')
foreach ($m in $workday) {
    $url = $m.Groups[1].Value
    $wdArgs = @($m.Groups[2].Value -split ',' | ForEach-Object { $_.Trim().Trim('"').Trim("'") } | Where-Object { $_ } |
        ForEach-Object { if ($_ -eq '{careers_url}') { $url } else { $_ } })
    if ($wdArgs.Count -eq 0) { continue }
    Add-Content $log "`n===== workday prefetch $url  $(Get-Date -Format s)"
    $pre = & python local\workday_us_jobs.py --prefetch @wdArgs 2>&1 | ForEach-Object { "$_" }
    Add-Content $log $pre
}

$scan = Run 'scan' @('scan.mjs')
$new = if ($scan.out -match 'New offers added:\s+(\d+)') { [int]$Matches[1] } else { 0 }
# Zero-token screening: drop foreign postings the location filter missed at scan time (bare city names,
# "SA Riyadh" style codes), rank (home area / entry-level / H-1B first), read the top JDs and drop postings
# that refuse sponsorship or are outside the US, re-rank, then run the job sieve (rules-only unless an AI
# model is set up; see local\sieve.py) and move decided rows out of Pending.
Add-Content $log "`n===== prune non-US  $(Get-Date -Format s)"
Add-Content $log (& node local\prune-location.mjs 2>&1 | ForEach-Object { "$_" })
foreach ($step in @(@('rank', @('local\rank_pipeline.py', '--top', '0')),
                    @('sponsor screen', @('local\sponsor_screen.py', '--top', '60', '--workers', '4')),
                    @('apply screen', @('local\apply_screen.py')),
                    @('re-rank', @('local\rank_pipeline.py', '--top', '0')),
                    @('job sieve', @('local\sieve.py', '--limit', '40')),
                    @('sieve: tick off rejected rows', @('local\sieve_clean_pending.py')),
                    @('link covers for the web app', @('local\link_covers.py')),
                    @('tracker locations for the web filter', @('local\build_locations.py')),
                    @('move decided rows out of Pending', @('local\clean_pending.py')))) {
    Add-Content $log "`n===== $($step[0])  $(Get-Date -Format s)"
    $o = & python @($step[1]) 2>&1 | ForEach-Object { "$_" }
    Add-Content $log $o
}
$sieveLine = (Select-String -Path $log -Pattern '^Sieve:' | Select-Object -Last 1).Line
$gold = if ($sieveLine -match 'GOLD (\d+)') { [int]$Matches[1] } else { 0 }

# Optional Google plugins: run only the ones enabled in config\plugins.yml.
$leads = 0
$gmail = $null
foreach ($id in @('gmail', 'linkedin-alerts', 'google-calendar')) {
    if (-not (PluginEnabled $id)) { Add-Content $log "`n===== $id  skipped (not enabled in config\plugins.yml)"; continue }
    $r = Run $id @('plugins.mjs', 'run', $id)
    if ($id -eq 'gmail') { $gmail = $r }
    if ($id -ne 'google-calendar' -and $r.out -match '(\d+)\s+new') { $leads += [int]$Matches[1] }
}

if ($gmail -and ($gmail.code -ne 0 -or $gmail.out -match 'token refresh failed|invalid_grant|missing GMAIL')) {
    Notify 'career-ops: reconnect Gmail' 'Google''s connection expired (it lasts about a week in Testing mode). Double-click "Connect Gmail.cmd" in the career-ops folder (10 seconds).'
}
if ($scan.code -ne 0) {
    Notify 'career-ops: scan had a problem' "See $log"
} elseif ($new + $leads -gt 0) {
    Notify "career-ops: $($new + $leads) new jobs" "$new from company boards, $leads from email alerts; $gold GOLD in the sieve. Open http://127.0.0.1:3000 in Chrome."
}
# keep the last 60 logs
Get-ChildItem $logDir -Filter 'daily-scan-*.log' | Sort-Object LastWriteTime -Descending | Select-Object -Skip 60 | Remove-Item -Force

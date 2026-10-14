# Live progress window for the OPTIONAL local-LLM quick-check (local/ollama_triage.py; needs Ollama, not used without a GPU).
# Reads data/triage/local-progress.json (written after every job); falls back to counting the newest
# data/triage/local-*.tsv results file. Close the window any time - it doesn't affect the run.
$ErrorActionPreference = 'SilentlyContinue'
$tri = Join-Path (Split-Path $PSScriptRoot -Parent) 'data\triage'
$host.UI.RawUI.WindowTitle = 'career-ops - local quick-check progress'

function Bar([double]$frac, [int]$width) {
    $fill = [Math]::Round($frac * $width)
    return ('#' * $fill) + ('-' * ($width - $fill))
}
function Fmt([double]$sec) {
    if ($sec -le 0 -or [double]::IsNaN($sec) -or [double]::IsInfinity($sec)) { return '--' }
    $t = [TimeSpan]::FromSeconds($sec)
    if ($t.TotalHours -ge 1) { return ('{0}h {1:D2}m' -f [int][Math]::Floor($t.TotalHours), $t.Minutes) }
    return ('{0}m {1:D2}s' -f $t.Minutes, $t.Seconds)
}

while ($true) {
    $p = $null
    $json = Join-Path $tri 'local-progress.json'
    $newest = Get-ChildItem $tri -Filter 'local-*.tsv' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (Test-Path $json) { $p = Get-Content $json -Raw | ConvertFrom-Json }
    if ($p -and $newest -and ((Resolve-Path $p.out).Path -ne $newest.FullName) -and ($newest.LastWriteTime -gt [DateTimeOffset]::FromUnixTimeSeconds([long]$p.updated).LocalDateTime)) { $p = $null }

    if ($p) {
        $done = [int]$p.done; $total = [int]$p.total; $model = $p.model; $file = Split-Path $p.out -Leaf
        $elapsed = (Get-Date).ToUniversalTime().Subtract([DateTime]'1970-01-01').TotalSeconds - [double]$p.started
        $counts = $p.counts; $recent = $p.recent; $state = $p.state
        $stale = ((Get-Date).ToUniversalTime().Subtract([DateTime]'1970-01-01').TotalSeconds - [double]$p.updated) -gt 600
    } elseif ($newest) {
        $rows = @(Import-Csv $newest.FullName -Delimiter "`t")
        $done = $rows.Count; $file = $newest.Name
        $total = if ($file -like 'local-cal*') { 60 } else { $done }
        $model = ($rows | Select-Object -Last 1).model
        $elapsed = ((Get-Date) - $newest.CreationTime).TotalSeconds
        $counts = @{}; $rows | Group-Object verdict | ForEach-Object { $counts[$_.Name] = $_.Count }
        $recent = $rows | Select-Object -Last 6 | ForEach-Object { '{0,-8} {1}  {2} | {3}' -f $_.verdict, $_.score, $_.company, $_.title }
        $state = if ($done -ge $total) { 'finished' } else { 'running' }
        $stale = ((Get-Date) - $newest.LastWriteTime).TotalMinutes -gt 10
    } else { Clear-Host; 'No local quick-check run found yet.'; Start-Sleep 5; continue }

    $frac = if ($total -gt 0) { [Math]::Min(1, $done / $total) } else { 0 }
    $per = if ($done -gt 0) { $elapsed / $done } else { 0 }
    $eta = ($total - $done) * $per
    $get = { param($k) if ($counts.$k) { $counts.$k } elseif ($counts[$k]) { $counts[$k] } else { 0 } }

    Clear-Host
    Write-Host ''
    Write-Host '  career-ops  -  local quick-check (free, runs on this laptop)' -ForegroundColor Cyan
    Write-Host ("  model: {0}    file: {1}" -f $model, $file) -ForegroundColor DarkGray
    Write-Host ''
    Write-Host ('  [' + (Bar $frac 50) + ']  ') -NoNewline -ForegroundColor Green
    Write-Host ('{0,3:N0}%   {1} / {2} jobs' -f ($frac * 100), $done, $total)
    Write-Host ''
    Write-Host ('  PASS {0}' -f (& $get 'PASS')) -ForegroundColor Green -NoNewline
    Write-Host ('    MARGINAL {0}' -f (& $get 'MARGINAL')) -ForegroundColor Yellow -NoNewline
    Write-Host ('    FAIL {0}' -f (& $get 'FAIL')) -ForegroundColor Red -NoNewline
    Write-Host ('    SKIP {0}    ERROR {1}' -f (& $get 'SKIP'), (& $get 'ERROR')) -ForegroundColor DarkGray
    Write-Host ''
    Write-Host ('  elapsed {0}    speed {1:N0} s/job    time left ~{2}' -f (Fmt $elapsed), $per, (Fmt $eta))
    if ($state -eq 'finished' -or $done -ge $total) { Write-Host '  FINISHED' -ForegroundColor Green }
    elseif ($stale) { Write-Host '  (no new result for 10+ min - the run may have stopped)' -ForegroundColor Yellow }
    Write-Host ''
    Write-Host '  latest:' -ForegroundColor DarkGray
    foreach ($l in $recent) { Write-Host ('   ' + ($l.Substring(0, [Math]::Min(100, $l.Length)))) }
    Write-Host ''
    Write-Host '  (refreshes every 5 s - closing this window does not stop the run)' -ForegroundColor DarkGray
    Start-Sleep 5
}

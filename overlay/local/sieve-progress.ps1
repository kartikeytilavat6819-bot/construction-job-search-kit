# Live progress window for the job sieve (local/sieve.py). Reads data\sieve\progress.json, written after every job.
# Close the window any time - it doesn't affect the run.
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path $PSScriptRoot -Parent
$json = Join-Path $root 'data\sieve\progress.json'
$host.UI.RawUI.WindowTitle = 'career-ops - job sieve progress'

function Fmt([double]$sec) {
    if ($sec -le 0 -or [double]::IsNaN($sec) -or [double]::IsInfinity($sec)) { return '--' }
    $t = [TimeSpan]::FromSeconds($sec)
    if ($t.TotalHours -ge 1) { return ('{0}h {1:D2}m' -f [int][Math]::Floor($t.TotalHours), $t.Minutes) }
    return ('{0}m {1:D2}s' -f $t.Minutes, $t.Seconds)
}

while ($true) {
    Clear-Host
    $p = $null
    if (Test-Path $json) { $p = Get-Content $json -Raw | ConvertFrom-Json }
    $backend = if ($p -and $p.backend) { $p.backend } else { 'rules only (no AI model)' }
    Write-Host ("JOB SIEVE  (free - AI model: {0})" -f $backend) -ForegroundColor DarkYellow
    Write-Host ''
    if ($p) {
        $now = (Get-Date).ToUniversalTime().Subtract([DateTime]'1970-01-01').TotalSeconds
        $done = [int]$p.done; $total = [int]$p.total
        if ($total -gt 0) {
            $frac = $done / $total
            $fill = [Math]::Round($frac * 40)
            Write-Host ('[' + ('#' * $fill) + ('-' * (40 - $fill)) + ']') -NoNewline
            Write-Host (' {0}/{1} jobs through the AI stages ({2:P0})' -f $done, $total, $frac)
            Write-Host ('elapsed {0}   about {1} left   {2:N0} s/job' -f (Fmt ($now - $p.started)), (Fmt (($total - $done) * $p.sec_per_job)), $p.sec_per_job)
        } else {
            Write-Host 'Rules-only run (stages S1-S4).'
        }
        Write-Host ''
        $c = $p.counts
        Write-Host ('GOLD {0}' -f [int]$c.GOLD) -ForegroundColor Green -NoNewline
        Write-Host ('   SILVER {0}' -f [int]$c.SILVER) -ForegroundColor Yellow -NoNewline
        Write-Host ('   REJECT {0}   NO_JD {1}   waiting {2}' -f [int]$c.REJECT, [int]$c.NO_JD, [int]$c.PENDING) -ForegroundColor Gray
        Write-Host ''
        if ($p.recent) {
            Write-Host 'Latest:'
            foreach ($r in $p.recent) {
                $col = if ($r -like 'GOLD*') { 'Green' } elseif ($r -like 'SILVER*') { 'Yellow' } else { 'DarkGray' }
                Write-Host "  $r" -ForegroundColor $col
            }
            Write-Host ''
        }
        if ($p.state -eq 'finished') { Write-Host 'Finished. Open the EVERY JOB tab at http://127.0.0.1:3000/pipeline' -ForegroundColor Green }
        elseif (($now - $p.updated) -gt 900) { Write-Host 'No update for 15+ minutes - the run may have stopped. Re-run "Run job sieve.cmd" to continue.' -ForegroundColor Red }
    } else {
        Write-Host 'Not started yet (or still downloading job descriptions). Double-click "Run job sieve.cmd" in the career-ops folder.'
    }
    Start-Sleep 10
}

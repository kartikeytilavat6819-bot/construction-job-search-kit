# Runs the job sieve (local/sieve.py) in the background: free; downloads missing JDs (no AI tokens).
# Without an AI model it runs rules-only; with OpenRouter free models or a local Ollama it also runs the AI stages
# (slower). Resumable: run it again and it continues where it stopped (AI answers are cached in
# data\sieve\cache.jsonl). Watch it with "Watch sieve progress.cmd" in the career-ops folder.
# Results show on the website's EVERY JOB tab.
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
$env:PYTHONIOENCODING = 'utf-8'
$log = Join-Path $root ('data\logs\sieve-' + (Get-Date -Format 'yyyy-MM-dd_HHmm') + '.log')
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null

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

# keep the PC awake while this runs (ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
Add-Type -Namespace W -Name P -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
[W.P]::SetThreadExecutionState([uint32]'0x80000001') | Out-Null
python local/sieve.py --fetch *>> $log
# tick rejected rows off the inbox (Pending) so it shows only jobs still worth a look
python local/sieve_clean_pending.py *>> $log
[W.P]::SetThreadExecutionState([uint32]'0x80000000') | Out-Null

$summary = (Select-String -Path $log -Pattern '^Sieve:' | Select-Object -Last 1).Line
if (-not $summary) { $summary = "The sieve stopped early - see $log." }
Notify 'career-ops: job sieve finished' ("$summary  Open the EVERY JOB tab at http://127.0.0.1:3000/pipeline")

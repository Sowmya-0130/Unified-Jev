# Per-file pytest with hard wall-clock kill (Cycle 27a).
param(
    [int]$WallSeconds = $(if ($env:TEST_FILE_WALL_S) { [int]$env:TEST_FILE_WALL_S } else { 300 })
)

Set-Location $PSScriptRoot\..

$logDir = ".loop\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$pytestTimeout = 180
if ($env:PYTEST_TIMEOUT_S) { $pytestTimeout = [int]$env:PYTEST_TIMEOUT_S }

$env:PYTHONFAULTHANDLER = "1"
$env:AURIX_BOTH_STUB = "1"

$files = Get-ChildItem -Path "tests" -Filter "test_*.py" -File | Sort-Object Name -Unique
$rows = @()

function Get-PythonProcs {
    Get-CimInstance Win32_Process -Filter "name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*Unified-SingleDB*" -or $_.CommandLine -like "*pytest*" } |
        Select-Object ProcessId, @{n = "Cmd"; e = { ($_.CommandLine).Substring(0, [Math]::Min(120, ($_.CommandLine).Length)) } }
}

Write-Host "=== run_tests.ps1 wall=${WallSeconds}s pytest-timeout=${pytestTimeout}s files=$($files.Count) ===" -ForegroundColor Cyan

foreach ($f in $files) {
    $rel = $f.FullName.Substring((Get-Location).Path.Length + 1) -replace '\\', '/'
    $logName = ($f.BaseName + ".txt")
    $logPath = Join-Path $logDir $logName
    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    $markExpr = if ($env:RUN_LIVE_TESTS) { "" } else { '-m "not live and not groupchat_legacy"' }
    $argLine = @(
        "-m pytest `"$rel`" -q --tb=line --durations=15",
        "--timeout=$pytestTimeout --timeout-method=thread",
        $markExpr
    ) -join " "

    $p = Start-Process -FilePath "python" -ArgumentList $argLine -PassThru -NoNewWindow `
        -RedirectStandardOutput $logPath -RedirectStandardError "${logPath}.err"
    $deadline = (Get-Date).AddSeconds($WallSeconds)
    $hung = $false

    while (-not $p.HasExited) {
        if ((Get-Date) -gt $deadline) {
            $hung = $true
            try { taskkill /PID $p.Id /T /F 2>&1 | Out-Null } catch { }
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $p.HasExited) {
        $p.WaitForExit(120000)
    }
    if (-not $p.HasExited) {
        $hung = $true
        try { taskkill /PID $p.Id /T /F 2>&1 | Out-Null } catch { }
    }

    $sw.Stop()
    $sec = [math]::Round($sw.Elapsed.TotalSeconds, 1)
    $passed = "-"
    $failed = "-"
    $exit = "?"
    if ($hung) {
        $exit = "HUNG"
    }

    if (-not $hung) {
        $tail = @()
        if (Test-Path $logPath) { $tail = Get-Content $logPath -Tail 8 -ErrorAction SilentlyContinue }
        $summary = ($tail | Where-Object { $_ -match 'passed|failed|error|xfailed|deselected|skipped' }) | Select-Object -Last 1
        if ($summary -match '(\d+) passed') { $passed = $Matches[1] }
        if ($summary -match '(\d+) failed') { $failed = $Matches[1] }
        elseif ($summary -match 'deselected' -and $summary -notmatch 'failed') {
            $failed = "0"
            if ($passed -eq "-") { $passed = "0" }
        }
        elseif ($summary -match '(\d+) passed' -and $summary -notmatch 'failed') { $failed = "0" }
        $rawExit = $p.ExitCode
        if ($null -ne $rawExit) { $exit = $rawExit }
        elseif ($failed -eq "0") { $exit = 0 }
        elseif ($failed -eq "-") { $exit = 0 }
        if ($exit -ne 0 -and $failed -eq "-") { $failed = "?" }
    }
    else {
        Add-Content -Path $logPath -Value "`nHUNG: wall ${WallSeconds}s exceeded — process tree killed."
        $failed = "HUNG"
    }

    $rows += [pscustomobject]@{ File = $f.Name; Passed = $passed; Failed = $failed; Hung = $(if ($hung) { "yes" } else { "" }); Sec = $sec; Exit = $exit }
    Write-Host ("{0,-40} pass={1} fail={2} hung={3} {4}s exit={5}" -f $f.Name, $passed, $failed, $(if ($hung) { "Y" } else { "" }), $sec, $exit)
}

Write-Host ""
Write-Host "| File | passed | failed | hung | sec |" -ForegroundColor Yellow
foreach ($r in $rows) {
    Write-Host ("| {0} | {1} | {2} | {3} | {4} |" -f $r.File, $r.Passed, $r.Failed, $r.Hung, $r.Sec)
}

$procs = Get-PythonProcs
Write-Host "`n=== python processes (Unified-SingleDB/pytest) ===" -ForegroundColor Yellow
if (-not $procs) { Write-Host "(none)" } else { $procs | Format-Table -AutoSize }

$anyFail = @($rows | Where-Object { $_.Hung -eq "yes" -or ($_.Failed -notmatch '^(\-|0)?$') }).Count
if ($anyFail -gt 0) { exit 1 }
exit 0
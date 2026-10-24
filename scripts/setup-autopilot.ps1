param(
    [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [switch]$SkipSchedule
)
$ErrorActionPreference = "Stop"
$RepoPath = (Resolve-Path $RepoPath).Path
$Top = (git -C $RepoPath rev-parse --show-toplevel).Trim()
if ((Resolve-Path $Top).Path -ne $RepoPath) { throw "RepoPath must be the repository root." }
$Branch = (git -C $RepoPath branch --show-current).Trim()
if ($Branch -eq "main" -or $Branch -eq "master") { throw "Refusing to configure from a protected main branch." }
$Status = git -C $RepoPath status --porcelain
if ($Status) { throw "Runner worktree must be clean before setup; no files were changed by this script." }
$Remote = (git -C $RepoPath remote get-url origin).Trim()
if ($Remote -notlike "*Sunset-Sunrise-Sun/competition-part-work*" -or $Remote -like "*yky666/ai_health_assistant*") {
    throw "origin must point to Sunset-Sunrise-Sun/competition-part-work, not the upstream project."
}

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "GitHub CLI is missing and winget is unavailable. Install GitHub CLI, then rerun this script."
    }
    winget install --id GitHub.cli -e --source winget --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw "GitHub CLI installation failed." }
    $GhInstall = Join-Path $env:ProgramFiles "GitHub CLI"
    if (Test-Path (Join-Path $GhInstall "gh.exe")) { $env:PATH = "$GhInstall;$env:PATH" }
}
if (-not (Get-Command node -ErrorAction SilentlyContinue) -or -not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "Node.js/npm is required to install the Codex CLI reviewer."
}
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    npm install --global @openai/codex
    if ($LASTEXITCODE -ne 0) { throw "Codex CLI installation failed." }
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw "gh is still not available in PATH; open a new PowerShell and rerun setup." }
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) { throw "codex is still not available in PATH; open a new PowerShell and rerun setup." }

Write-Warning "For unattended DSH headless work, the runner sets DSH_PERMISSION_MODE=danger-full-access only for the DSH child process. This does not change global Harness settings, but it grants that process full access to files available to your Windows user. Prompt instructions are not a security boundary."
$PermissionConfirmation = Read-Host "Type YES to accept DSH full-access mode for this local runner"
if ($PermissionConfirmation -cne "YES") { throw "Full-access mode was not accepted; setup stopped before preflight or scheduling." }

& gh auth status --hostname github.com
if ($LASTEXITCODE -ne 0) {
    Write-Host "Complete the one-time GitHub browser login. No token will be pasted into chat or written to the repository."
    & gh auth login --hostname github.com --web --git-protocol https
    if ($LASTEXITCODE -ne 0) { throw "GitHub CLI login did not complete." }
}
& gh auth setup-git
if ($LASTEXITCODE -ne 0) { throw "Could not configure Git to use the GitHub CLI credential store." }

& codex login status
if ($LASTEXITCODE -ne 0) {
    Write-Host "Complete the one-time Codex login using your ChatGPT account in the browser."
    & codex login
    if ($LASTEXITCODE -ne 0) { throw "Codex login did not complete." }
}

$DshCli = Join-Path $env:LOCALAPPDATA "Programs\DeepSeek Harness\resources\runtime\cli\bin\dsh.cmd"
if (-not (Test-Path $DshCli)) { throw "DSH CLI was not found at $DshCli. Install/repair the Harness CLI first." }
$Version = (& $DshCli --version 2>&1 | Out-String).Trim()
Write-Host "Detected DSH CLI: $Version"

$WorkspacesRoot = Split-Path $RepoPath -Parent
$ProjectRoot = Split-Path $WorkspacesRoot -Parent
$TaskRoot = Join-Path $WorkspacesRoot "autopilot-task-worktrees"
$LogRoot = Join-Path $ProjectRoot "outputs\autopilot-runner"
$DbPath = Join-Path $LogRoot "autopilot.sqlite3"
$ConfigRoot = Join-Path $ProjectRoot "config"
$ConfigPath = Join-Path $ConfigRoot "autopilot.local.ps1"
New-Item -ItemType Directory -Force -Path $TaskRoot, $LogRoot, $ConfigRoot | Out-Null

function Quote-Ps([string]$Value) { return "'" + $Value.Replace("'", "''") + "'" }
$Config = @(
    ('$AutopilotRepoPath = ' + (Quote-Ps $RepoPath)),
    ('$AutopilotTaskRoot = ' + (Quote-Ps $TaskRoot)),
    ('$AutopilotLogRoot = ' + (Quote-Ps $LogRoot)),
    ('$AutopilotDbPath = ' + (Quote-Ps $DbPath)),
    ('$AutopilotDshCli = ' + (Quote-Ps $DshCli)),
    ('$AutopilotDshProfile = ' + (Quote-Ps "headless")),
    ('$AutopilotGithubRepo = ' + (Quote-Ps "Sunset-Sunrise-Sun/competition-part-work")),
    ('$AutopilotBaseBranch = ' + (Quote-Ps "wjy/three-day-delivery"))
)
Set-Content -Path $ConfigPath -Value $Config -Encoding UTF8

$env:AUTOPILOT_GITHUB_REPO = "Sunset-Sunrise-Sun/competition-part-work"
$env:AUTOPILOT_BASE_BRANCH = "wjy/three-day-delivery"
$env:AUTOPILOT_REPO_PATH = $RepoPath
$env:AUTOPILOT_TASK_ROOT = $TaskRoot
$env:AUTOPILOT_LOG_ROOT = $LogRoot
$env:AUTOPILOT_DB_PATH = $DbPath
$env:AUTOPILOT_DSH_CLI = $DshCli
$env:AUTOPILOT_DSH_PROFILE = "headless"

Write-Host "Running a safe preflight in a disposable temporary repository. This must pass before scheduling."
Push-Location $RepoPath
try {
    & python -m autopilot.runner --preflight --repo-path $RepoPath --task-root $TaskRoot --log-root $LogRoot --db $DbPath --dsh-cli $DshCli --repo $env:AUTOPILOT_GITHUB_REPO --base-branch $env:AUTOPILOT_BASE_BRANCH
    if ($LASTEXITCODE -ne 0) {
        throw "Preflight failed. The scheduled task was not registered. Review the diagnostic above and rerun setup."
    }
}
finally { Pop-Location }

# Issues with this explicit title prefix are queued only after all preflight checks pass.
# Existing agent status labels are respected, so completed/paused issues are never re-queued.
$QueueOutput = (& gh issue list --repo "Sunset-Sunrise-Sun/competition-part-work" --state open --limit 100 --json number,title,labels | Out-String)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect pending task queue after preflight." }
$QueueIssues = @($QueueOutput | ConvertFrom-Json)
$StatusLabels = @("agent:ready", "agent:working", "agent:review", "agent:changes-requested", "agent:done", "agent:needs-owner")
foreach ($Issue in $QueueIssues) {
    if (-not $Issue.title.StartsWith("[AUTOPILOT-QUEUE]", [StringComparison]::Ordinal)) { continue }
    $IssueLabelNames = @($Issue.labels | ForEach-Object { $_.name })
    $ExistingStatus = @($IssueLabelNames | Where-Object { $_ -in $StatusLabels })
    if ($ExistingStatus.Count -eq 0) {
        & gh issue edit $Issue.number --repo "Sunset-Sunrise-Sun/competition-part-work" --add-label "agent:ready"
        if ($LASTEXITCODE -ne 0) { throw "Could not activate queued issue #$($Issue.number)." }
        Write-Host "Queued issue #$($Issue.number) after successful preflight."
    }
}

if (-not $SkipSchedule) {
    $TaskName = "LocalFitAutopilot"
    $PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $Action = New-ScheduledTaskAction -Execute $PowerShell -Argument ('-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $RepoPath "scripts\run-autopilot.ps1") + '"')
    $UserId = "$env:USERDOMAIN\$env:USERNAME"
    $Trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
    $Principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited
    $Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -WakeToRun
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description "LocalFit local autonomous coding runner; no merge or upstream push." -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Scheduled task registered and started: $TaskName"
    Write-Host "Keep this Windows user session logged in and the PC awake. Logs: $LogRoot"
}
else {
    Write-Host "Preflight passed. Scheduling was skipped as requested."
}

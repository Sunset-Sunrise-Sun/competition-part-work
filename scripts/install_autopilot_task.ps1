param(
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,
    [string]$TaskName = "LocalFitAutopilot",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task: $TaskName"
    exit 0
}

$resolvedRoot = (Resolve-Path $RepoRoot).Path
$pythonCommand = Get-Command python -ErrorAction Stop
$pythonPath = $pythonCommand.Source
$dbPath = Join-Path $resolvedRoot "data\autopilot.sqlite3"

# Secrets are intentionally not embedded in this task action. Prefer the
# authenticated GitHub CLI credential store; a fine-grained token may also be
# supplied through the user's GITHUB_TOKEN environment variable.
$required = @(
    "AUTOPILOT_GITHUB_ENABLED",
    "AUTOPILOT_DSH_ENABLED",
    "AUTOPILOT_REVIEW_ENABLED",
    "AUTOPILOT_GITHUB_REPOSITORY",
    "AUTOPILOT_GITHUB_BASE_BRANCH"
)
$missing = @()
foreach ($name in $required) {
    $value = [Environment]::GetEnvironmentVariable($name, "User")
    if ([string]::IsNullOrWhiteSpace($value)) {
        $missing += $name
    }
}
if ($missing.Count -gt 0) {
    throw ("Missing user environment variables: " + ($missing -join ", "))
}
foreach ($name in @("AUTOPILOT_GITHUB_ENABLED", "AUTOPILOT_DSH_ENABLED", "AUTOPILOT_REVIEW_ENABLED")) {
    if ([Environment]::GetEnvironmentVariable($name, "User") -ne "1") {
        throw ("Set " + $name + "=1 in the user's environment before installing the task.")
    }
}
$githubToken = [Environment]::GetEnvironmentVariable("GITHUB_TOKEN", "User")
$ghToken = [Environment]::GetEnvironmentVariable("GH_TOKEN", "User")
if ([string]::IsNullOrWhiteSpace($githubToken) -and [string]::IsNullOrWhiteSpace($ghToken)) {
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if ($null -eq $gh) {
        throw "Configure GITHUB_TOKEN/GH_TOKEN in the user environment or authenticate the GitHub CLI with 'gh auth login'."
    }
    & $gh.Source auth status --hostname github.com *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub CLI is not authenticated. Run 'gh auth login' first."
    }
}

$arguments = '-m autopilot.daemon --repo-root "' + $resolvedRoot + '" --db "' + $dbPath + '"'
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $arguments -WorkingDirectory $resolvedRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -ExecutionTimeLimit (New-TimeSpan -Hours 12)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Opt-in LocalFit agent task loop; no automatic merge."

Write-Host "Installed scheduled task: $TaskName"
Write-Host "It starts at user logon and runs with your user permissions."
Write-Host ('To remove it: .\scripts\install_autopilot_task.ps1 -RepoRoot "' + $resolvedRoot + '" -TaskName "' + $TaskName + '" -Remove')
Write-Host ('Start it manually with: Start-ScheduledTask -TaskName "' + $TaskName + '"')

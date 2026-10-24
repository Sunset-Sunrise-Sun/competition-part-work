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

# Secrets are intentionally not embedded in this task action. Configure the
# required environment variables in the user's environment before installation.
$required = @(
    "AUTOPILOT_GITHUB_ENABLED",
    "AUTOPILOT_DSH_ENABLED",
    "AUTOPILOT_REVIEW_ENABLED",
    "GITHUB_TOKEN",
    "AUTOPILOT_GITHUB_REPOSITORY",
    "AUTOPILOT_GITHUB_BASE_BRANCH"
)
$missing = @()
foreach ($name in $required) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, "User"))) {
        $missing += $name
    }
}
if ($missing.Count -gt 0) {
    throw ("Missing user environment variables: " + ($missing -join ", ") + ". Do not put secret values in this script or the repository.")
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

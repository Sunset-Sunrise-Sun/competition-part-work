param(
    [switch]$Preflight,
    [switch]$Once,
    [switch]$Status,
    [switch]$ClearHalt
)
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WorkspaceRoot = Split-Path $RepoRoot -Parent
$ProjectRoot = Split-Path $WorkspaceRoot -Parent
$ConfigPath = Join-Path $ProjectRoot "config\autopilot.local.ps1"
if (-not (Test-Path $ConfigPath)) {
    throw "Missing local config: $ConfigPath. Run scripts/setup-autopilot.ps1 first."
}
. $ConfigPath

$env:AUTOPILOT_GITHUB_REPO = $AutopilotGithubRepo
$env:AUTOPILOT_BASE_BRANCH = $AutopilotBaseBranch
$env:AUTOPILOT_REPO_PATH = $AutopilotRepoPath
$env:AUTOPILOT_TASK_ROOT = $AutopilotTaskRoot
$env:AUTOPILOT_LOG_ROOT = $AutopilotLogRoot
$env:AUTOPILOT_DB_PATH = $AutopilotDbPath
$env:AUTOPILOT_DSH_CLI = $AutopilotDshCli
$env:AUTOPILOT_DSH_PROFILE = $AutopilotDshProfile
$env:AUTOPILOT_CODEX_CLI = "codex"

Push-Location $RepoRoot
try {
    $Args = @(
        "-m", "autopilot.runner",
        "--repo", $AutopilotGithubRepo,
        "--base-branch", $AutopilotBaseBranch,
        "--repo-path", $AutopilotRepoPath,
        "--task-root", $AutopilotTaskRoot,
        "--log-root", $AutopilotLogRoot,
        "--db", $AutopilotDbPath,
        "--dsh-cli", $AutopilotDshCli,
        "--dsh-profile", $AutopilotDshProfile
    )
    if ($Preflight) { $Args += "--preflight" }
    if ($Once) { $Args += "--once" }
    if ($Status) { $Args += "--status" }
    if ($ClearHalt) { $Args += "--clear-halt" }
    & python @Args
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}

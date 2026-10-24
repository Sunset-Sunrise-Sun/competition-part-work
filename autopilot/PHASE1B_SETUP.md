# Phase 1B — Local unattended runner

Status: implementation draft. This adds a local Windows runner; it is not considered operational until the local preflight passes.

## Runtime flow

1. Poll open issues in Sunset-Sunrise-Sun/competition-part-work carrying the label agent:ready.
2. Persist each issue in SQLite using its issue number as the idempotent task identity.
3. Create or reuse an isolated task clone and a dedicated branch named agent/issue-N, based on the exact recorded SHA from wjy/three-day-delivery.
4. Invoke DeepSeek Harness headless to implement the issue. The DSH child process is not given GitHub/OpenAI/Codex environment tokens.
5. Run fixed validation commands based on changed paths. Refuse to stage environment files, credentials, logs, databases, dependency folders, runner code, or workflow files.
6. Commit and push only the dedicated agent/issue-N branch to the owner-controlled work repository, then create or update a Draft PR targeting wjy/three-day-delivery.
7. Invoke Codex CLI in read-only mode to independently review the exact head SHA. Persist the verdict and findings. Review findings are passed into the next DSH attempt.
8. A passed review marks the issue agent:done and the runner polls the next issue. Changes requested trigger another implementation/review cycle. A needs-owner result, lease loss, malformed review, or unknown error writes a local HALT marker and stops the queue.

## One-time setup

Use a clean isolated worktree of this repository, on the Phase 1B branch. Do not run setup from D:/localfit-fe-02 or from a dirty product worktree. If the runner worktree has not been created yet, run the following from the existing clean clone at D:/原子赛道/workspaces/three-day-delivery/upstream:

    git -C D:/原子赛道/workspaces/three-day-delivery/upstream fetch origin feat/autopilot-phase1b-local-runner
    git -C D:/原子赛道/workspaces/three-day-delivery/upstream worktree add --track -b feat/autopilot-phase1b-local-runner D:/原子赛道/workspaces/autopilot-runner origin/feat/autopilot-phase1b-local-runner

Then open a new PowerShell in D:/原子赛道/workspaces/autopilot-runner and run:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-autopilot.ps1

The setup script may install GitHub CLI and Codex CLI, and may open browser login flows for GitHub and Codex. These are one-time local setup steps. Authentication stays in the respective local credential stores; do not paste any token into chat, an issue, a prompt, or this repository.

Before registering the scheduled task, setup runs a preflight in a disposable temporary Git repository:
- GitHub CLI authentication and repository identity;
- access to the allowed base branch;
- DSH headless model access plus actual file-write capability inside the temporary workspace;
- Codex CLI authentication and read-only review capability.

If DSH preflight fails with a missing model credential or an approval prompt, setup stops and does not register the scheduled task. Configure the existing credential in the Harness credential store and verify the headless profile can write within its current workspace, then rerun setup. The runner intentionally does not copy a model key into environment variables or the repository.

## Queueing a task

Create a GitHub issue with a clear objective, explicit acceptance criteria, tests to run, scope boundaries, and the label agent:ready. Do not queue an issue that asks the agent to change the runner, security rules, GitHub workflows, or this setup procedure.

The initial task source is restricted to the owner-controlled work repository and the base branch wjy/three-day-delivery. Each task uses a separate agent/issue-N branch and a Draft PR. No task branch is merged automatically.

## Local files and logs

The scheduled runner stores its SQLite state, logs, validation output, task clones, and HALT marker outside the repository, under the configured D:/原子赛道 directories. Those files must not be committed.

To inspect state:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-autopilot.ps1 -Status

To stop the runner:

    Stop-ScheduledTask -TaskName LocalFitAutopilot

To resume after inspecting a blocker, remove the HALT marker explicitly:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-autopilot.ps1 -ClearHalt

Then start the scheduled task again:

    Start-ScheduledTask -TaskName LocalFitAutopilot

The scheduled task runs as the current Windows user with limited privileges and an interactive logon, so Harness credentials remain available. Keep that user session logged in and the PC awake for overnight work. If the computer sleeps, logs out, or loses network access, unattended progress pauses.

## Safety boundaries

- The runner may push only agent/issue-N branches to Sunset-Sunrise-Sun/competition-part-work.
- The only allowed PR base is wjy/three-day-delivery.
- There is no PR merge, auto-merge, main push, or push to yky666/ai_health_assistant.
- A Draft PR is evidence for review, not merge authorization.
- The first run should use one small, reversible task. Do not queue broad refactors or multiple tasks that edit the same module until the first real loop has been observed.
- The local SQLite lease protects cooperating runner instances on this machine. It is not a distributed lock across machines.
- A Codex review comment is an automated review comment, not a GitHub formal APPROVE event. Formal approval is not required for the local state machine to record the independent review result.
- The runner uses DSH for implementation and Codex CLI for review. It does not install dsh-agent-teams automatically because the installed Harness host is 0.2.1-rc.3 while the public plugin documentation's recommended host is 0.2.1-rc.2; compatibility has not been proven. See https://github.com/NanmiCoder/dsh-agent-teams.

## Validation

CI runs:
- python -m unittest discover -s autopilot/tests -t . -v
- python -m compileall -q autopilot

A green CI run validates the code package, not the local credentials or the actual DSH/Codex runtime. Operational success requires a successful local preflight and then at least two real queued tasks, one of which goes through a changes-requested/re-review cycle, without a user message between tasks.

# Autopilot — scheduler, DSH runtime and GitHub loop prototype

> 状态：**Phase 1A mock 调度器、Phase 1B opt-in DSH 执行/审查、Phase 1C GitHub Issue 领取/审核后 Draft PR 发布与前台轮询 runner 已写入独立 Draft 分支；尚未在用户 Windows 环境实跑，也未验证真实凭证。本分支新增只读 preflight。**
> 基线：Phase 1C `feat/autopilot-phase1c-github-loop`
> 工作区：`D:/原子赛道/workspaces/autopilot-preflight`（隔离 worktree）
> 分支：`feat/autopilot-preflight`

## 1. 范围

本阶段实现 Issue #3 / Phase 1A 要求的调度器骨架：

- Python 标准库 + SQLite，无第三方依赖；
- 六个任务状态：`ready`、`working`、`review`、`changes-requested`、`done`、`needs-owner`；
- SQLite 持久化的单任务状态机、全局单执行 lease、幂等键、有限重试、超时保护、崩溃恢复；
- 长执行/审查期间的后台 lease heartbeat，以及 lease generation + claim token fencing；
- `TaskSource` / `Executor` / `Reviewer` 接口 + fake/mock 实现；
- 审查结果绑定精确 `head_sha`，新提交使旧审查失效；
- 旧版 `GitHubRestAdapter` / `DshHeadlessAdapter` 占位类仍保留；新增 DSH 与 GitHub runtime adapter 均 **默认关闭**，需要显式启用；
- 两个 dummy 任务自动连续推进，其中一个发生返工并重新审查。

**不包含**：已在用户设备验收的真实 DSH/模型调用、Webhook 入站、ChatGPT API Review、已注册的常驻 Windows 任务、自动合并、默认分支推送。

## 2. 目录

```text
autopilot/
  models.py           # 状态、审查结论、任务/执行/审查数据类、合法转换
  interfaces.py       # TaskSource / Executor / Reviewer protocols
  store.py            # SQLite schema、状态机、lease、幂等、恢复
  scheduler.py        # 单槽调度循环、执行/审查编排、超时/失败暂停
  fakes.py            # FakeClock / FakeTaskSource / FakeExecutor / FakeReviewer
  redaction.py        # 日志脱敏辅助（runtime adapters 使用）
  cli.py              # status / recover 只读/恢复命令
  preflight.py        # --preflight 只读环境预检（不建库/不建 worktree/不调用模型）
  adapters/
    dsh.py             # Phase 1A DSH 占位 adapter（保留）
    dsh_runtime.py     # opt-in DSH worktree executor + diff reviewer
    github.py          # Phase 1A GitHub REST 占位 adapter（保留）
    github_runtime.py  # opt-in GitHub issue source + Draft PR publisher
  daemon.py             # foreground polling runner
  tests/                # unittest 测试
scripts/
  install_autopilot_task.ps1  # 显式安装/移除 Windows Task Scheduler task
autopilot/README.md
```

## 3. 状态机

```text
ready ──claim──> working ──execution ok──> review
  ^                  │                       │
  │                  └──retryable error──────┘（有限重试，回到 ready）
  │                                          │
  │                    changes-requested <── review: changes（≤3 轮）
  │                          │               │
  │                          └──claim──> working
  │                                          │
  └──────────── 超时/异常/审查失败/3 轮上限 ──> needs-owner

review: approved ──> done
```

- 合法转换在 `models.ALLOWED_TRANSITIONS` 中定义；非法转换抛 `InvalidTransition`，不会被静默接受。
- `needs-owner` 与 `done` 为终态；`needs-owner` 后调度循环停止，等待人工处理。
- `rework_rounds` 最多为 3：初次执行 + 最多 3 次返工；第 4 次审查仍要求修改时转 `needs-owner`。
- 执行超时、审查超时、未知异常、审查 head 不匹配、重试上限均转 `needs-owner`。

## 4. 持久化与并发

SQLite 表：

| 表 | 用途 |
| --- | --- |
| `tasks` | 任务状态、base/head SHA、轮次、attempts、错误、当前 attempt 是否已提交结果、claim token |
| `lease` | 单例全局执行 lease（owner/acquired/expires/generation） |
| `events` | `event_key` 主键的外部事件幂等记录 |
| `reviews` | 结构化审查（verdict/defects/reviewer/stale/head_sha） |
| `transitions` | 每次状态迁移审计日志 |

- 所有关键写操作使用 `BEGIN IMMEDIATE` 事务；
- 全局 lease 由 SQLite 单例行保护，两个调度器不能同时持有有效 lease；
- `claim_next` 在事务内检查 lease generation 和任务状态，避免重复领取；
- 每次领取生成新的 `claim_token`；执行结果/失败必须同时匹配当前 lease generation 和 claim token；
- 执行与审查写入（含失败/暂停/审查提交）都要求当前 lease generation，过期 worker 的结果会被拒绝；
- 后台 `LeaseHeartbeat` 在长执行/审查期间续租（默认 interval = min(TTL/3, 5s)）；
- `events.event_key` 唯一约束使重复 GitHub 事件/轮询被忽略；
- `reviews` 对非 stale 的 `(task_id, head_sha, reviewer)` 建唯一索引；
- 进程崩溃后 `recover()`：过期 lease 被清除；只有**当前 attempt 已提交结果**的 `working` 任务进入 `review`；返工被中断（旧 head 仍存在但当前 attempt 未提交）会回到 `ready` 重新执行，而不是错误地审查旧 head。

## 5. Interfaces 与 fake/mock

```python
TaskSource.next_ready() -> TaskSpec | None
Executor.execute(task, attempt, workspace, timeout_seconds) -> ExecutionResult
Reviewer.review(task, head_sha, timeout_seconds) -> ReviewResult
ApprovedPublisher.publish_approved(task, review, execution) -> Draft PR URL
TaskResultNotifier.on_task_result(task, result) -> None
```

- `FakeTaskSource`：按顺序发放任务；重复任务由 `enqueue_task` 幂等吸收。
- `FakeExecutor`：按脚本返回 head SHA 或抛异常/超时；只记录调用，不触碰真实系统。
- `FakeReviewer`：按 `(task_id, head_sha)` 返回结构化 verdict；旧 head 的审查无法通过。
- `FakeClock`：测试中无真实等待。

Runtime adapter 状态：

- `DshHeadlessAdapter`：Phase 1A 占位类仍保留，不执行真实命令。
- `DshWorktreeExecutor`：新增的 opt-in 执行器；要求 `AUTOPILOT_DSH_ENABLED=1`（或构造时显式启用）以及本机可用的 `dsh` CLI。每个任务使用独立 Git worktree，校验 base/head SHA，从 DSH 子进程环境中移除常见 API key/token/secret/password、云凭证、GitHub token 与 SSH agent 变量，并隔离 Git/GH CLI 配置；拒绝秘密文件、数据目录、GitHub workflows 与符号链接变更，监督进程负责提交本地分支；不 push。DSH 必须使用独立 profile 管理模型认证；若 CLI 依赖环境变量中的 API key，本执行路径会将其移除而导致启动失败，不应为图方便重新暴露密钥。
- `DshDiffReviewer`：独立启动一次 headless 调用，只把脱敏后的精确 base..head patch 传给审查器，要求返回绑定 head SHA 的结构化 JSON；默认由 `AUTOPILOT_REVIEW_ENABLED=1` 显式启用。
- `GitHubRestAdapter`：仍是 fail-closed 占位类；新增 `GitHubIssueAdapter` 轮询带 `agent:ready` 标签的 Issues，审查通过后只推送 `autopilot/*` 分支并创建 Draft PR；不合并。
- `python -m autopilot.daemon`：前台轮询 runner，要求显式启用 GitHub/DSH/Review；发布失败不会把任务标记为 done。
- DSH 子进程超时或 lease 丢失时会尝试终止进程树；CI 使用 fake CLI 和 mock GitHub API 验证控制流，真实 Windows/DSH/Token 仍未验收。

## 6. 配置

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| SQLite 路径 | `data/autopilot.sqlite3`（CLI） | 每个隔离工作区独立 |
| `max_attempts` | 2 | 同阶段连续执行失败/崩溃重试上限 |
| `max_rework_rounds` | 3 | 最多 3 轮返工 |
| `lease_ttl_seconds` | 60 | 全局 lease 过期时间 |
| `lease_heartbeat_enabled` | true | 长执行/审查期间后台续租开关（测试可关闭以验证 fencing） |
| `execution_timeout_seconds` | 300 | 执行超时（adapter/执行器负责落地） |
| `review_timeout_seconds` | 60 | 审查超时 |
| `max_steps_per_run` | 50 | 单次 `run_until_idle` 上限，防止无限循环 |

测试不会读取真实 GitHub/DSH 凭证；运行时按 `GITHUB_TOKEN`、`GH_TOKEN`、已登录的 GitHub CLI、固定 `github.com` 的 Git Credential Helper（只读 `git credential fill`）顺序取得发布凭证；不在仓库中创建 `.env`，不记录凭证值。

## 7. 启动 / 停止

当前有前台 runner 和 Windows Task Scheduler 安装脚本，但**尚未在你的电脑上启动或注册**。先手动执行一次 smoke test，再决定是否安装常驻任务。

```powershell
cd D:\原子赛道\workspaces\autopilot-preflight

# 只读查看任务/lease 状态
python -m autopilot.cli --db data/autopilot.sqlite3 status

# 崩溃后恢复过期 lease / working 任务
python -m autopilot.cli --db data/autopilot.sqlite3 recover
```

前台 runner 已接通代码路径：GitHub Issue（`agent:ready`）→ SQLite 队列 → 隔离 worktree 中的 DSH → 独立 DSH diff review → 审查通过后推送专用分支并创建 Draft PR → 回写 Issue 标签/评论。此链路的代码已提交到 Draft 分支，但真实凭证、模型调用和 Windows 任务尚未实跑验收。

## 8. Phase 1C — 首次运行与 Windows 任务

先在独立工作区切到 `feat/autopilot-phase1c-github-loop`，安装好 Python、Git 和 DSH CLI。GitHub 端只会领取你手动添加 `agent:ready` 标签的开放 Issue。

在 PowerShell 当前会话中设置运行开关与目标仓库/基线分支（不要把 Token 粘贴到仓库文件）：

```powershell
$env:AUTOPILOT_GITHUB_ENABLED = "1"
$env:AUTOPILOT_DSH_ENABLED = "1"
$env:AUTOPILOT_REVIEW_ENABLED = "1"
$env:AUTOPILOT_GITHUB_REPOSITORY = "OWNER/REPOSITORY"
$env:AUTOPILOT_GITHUB_BASE_BRANCH = "YOUR_WORKING_BRANCH"

# 优先使用 GITHUB_TOKEN / GH_TOKEN，其次已登录的 GitHub CLI；最后回退到固定 github.com 的 Git Credential Helper（非交互只读 fill）。
gh auth login

# 先跑一次，不安装常驻任务
python -m autopilot.daemon --repo-root . --db data/autopilot.sqlite3 --once
```

Token 至少需要目标仓库的 Contents（读写）、Issues（读写）、Pull requests（读写）与 Metadata（读取）权限。建议用只授权单个仓库的 fine-grained token；不要使用组织/个人全权限凭证。

只有一次运行成功、确认 Draft PR 和 Issue 标签/评论均符合预期后，再安装登录触发的 Windows 任务。安装脚本读取的是 **Windows 用户级环境变量**，不是仅存在于当前 PowerShell 窗口的 `$env:` 值；请先把运行开关和目标配置保存到当前用户环境（不需要保存 Token）：

```powershell
[Environment]::SetEnvironmentVariable("AUTOPILOT_GITHUB_ENABLED", "1", "User")
[Environment]::SetEnvironmentVariable("AUTOPILOT_DSH_ENABLED", "1", "User")
[Environment]::SetEnvironmentVariable("AUTOPILOT_REVIEW_ENABLED", "1", "User")
[Environment]::SetEnvironmentVariable("AUTOPILOT_GITHUB_REPOSITORY", "OWNER/REPOSITORY", "User")
[Environment]::SetEnvironmentVariable("AUTOPILOT_GITHUB_BASE_BRANCH", "YOUR_WORKING_BRANCH", "User")
# 若 dsh 不在用户 PATH 中，再显式设置：
# [Environment]::SetEnvironmentVariable("AUTOPILOT_DSH_CLI", "C:\path\to\dsh.exe", "User")
```

保存后，重新打开 PowerShell 窗口，再安装任务：



```powershell
.\scripts\install_autopilot_task.ps1 -RepoRoot (Get-Location).Path
Start-ScheduledTask -TaskName "LocalFitAutopilot"
# 停止或卸载
Stop-ScheduledTask -TaskName "LocalFitAutopilot"
.\scripts\install_autopilot_task.ps1 -RepoRoot (Get-Location).Path -Remove
```

任务只在用户登录且电脑运行时执行；运行时失败会退出并由 Task Scheduler 有限重启。达到 `needs-owner` 会暂停本轮自动推进。**不自动合并任何 PR。** 首次真实运行前，请先确认本机 DSH profile 的工具权限；worktree 不是 OS 级沙箱，不能把它当作隔离恶意代码的安全边界。

## 8.1 只读预检（Preflight）

在真实冒烟测试之前先运行只读预检。它不会领取 Issue、调用 DSH/模型、创建 SQLite 数据库、创建 worktree、提交代码、写 GitHub 或注册计划任务。

```powershell
cd D:\原子赛道\workspaces\autopilot-preflight

# 人工可读报告
python -m autopilot.daemon --repo-root . --preflight

# 单对象 JSON，便于机器解析
python -m autopilot.daemon --repo-root . --preflight --json
```

检查范围：

- **配置**：`AUTOPILOT_GITHUB_ENABLED`、`AUTOPILOT_DSH_ENABLED`、`AUTOPILOT_REVIEW_ENABLED` 是否显式启用；GitHub `owner/name`、base branch 是否有效；GitHub 凭据是否可取得（不输出值）；DSH CLI 是否可解析。
- **本地环境**：`--repo-root` 是否为 Git 根目录；Python（>=3.11）、Git、DSH 入口（含 Windows `.cmd`/`.bat`→`cmd.exe`）是否满足；工作区状态、本地 base branch 是否存在（无法确认时标 warning，而不是假装通过）。Preflight 的 Git 子进程使用独立环境并设置 `GIT_OPTIONAL_LOCKS=0`，避免 `git status` 刷新写回 `.git/index`；父进程环境不被修改。
- **GitHub 连通性**：只使用现有 `GitHubIssueAdapter` 的只读 GET，检查仓库访问和 base branch 是否存在。区分权限、404/not found、网络和配置错误。**不会**创建 Issue、改标签、发评论、推分支或建 PR。
- **DSH**：只检查 CLI 文件/启动入口是否可解析；**不会**调用模型或执行代码。无法在不调用模型的情况下确认的能力标记为 `not_checked`。

输出字段：`check`、`status`（`pass`/`fail`/`warning`/`not_checked`）、`message`；JSON 还包含 `read_only`、`status`、`exit_code`、`summary` 和 `limitations`。

退出码：

| 退出码 | 含义 |
| --- | --- |
| `0` | 没有阻断项。若存在 warning/not_checked，总体为 `ready_with_warnings`，这些项**不算通过**，需人工复核。 |
| `2` | 至少一个 `fail` 阻断项；或参数组合非法（`--preflight --once`）。 |

`--preflight` 与 `--once` 互斥，组合会以退出码 2 明确拒绝；`--json` 只允许与 `--preflight` 一起使用。

预检**不能替代**真实端到端测试：只读请求不能证明 Contents/Issues/Pull-request 的写权限；不调用模型不能证明 DSH 模型凭证可用；不注册计划任务不能证明 Task Scheduler 登录触发可用。真实 DSH、GitHub 写入和 Windows 计划任务仍需单独、人工授权的冒烟测试。

## 9. 测试

```powershell
cd D:\原子赛道\workspaces\autopilot-preflight
python -m unittest discover -s autopilot/tests -t . -v
```

覆盖：

- 两个 dummy 任务自动连续推进；T1 一次返工后通过，T2 直接通过；
- 重复轮询/重复事件/重复审查不重复执行；
- 两个调度器不能同时持有有效 lease（含并发线程）；长执行期间 lease heartbeat 阻止第二调度器抢占；
- 进程崩溃后：已提交执行进入 review、不重复执行；未提交执行受 attempts 限制重试；
- 返工执行在提交新 head 前崩溃时回到 `ready` 重新执行，不会卡在旧 head 的 review；
- lease generation/claim token 防止过期 worker 提交结果、提交审查或暂停新 attempt；
- 审查绑定精确 head SHA；旧 SHA 审查不能通过；
- 三轮返工上限 → `needs-owner`；
- 执行超时、执行异常、审查超时、空 head、非法状态转换 → 安全暂停；
- 专用 CI job 会执行 `python -m unittest discover -s autopilot/tests -t . -v` 与 `python -m compileall -q autopilot`。
- 旧占位 adapter 默认关闭；新 DSH runtime 只有显式启用才会启动真实进程。测试通过 fake DSH 子进程验证工作树隔离、超时/租约丢失终止、敏感路径拦截和审查 JSON 校验；GitHub runtime 只允许推送 `autopilot/*` 专用分支并创建 Draft PR，不包含 merge、auto-merge、默认分支推送或 upstream 推送路径；
- 日志脱敏辅助函数。
- Preflight 的 GitHub/DSH 使用 fake，Git 部分另含真实临时仓库回归测试；覆盖缺配置、缺 DSH CLI、仓库无权限、base branch 不存在、网络错误、token 不出现在输出/异常、不调用正常 runner/不创建状态文件、`--preflight --once` 拒绝以及默认运行行为不变。

## 10. 日志与秘密

- 调度器只记录 task id、状态、head SHA、错误类型；不会记录环境变量值、token、cookie；
- `redaction.redact()` 对常见 API-key/token 环境变量赋值、Bearer/Basic 授权头、URL 内嵌凭证、常见原始 token 格式及 `X-Hub-Signature-256` 做掩码；
- 测试使用 `dummy-test-only` 字符串，仅验证“adapter 不执行真实动作”，不是真实凭证；
- 仓库不创建 `.env`；GitHub runtime 按 `GITHUB_TOKEN`、`GH_TOKEN`、已认证 `gh` CLI、固定 `github.com` 的 Git Credential Helper（`git credential fill`，非交互、超时、只读，不输出 helper stdout）顺序解析凭据。凭证只在运行时进程内使用，不写入仓库文件；DSH 子进程环境仍会剥离 GitHub/SSH 等无关秘密。

## 11. 已知限制

1. GitHub Issue 领取、专用分支发布与 Draft PR 创建已有实现和 mock 测试；真实 GitHub 凭证、仓库权限与远端发布仍未验收。
2. 前台 runner 与 Task Scheduler 安装脚本已实现，但尚未在用户电脑上启动/注册；没有 webhook。
3. 自动审查使用单独的 DSH headless 调用，不等同于 ChatGPT API，也不代表模型判断可靠；需人工抽查审查质量。
4. DSH 子进程支持超时/租约丢失时终止进程树；真实 Windows 进程树终止与本机 DSH 凭证链仍需现场验收。
5. 单机 SQLite；跨机器并发不在范围内。
6. 不包含 main 合并、auto-merge、总仓库推送路径；未来也必须保留王靖贻的人工授权门禁。
7. 只读 preflight 无法证明 GitHub 写权限、DSH 模型凭证或 Windows Task Scheduler 注册成功；warning/not_checked 条目必须在真实冒烟测试前人工复核。

## 12. 证据边界

本目录的测试包括 mock 调度闭环、fake DSH 子进程、mock GitHub API 和隔离 worktree 集成测试；**它们不等于在用户机器上成功调用真实 DeepSeek 模型或真实 GitHub 发布**。Phase 1C 代码已接入，但真实 DSH 凭证、Token 权限、Windows 进程终止与计划任务仍需本机验收。

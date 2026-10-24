# Autopilot — Phase 1A scheduler + Phase 1B runtime prototype

> 状态：**调度器仍以 mock 闭环验证；另新增 opt-in DSH worktree executor / diff reviewer 原型。尚未在用户 Windows 环境实跑，也未接入 GitHub 任务源、推送/PR 发布或常驻服务。**
> 基线：`wjy/three-day-delivery` @ `c788a1ad0237055c74c42b4f80d04e1860787be8`
> 工作区：`D:/原子赛道/workspaces/autopilot-mvp`（隔离 worktree）
> 分支：`feat/autopilot-scheduler-mvp`

## 1. 范围

本阶段实现 Issue #3 / Phase 1A 要求的调度器骨架：

- Python 标准库 + SQLite，无第三方依赖；
- 六个任务状态：`ready`、`working`、`review`、`changes-requested`、`done`、`needs-owner`；
- SQLite 持久化的单任务状态机、全局单执行 lease、幂等键、有限重试、超时保护、崩溃恢复；
- 长执行/审查期间的后台 lease heartbeat，以及 lease generation + claim token fencing；
- `TaskSource` / `Executor` / `Reviewer` 接口 + fake/mock 实现；
- 审查结果绑定精确 `head_sha`，新提交使旧审查失效；
- 旧版 GitHub/DSH adapter 仍为占位；新增的 DSH runtime adapter **默认关闭**，显式启用后才会调用本机 CLI；
- 两个 dummy 任务自动连续推进，其中一个发生返工并重新审查。

**不包含**：GitHub 任务读取/写入与远程发布、已在用户设备验收的真实 DSH/模型调用、Webhook 入站、ChatGPT API Review、常驻 Windows 服务、合并/main/upstream push。

## 2. 目录

```text
autopilot/
  models.py           # 状态、审查结论、任务/执行/审查数据类、合法转换
  interfaces.py       # TaskSource / Executor / Reviewer protocols
  store.py            # SQLite schema、状态机、lease、幂等、恢复
  scheduler.py        # 单槽调度循环、执行/审查编排、超时/失败暂停
  fakes.py            # FakeClock / FakeTaskSource / FakeExecutor / FakeReviewer
  redaction.py        # 日志脱敏辅助（未来 adapter 使用）
  cli.py              # status / recover 只读/恢复命令
  adapters/
    dsh.py            # Phase 1A DSH 占位 adapter（保留）
    dsh_runtime.py    # opt-in DSH worktree executor + diff reviewer
    github.py         # GitHub REST 占位 adapter（无 merge 方法）
  tests/              # unittest 测试
  README.md
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
```

- `FakeTaskSource`：按顺序发放任务；重复任务由 `enqueue_task` 幂等吸收。
- `FakeExecutor`：按脚本返回 head SHA 或抛异常/超时；只记录调用，不触碰真实系统。
- `FakeReviewer`：按 `(task_id, head_sha)` 返回结构化 verdict；旧 head 的审查无法通过。
- `FakeClock`：测试中无真实等待。

Runtime adapter 状态：

- `DshHeadlessAdapter`：Phase 1A 占位类仍保留，不执行真实命令。
- `DshWorktreeExecutor`：新增的 opt-in 执行器；要求 `AUTOPILOT_DSH_ENABLED=1`（或构造时显式启用）以及本机可用的 `dsh` CLI。每个任务使用独立 Git worktree，校验 base/head SHA，屏蔽 GitHub/SSH 发布凭证，拒绝秘密文件、数据目录、GitHub workflows 与符号链接变更，监督进程负责提交本地分支；不 push。
- `DshDiffReviewer`：独立启动一次 headless 调用，只把脱敏后的精确 base..head patch 传给审查器，要求返回绑定 head SHA 的结构化 JSON；默认由 `AUTOPILOT_REVIEW_ENABLED=1` 显式启用。
- `GitHubRestAdapter`：仍是 fail-closed 占位类；本阶段不轮询 GitHub Issues、不推送分支、不创建 PR，也不发正式 GitHub Review。
- DSH 子进程超时或 lease 丢失时会终止进程树；CI 测试验证模拟执行路径，但真实 Windows/DSH 运行仍未验收。

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

环境变量只作为未来 adapter 的开关/凭证存在性检查，本阶段测试不会读取或写入任何真实密钥，也不创建 `.env`。

## 7. 启动 / 停止

当前仍**没有常驻服务，也没有 GitHub 任务领取/发布闭环**；不要把它当作已上线无人值守系统。

```powershell
cd D:\原子赛道\workspaces\autopilot-mvp

# 只读查看任务/lease 状态
python -m autopilot.cli --db data/autopilot.sqlite3 status

# 崩溃后恢复过期 lease / working 任务
python -m autopilot.cli --db data/autopilot.sqlite3 recover
```

调度循环本身仍是库 API（`Scheduler.run_once()` / `run_until_idle()`）；Phase 1B 目前只接入可测试的本地 DSH 执行/审查原型，尚未增加常驻 runner、Windows Task Scheduler、GitHub 任务源或远程发布。本阶段“启动/停止”仍仅指运行测试或单次库调用。

## 8. 测试

```powershell
cd D:\原子赛道\workspaces\autopilot-mvp
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
- 旧占位 adapter 默认关闭；新 DSH runtime 只有显式启用才会启动真实进程。测试通过 fake DSH 子进程验证工作树隔离、超时/租约丢失终止、敏感路径拦截和审查 JSON 校验；无 GitHub push/merge/main/upstream push 路径；
- 日志脱敏辅助函数。

## 9. 日志与秘密

- 调度器只记录 task id、状态、head SHA、错误类型；不会记录环境变量值、token、cookie；
- `redaction.redact()` 对 `DEEPSEEK_API_KEY=...`、`GITHUB_TOKEN=...`、`Authorization: Bearer ...`、`X-Hub-Signature-256` 做掩码；
- 测试使用 `dummy-test-only` 字符串，仅验证“adapter 不执行真实动作”，不是真实凭证；
- 仓库不创建 `.env`，不读取本机凭证存储。

## 10. 已知限制（Phase 1A）

1. GitHub task source / push / PR publication adapter 尚未实现；当前不能领取 GitHub 任务、不能推送、不能创建 PR。
2. 没有常驻进程、Windows Task Scheduler 或 webhook；自动化循环仍未部署。
3. 自动审查使用单独的 DSH headless 调用，不等同于 ChatGPT API，也不代表模型判断可靠；需人工抽查审查质量。
4. DSH 子进程支持超时/租约丢失时终止进程树；真实 Windows 进程树终止与本机 DSH 凭证链仍需现场验收。
5. 单机 SQLite；跨机器并发不在范围内。
6. 不包含 main 合并、auto-merge、总仓库推送路径；未来也必须保留王靖贻的人工授权门禁。

## 11. 证据边界

本目录的测试包括 mock 调度闭环与对 DSH 子进程/隔离 worktree 的模拟集成测试；**它们不等于在用户机器上成功调用真实 DeepSeek 模型**。真实 DSH 运行、GitHub 任务源/写权限、远程分支与 PR 发布、常驻 runner 均尚未接入或验收。

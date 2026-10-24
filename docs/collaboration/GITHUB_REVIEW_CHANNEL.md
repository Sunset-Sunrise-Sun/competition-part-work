# GitHub 协作通道：LocalFit Agent × ChatGPT Independent Code Reviewer


> **2026-10-24 范围更新（按 Issue #1 独立复核意见）**
>
> 本仓库已从“仅协作文档”升级为独立工作仓库：
> - `main` 仍保持 README-only，不直接推送、不用于内部开发、不合并；
> - 完整上游代码基线 `be013f0` 已推送到工作分支 `wjy/three-day-delivery`（保留完整 Git 历史）；
> - 后续内部功能分支从 `wjy/three-day-delivery` 创建，功能 PR 的 base 指向该分支；
> - 首个代码迁移 PR：#4 `feat: integrate FE-BE-01 safety contract on three-day baseline`（Draft，未合并）；
> - ChatGPT Reviewer 接入后，在功能 PR 上直接发表 Review 意见并记录返工。
>
> 下方原始说明中“本仓库当前只承载协作文档与评审记录”的表述按本更新执行。
本仓库是 LocalFit Agent 的独立评审与交接仓库：代码修改说明、测试证据、ChatGPT Review 意见和返工记录
全部通过 GitHub PR 交接，不再依赖人工消息转发。

## 目的与范围

- 为 LocalFit Agent 竞赛相关改动提供可追踪的 GitHub PR 评审通道；
- ChatGPT 作为独立 Code Reviewer，在 PR 中提交 Review 评论；
- 所有者王靖贻负责最终验收与合并授权；
- 本仓库当前只承载协作文档与评审记录，不承载 LocalFit 生产代码；业务代码仍在源项目工作区开发，
  评审证据通过 PR 或 PR 评论交接（如后续需要迁移代码，另行提交迁移 PR）。

## 角色

| 角色 | 职责 |
| --- | --- |
| DeepSeek Harness（实现方） | 在功能分支开发、跑测试、创建/更新 Draft PR、在 PR 中提交证据与返工记录 |
| ChatGPT（独立 Review） | 读取 PR diff、测试证据，提交 Review 评论；不直接修改 main |
| 王靖贻（所有者） | 指定合并授权、最终验收；唯一可以授权合并到 main 的人 |

## 强制合并授权规则

1. 王靖贻是唯一有权在本项目中授权合并至 `main` 的人员。
2. ChatGPT 与 DeepSeek Harness 均无权自行合并任何 PR（包括普通合并、Squash、Rebase、Merge Queue、
   启用 Auto-merge 等）。
3. 禁止绕过分支保护或直接向 `main` 推送代码。
4. 允许在独立功能分支自主开发、推送、创建和更新 PR，并完成自动测试、Review 与返工。
5. PR 达到条件后标记为 **“已验收，等待王靖贻授权合并”**，然后继续其他不依赖合并的任务。
6. 只有王靖贻明确授权指定 PR/提交后，才可执行对应合并；授权不自动扩展到其他 PR。
7. 任何自动化工作流（包括 Actions/机器人/Agent）都必须遵守以上限制。

## 分支与 PR 流程

1. 从最新 `main` 创建隔离分支：`feat/<task-id>-<slug>`、`fix/<task-id>-<slug>` 或 `docs/...`；
2. 尽早创建 **Draft PR**，并在 PR 描述中写明：任务范围、修改点、测试命令与结果、证据路径、未覆盖项与风险；
3. CI 必须通过（当前仓库暂未配置 CI；源项目 CI：backend pytest、frontend test/build、evaluation scripts）；
4. ChatGPT 在 PR 中 Review；实现方在同一分支返工、追加提交，并逐条回复 Review 线程；
5. 达到验收条件后添加/更新状态标记 **“已验收，等待王靖贻授权合并”**；
6. 不启用 Auto-merge、不执行合并；等待所有者明确授权。

## 证据与数据规范

- PR 内记录：测试命令、结果摘要、关键日志片段、commit SHA、真实浏览器 E2E 与数据库状态的摘要；
- 大文件/截图/数据库文件不直接提交到仓库，使用 PR 评论中的证据路径或受控附件说明；
- 不提交 Token、密码、`.env`、个人视频/摄像头画面/动作关键点等敏感或个人数据；
- 测试必须是真实执行结果，禁止用 mock 测试或构建成功冒充真实浏览器 E2E。

## 当前状态

- 仓库已按所有者授权完成最小初始化：`main` 仅包含 README；本文件通过 Draft PR 引入；
- 通道 PR：见仓库当前开放 Draft PR（`docs: establish GitHub review channel with ChatGPT`）；
- ChatGPT Reviewer 接入方式待所有者配置；
- 源项目 `yky666/ai_health_assistant` 当前对本环境为只读；业务代码变更在源项目隔离工作区进行，
  评审与交接通过本通道执行。

## 变更记录

- 2026-10-24：初始化评审通道仓库与协作文档（Draft PR，未合并）。

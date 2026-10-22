# S01 数据合同与规则冻结

负责人：杨开元。当前合同 `localfit.session.v1`，规则 `localfit.rules.2026-10-22`，动作算法 `localfit.pose.2026-10-22`。这是软件接口冻结，不代表真人验收或最终参赛版本冻结。

权威文件：`shared/contract.json`（共用版本及规则阈值）、`shared/session.schema.json`（后端请求 JSON Schema）、`shared/plan_cases.json`（24 组预期）、`shared/energy_cases.json` / `daily_cases.json`（能耗/日需求）。修改 Schema 后执行 `python scripts/export_contract.py`，CI 会检查运行时 Schema 与仓库一致。

| 合同项 | 已冻结约定 |
|---|---|
| 支持范围 | 默认深蹲/开合跳；其余动作实验性；动作由用户选择，不称自动类别识别 |
| 运行模式 | browser/backend 在页面加载时选定；HTTP 失败不切换状态来源；严格资源模式默认仅同源 |
| 标识与版本 | session_id 为 1–100 个字母/数字/下划线/连字符；input_version 从 1 起严格递增；提案 ID 为 session_id:input_version |
| 版本兼容 | 缺省 schema_version 按 v1；未知版本拒绝；报告回传 schema_version 与 policy_version |
| 输入时间 | active_seconds 不含暂停；observable≤active；work/rest 必须成对、非负且和≤observable；剩余时间未知，不补造运动 |
| 计划优先级 | 不适阻断→证据不足保持→高疲劳/低完成度降量延休→多次偏差延休→保持；不自动加量 |
| 提案状态 | pending 可接受或拒绝；blocked 不可继续；同终态重复幂等；相反终态冲突；未确认不改当前训练目标 |
| 持久化 | 默认 false；明确 true 后保存；保存失败不提交内存新版本/决定，允许原版本重试 |
| 删除 | 清持久化历史及内存会话；旧提案不能确认或解释；网页清评测内存，已手动下载文件由用户管理 |
| 日需求 | 共享舍入与显式公式假设；中间性别常数、活动系数、fitness 增量均为演示参数 |
| 错误 | 后端非法 schema=422，旧版本/错误提案/终态冲突=409，当前进程不存在会话=404；存储故障返回失败并保持原状态 |

浏览器入口使用 `LocalSummary` 的完整必要字段；后端允许 Schema 中声明的默认值。联调输入应使用 `scripts/evaluate_plans.py` 中的完整规范字段；不要依靠两个语言的隐式类型转换。discomfort/persist 必须是布尔值，字符串 "false" 不合法。

执行 `python scripts/evaluate_plans.py`：同一批完整摘要分别进入真实 TypeScript `analyzeLocal` 与 Python `analyze`，比较版本、证据比例、提案全部字段、逐次记录和数值能耗。时间戳、运行模式 trace 标签及解释文案不作逐字等同要求。24 个预期同时在两端单元测试执行；API 状态机另测过期、幂等、拒绝、不适、删除与磁盘失败。

固定计划对照保留同样的不适阻断，其他情况下始终原次数+60秒休息；与自适应规则使用同一输入，报告每例理由及差异。预期来自团队规则定义，匹配率不是用户满意度、健康效果或多 Agent 优越性。现在实现的是四角色确定性工作流，无外部 LLM 依赖；不能把角色 trace 当作多模型协作收益证明。

10/24 之后如需改变字段/阈值，先更新本表、版本、共享样例及两端测试，再合并；旧评测报告保留其版本与源哈希。

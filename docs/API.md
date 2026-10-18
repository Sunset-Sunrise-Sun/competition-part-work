# API 与数据合同

后端 `http://127.0.0.1:8000`，交互式 OpenAPI `/docs`。只监听回环地址，默认单用户、单进程。不提供视频上传接口。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | /api/health | 服务状态与规则运行模式 |
| POST | /api/sessions/analyze | 分析摘要并生成待确认提案 |
| POST | /api/sessions/{id}/accept | 检查版本并接受提案 |
| POST | /api/sessions/{id}/explanation | 可选本地 LLM 解释，失败降级 |
| GET | /api/history | 读取最近 50 条已授权保存的摘要 |
| DELETE | /api/history | 删除本机保存摘要及当前内存结果 |
| POST | /api/nutrition/estimate | 示例食物与克数计算 |

## 摘要请求示例

```json
{
  "session_id": "demo-001",
  "input_version": 1,
  "exercise": "squat",
  "source": "simulation",
  "reps": 8,
  "active_seconds": 60,
  "observable_seconds": 55,
  "form_events": 1,
  "fatigue": 8,
  "discomfort": false,
  "target_reps": 12,
  "persist": false,
  "profile": {"weight_kg": 65, "experience": "beginner", "goal": "habit"}
}
```

exercise：squat/jumping_jack/pull_up/jump_rope；source：simulation/camera/video；fatigue：0–10。observable_seconds 不得大于 active_seconds。数值范围以 schema 为准。身高、体重与肌肉分布由用户填写，用于 SMPL 人体定制，不由视频推断。

可选 `rep_details`（默认空，最多 100 条）为深蹲单次记录，字段：number、start_seconds、bottom_seconds、end_seconds、descent_seconds、ascent_seconds、min_angle_degrees、rom。rom 为 within_rule/below_rule/unobservable，只代表实验幅度规则。时间为不含暂停的活动时钟；阶段差值必须一致，次数递增、不重叠且位于本组时长以内。开合跳暂不接受此字段。结果回传用于复盘、trace 与保存。

响应包含 coverage、completion、energy、proposal、trace、saved。energy 是 gross_scenario_estimate：含静息的演示假设范围，不是统计区间。proposal 状态 pending/blocked/accepted。

确认 body：`{"input_version":1}`。不存在的当前会话 404；重复／旧版本更新、旧版本确认、不适禁止继续均 409；schema 不合法 422。accept 幂等地返回已确认状态，不自动启动摄像头或运动。

## 饮食请求

```json
[{"food_id":"rice","grams":150},{"food_id":"egg","grams":50}]
```

当前 food_id：rice/egg/milk/broccoli，每次最多 100 条。响应明确 data_status=illustrative_unverified。正式食品条目必须增加数据库 ID、来源与版本。该接口当前不保存饮食历史。

## 将来 WebSocket 约定

尚未实现。实时计数不需要每帧发网络请求；未来仅将阶段摘要、用户指令和有限状态推送编排器。事件必须含 session_id、event_id、输入版本与事件时间，去重后处理。禁止未经范围评估增加原始视频上传。

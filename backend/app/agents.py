"""Typed, deterministic agent workflow baseline. No external model is required."""
from datetime import datetime, timezone
from .schemas import SessionSummary


def analyze(summary: SessionSummary) -> dict:
    trace = []

    def record(role: str, evidence: dict, decision: str):
        trace.append({"role": role, "runtime": "deterministic", "status": "completed",
                      "session_id": summary.session_id, "input_version": summary.input_version,
                      "timestamp": datetime.now(timezone.utc).isoformat(),
                      "evidence": evidence, "decision": decision})

    coverage = min(1, summary.observable_seconds / max(summary.active_seconds, 1))
    completion = min(1, summary.reps / summary.target_reps)
    rom_counts = {status: sum(rep.rom == status for rep in summary.rep_details)
                  for status in ("within_rule", "below_rule", "unobservable")}
    record("training_analyst", {"reps": summary.reps, "completion": round(completion, 3),
                               "coverage": round(coverage, 3), "form_events": summary.form_events,
                               "experimental_rom": rom_counts, "recorded_reps": len(summary.rep_details)},
           "汇总动作证据；识别覆盖率不足时不判断动作质量。")

    blocked = summary.discomfort
    low_evidence = coverage < 0.6 or summary.active_seconds < 10
    target = summary.target_reps
    rest = 60
    if blocked:
        reason = "用户报告不适：暂停训练，取消继续训练建议。"
    elif low_evidence:
        reason = "有效观察不足：保持计划，先调整机位或补充训练记录。"
    elif summary.fatigue >= 7 or completion < 0.7:
        target = max(1, round(target * 0.8))
        rest = 90
        reason = "主观疲劳较高或完成度不足，建议减少下一组目标并延长休息。"
    elif summary.form_events > 2 or rom_counts["below_rule"] > 2:
        rest = 75
        reason = "出现多次可观察偏差或未达到实验幅度，保持次数，增加休息并复核动作。"
    else:
        reason = "本次记录暂不支持增加训练量，保持计划并继续观察。"
    record("plan_adapter", {"fatigue": summary.fatigue, "discomfort": blocked,
                            "low_evidence": low_evidence}, reason)
    record("safety_gate", {"blocked": blocked, "target_reps": target, "rest_seconds": rest},
           "阻止继续训练。" if blocked else "候选计划通过预设规则，等待用户确认。")

    # Scenario assumptions, not calibrated prediction intervals or per-person measurements.
    met_low, met_high = ((3.5, 5.0) if summary.exercise == "squat" else (5.0, 8.0))
    hours = summary.active_seconds / 3600
    energy = {"low_kcal": round(met_low * summary.profile.weight_kg * hours, 1),
              "high_kcal": round(met_high * summary.profile.weight_kg * hours, 1),
              "met_low": met_low, "met_high": met_high, "kind": "gross_scenario_estimate",
              "note": "演示用 MET 假设范围，包含静息消耗；不是测量值或统计置信区间。"}
    record("reporter", {"source": summary.source, "energy": energy}, "生成可追踪摘要，不推断医疗状态。")
    return {"session_id": summary.session_id, "input_version": summary.input_version,
            "source": summary.source, "coverage": round(coverage, 3), "completion": round(completion, 3),
            "rep_details": [rep.model_dump() for rep in summary.rep_details],
            "energy": energy, "proposal": {"target_reps": target, "rest_seconds": rest,
            "reason": reason, "blocked": blocked, "status": "blocked" if blocked else "pending"},
            "trace": trace, "saved": summary.persist}

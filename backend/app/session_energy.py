"""Estimates only classified time. Unknown time is never imputed as exercise."""
import json
import math
from pathlib import Path

CATALOG = json.loads((Path(__file__).resolve().parents[2] / "shared" / "energy_catalog.json").read_text(encoding="utf-8"))


def tenth(value):
    return math.floor((value + 1e-12) * 10 + 0.5) / 10


def session_energy(exercise, weight_kg, active_seconds, observable_seconds,
                   rep_details, reps=0, work_seconds=None, rest_seconds=None):
    if not all(math.isfinite(n) for n in (weight_kg, active_seconds, observable_seconds)) or not 30 <= weight_kg <= 250 or not 0 <= observable_seconds <= active_seconds:
        raise ValueError("Invalid energy input")
    spec = CATALOG[exercise]
    explicit = work_seconds is not None or rest_seconds is not None
    if explicit and (work_seconds is None or rest_seconds is None):
        raise ValueError("Provide both work and rest durations")
    phases = sum(r.descent_seconds + r.ascent_seconds for r in rep_details if r.rom != "unobservable")
    work = work_seconds if explicit else min(phases, observable_seconds, active_seconds)
    rest = rest_seconds if explicit else 0
    if not all(math.isfinite(n) for n in (work, rest)) or work < 0 or rest < 0 or work + rest > observable_seconds + 0.001:
        raise ValueError("Classified durations exceed observed time")
    unknown = max(0, active_seconds - work - rest)
    low = (spec["work"][0] * work + spec["rest"] * rest) * weight_kg / 3600
    high = (spec["work"][1] * work + spec["rest"] * rest) * weight_kg / 3600
    basal = weight_kg * (work + rest) / 3600
    return {
        "low_kcal": tenth(low), "high_kcal": tenth(high),
        "net_low_kcal": tenth(max(0, low - basal)), "net_high_kcal": tenth(max(0, high - basal)),
        "work_seconds": tenth(work), "rest_seconds": tenth(rest), "unknown_seconds": tenth(unknown),
        "available": work + rest > 0, "met_work": spec["work"], "met_rest": spec["rest"],
        "compendium_id": spec["id"], "kind": "observed_segments_scenario",
        "note": f"仅估算已分类片段：活动 {tenth(work)} 秒、静止 {tenth(rest)} 秒、未知 {tenth(unknown)} 秒。未知未计入；活动/静止为待验证视觉规则，MET 为情景假设。总消耗包含静息，净消耗扣除已分类片段的 1 MET；不是完整训练实测值。",
    }

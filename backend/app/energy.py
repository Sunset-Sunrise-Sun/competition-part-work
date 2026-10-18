"""Session and daily energy estimates. Scenario ranges, not measured values."""
from __future__ import annotations

MET = {
    "squat": {"work": (3.5, 5.0), "rest": 1.3, "id": "02050", "label": "抗阻/徒手力量，中等"},
    "jumping_jack": {"work": (7.0, 8.3), "rest": 1.5, "id": "02022", "label": "开合跳"},
    "pull_up": {"work": (8.0, 9.8), "rest": 1.8, "id": "02054", "label": "引体向上"},
    "jump_rope": {"work": (8.8, 12.3), "rest": 1.8, "id": "15552", "label": "跳绳"},
}
PAL = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725}


def mifflin_bmr(sex: str, weight_kg: float, height_cm: float, age_years: float) -> float:
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age_years
    if sex == "male":
        return base + 5
    if sex == "female":
        return base - 161
    return base - 78


def daily_requirement(profile) -> dict:
    pal_key = getattr(profile, "activity", "light")
    pal = PAL.get(pal_key, 1.375)
    bmr = mifflin_bmr(getattr(profile, "sex", "unspecified"), profile.weight_kg,
                      getattr(profile, "height_cm", 170), getattr(profile, "age_years", 22))
    tdee = bmr * pal
    target = tdee + 200 if getattr(profile, "goal", "habit") == "fitness" else tdee
    return {
        "bmr_kcal": round(bmr),
        "tdee_kcal": round(tdee),
        "need_kcal": round(target),
        "pal": pal,
        "formula": "Mifflin-St Jeor × 活动系数",
        "note": "每日热量需求为情景估算，不是处方；健身目标按维持量上浮约 200 kcal。",
    }


def session_energy(exercise: str, weight_kg: float, active_seconds: float,
                   observable_seconds: float, rep_details: list) -> dict:
    spec = MET[exercise]
    work = 0.0
    for rep in rep_details:
        work += getattr(rep, "descent_seconds", 0) + getattr(rep, "ascent_seconds", 0)
    if work <= 0:
        work = min(active_seconds, observable_seconds * 0.7)
    work = min(work, active_seconds)
    rest = max(0.0, active_seconds - work)
    hours_w, hours_r, hours_a = work / 3600, rest / 3600, active_seconds / 3600
    low = spec["work"][0] * weight_kg * hours_w + spec["rest"] * weight_kg * hours_r
    high = spec["work"][1] * weight_kg * hours_w + spec["rest"] * weight_kg * hours_r
    rest_met = 1.0 * weight_kg * hours_a
    return {
        "low_kcal": round(low, 1),
        "high_kcal": round(high, 1),
        "net_low_kcal": round(max(0.0, low - rest_met), 1),
        "net_high_kcal": round(max(0.0, high - rest_met), 1),
        "work_seconds": round(work, 1),
        "rest_seconds": round(rest, 1),
        "met_work": spec["work"],
        "met_rest": spec["rest"],
        "compendium_id": spec["id"],
        "kind": "gross_and_net_scenario",
        "note": f"{spec['label']}（Compendium {spec['id']}）按活动/休息分段；总消耗含静息，净消耗已扣 1.0 MET。不是测量值。",
    }

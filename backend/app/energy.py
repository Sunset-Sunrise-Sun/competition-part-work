"""Session and daily energy estimates. Scenario ranges, not measured values."""
from __future__ import annotations
import math

from .catalog import MET, MET_DEFAULT
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
        "bmr_kcal": math.floor(bmr + 0.5),
        "tdee_kcal": math.floor(tdee + 0.5),
        "need_kcal": math.floor(target + 0.5),
        "pal": pal,
        "formula": "Mifflin-St Jeor × 活动系数",
        "note": "每日需求为情景估算；未指定公式性别项时使用中间常数 -78；活动系数为自评假设，健身目标 +200 kcal 为演示策略，不是个体处方。",
    }


from .session_energy import session_energy

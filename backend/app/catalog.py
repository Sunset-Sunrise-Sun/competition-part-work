from pathlib import Path
import json

EXERCISE_IDS = {
    "squat", "lunge", "side_lunge", "jumping_squat", "calf_raise", "deadlift",
    "glute_bridge", "hip_abduction", "wall_sit", "push_up", "pull_up", "dip",
    "biceps_curl", "overhead_press", "lateral_raise", "front_raise",
    "tricep_extension", "bent_over_row", "sit_up", "crunch", "plank",
    "mountain_climber", "russian_twist", "jumping_jack", "jump_rope",
    "high_knees", "running_in_place", "burpee", "boxing", "arm_circle",
}

MET = {
    "squat": {"work": (3.5, 5.0), "rest": 1.3, "id": "02050", "label": "深蹲"},
    "lunge": {"work": (3.8, 5.5), "rest": 1.4, "id": "02050", "label": "弓步"},
    "side_lunge": {"work": (3.8, 5.5), "rest": 1.4, "id": "02050", "label": "侧弓步"},
    "jumping_squat": {"work": (8.0, 10.0), "rest": 1.8, "id": "02120", "label": "跳蹲"},
    "calf_raise": {"work": (3.0, 4.0), "rest": 1.3, "id": "02101", "label": "提踵"},
    "deadlift": {"work": (5.0, 6.0), "rest": 1.5, "id": "02054", "label": "硬拉/髋铰链"},
    "glute_bridge": {"work": (3.5, 5.0), "rest": 1.3, "id": "02101", "label": "臀桥"},
    "hip_abduction": {"work": (3.0, 4.5), "rest": 1.3, "id": "02101", "label": "侧抬腿"},
    "wall_sit": {"work": (3.5, 5.0), "rest": 1.5, "id": "02050", "label": "靠墙静蹲"},
    "push_up": {"work": (6.0, 8.0), "rest": 1.6, "id": "02054", "label": "俯卧撑"},
    "pull_up": {"work": (8.0, 9.8), "rest": 1.8, "id": "02054", "label": "引体向上"},
    "dip": {"work": (8.0, 9.0), "rest": 1.7, "id": "02054", "label": "双杠臂屈伸"},
    "biceps_curl": {"work": (3.0, 5.0), "rest": 1.3, "id": "02054", "label": "弯举"},
    "overhead_press": {"work": (3.5, 6.0), "rest": 1.4, "id": "02050", "label": "推举"},
    "lateral_raise": {"work": (3.0, 4.5), "rest": 1.3, "id": "02050", "label": "侧平举"},
    "front_raise": {"work": (3.0, 4.5), "rest": 1.3, "id": "02050", "label": "前平举"},
    "tricep_extension": {"work": (3.0, 4.5), "rest": 1.3, "id": "02054", "label": "臂屈伸"},
    "bent_over_row": {"work": (4.0, 6.0), "rest": 1.4, "id": "02054", "label": "俯身划船"},
    "sit_up": {"work": (3.8, 8.0), "rest": 1.4, "id": "02171", "label": "仰卧起坐"},
    "crunch": {"work": (2.8, 3.8), "rest": 1.3, "id": "02171", "label": "卷腹"},
    "plank": {"work": (3.3, 4.5), "rest": 1.5, "id": "02171", "label": "平板支撑"},
    "mountain_climber": {"work": (8.0, 10.0), "rest": 1.7, "id": "02130", "label": "登山者"},
    "russian_twist": {"work": (3.5, 5.0), "rest": 1.3, "id": "02171", "label": "俄罗斯转体"},
    "jumping_jack": {"work": (7.0, 8.3), "rest": 1.5, "id": "02022", "label": "开合跳"},
    "jump_rope": {"work": (8.8, 12.3), "rest": 1.8, "id": "15552", "label": "跳绳"},
    "high_knees": {"work": (8.0, 10.0), "rest": 1.7, "id": "12020", "label": "高抬腿"},
    "running_in_place": {"work": (6.0, 8.0), "rest": 1.6, "id": "12020", "label": "原地跑"},
    "burpee": {"work": (8.0, 11.0), "rest": 1.8, "id": "02130", "label": "波比跳"},
    "boxing": {"work": (7.8, 10.0), "rest": 1.6, "id": "12050", "label": "空击/出拳"},
    "arm_circle": {"work": (2.8, 4.0), "rest": 1.3, "id": "02050", "label": "绕臂"},
}
MET_DEFAULT = {"work": (4.0, 6.0), "rest": 1.5, "id": "02000", "label": "一般健身活动"}

FOODS_PATH = Path(__file__).resolve().parents[2] / "frontend" / "src" / "foods.json"
FOODS = json.loads(FOODS_PATH.read_text(encoding="utf-8"))


def normalize(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch not in " \t()（）·-_/.,，。")


def score_food(query: str, food: dict) -> int:
    q = normalize(query)
    if not q:
        return 0
    names = [normalize(food["id"]), normalize(food["name"]), *[normalize(a) for a in food.get("aliases", [])]]
    if q in names:
        return 100
    if any(n.startswith(q) or q.startswith(n) for n in names if n):
        return 86
    if any(q in n or n in q for n in names if n):
        return 72
    return 0


def parse_query(query: str) -> tuple[str, float | None]:
    raw = query.strip()
    grams = None
    text = raw
    digits = ""
    if raw and raw[-1].isdigit():
        i = len(raw)
        while i and (raw[i - 1].isdigit() or raw[i - 1] in ".克gG"):
            i -= 1
        tail = raw[i:]
        num = "".join(ch for ch in tail if ch.isdigit() or ch == ".")
        if num and i >= 2:
            grams = float(num)
            text = raw[:i].strip()
    return text or raw, grams


def match_food(query: str, food_id: str = "") -> dict | None:
    if food_id:
        for food in FOODS:
            if food["id"] == food_id:
                return food
    text, _ = parse_query(query)
    ranked = sorted(((score_food(text, food), food) for food in FOODS), key=lambda x: -x[0])
    return ranked[0][1] if ranked and ranked[0][0] >= 48 else None

from pathlib import Path
from threading import RLock
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .agents import analyze
from .schemas import SessionSummary, AcceptProposal, FoodEntry
from .storage import Storage
from .local_llm import explain

ROOT = Path(__file__).resolve().parents[2]
app = FastAPI(title="LocalFit Agent", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])
storage = Storage(ROOT / "data" / "sessions.sqlite3")
reports: dict[str, dict] = {}
lock = RLock()


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0", "agent_runtime": "deterministic",
            "video_upload": False, "cloud_required": False}


@app.post("/api/sessions/analyze")
def analyze_session(summary: SessionSummary):
    if summary.observable_seconds > summary.active_seconds:
        raise HTTPException(422, "observable_seconds cannot exceed active_seconds")
    with lock:
        previous = reports.get(summary.session_id)
        if previous and summary.input_version <= previous["input_version"]:
            raise HTTPException(409, "Input version must increase for an existing session")
        report = analyze(summary)
        if summary.persist:
            storage.save(report)
        reports[summary.session_id] = report
        if len(reports) > 100:
            del reports[next(iter(reports))]
        return report


@app.post("/api/sessions/{session_id}/accept")
def accept(session_id: str, request: AcceptProposal):
    with lock:
        report = reports.get(session_id)
        if not report:
            raise HTTPException(404, "Session not found in current process")
        if request.input_version != report["input_version"]:
            raise HTTPException(409, "Stale proposal")
        if report["proposal"]["blocked"]:
            raise HTTPException(409, "Continuation blocked by discomfort report")
        report["proposal"]["status"] = "accepted"
        if report["saved"]:
            storage.save(report)
        return report


@app.post("/api/sessions/{session_id}/explanation")
async def explanation(session_id: str):
    with lock:
        report = reports.get(session_id)
        if not report:
            raise HTTPException(404, "Session not found")
        snapshot = {**report, "proposal": dict(report["proposal"])}
    try:
        message = await explain(snapshot)
        return {"text": message or snapshot["proposal"]["reason"],
                "runtime": "local_llm" if message else "deterministic", "input_version": snapshot["input_version"]}
    except Exception as error:
        # Preserve working baseline when an optional local model is unavailable.
        return {"text": snapshot["proposal"]["reason"], "runtime": "fallback",
                "input_version": snapshot["input_version"], "reason": type(error).__name__}


@app.get("/api/history")
def history():
    return storage.list()


@app.delete("/api/history")
def clear_history():
    with lock:
        storage.clear()
        reports.clear()
    return {"deleted": True}


FOODS = {"rice": ("熟米饭", 130), "egg": ("鸡蛋", 143), "milk": ("全脂牛奶", 61), "broccoli": ("西兰花", 34)}


@app.post("/api/nutrition/estimate")
def nutrition(entries: list[FoodEntry]):
    if len(entries) > 100:
        raise HTTPException(422, "Too many entries")
    items = [{"name": FOODS[x.food_id][0], "grams": x.grams,
              "kcal": round(FOODS[x.food_id][1] * x.grams / 100, 1)} for x in entries]
    return {"items": items, "total_kcal": round(sum(x["kcal"] for x in items), 1),
            "data_status": "illustrative_unverified", "note": "示例数据，尚未完成食品条目及烹饪方式核验，仅供功能演示。"}


# Mount last so explicit API and OpenAPI routes retain priority.
frontend_build = ROOT / "frontend" / "dist"
if frontend_build.is_dir():
    app.mount("/", StaticFiles(directory=frontend_build, html=True), name="frontend")

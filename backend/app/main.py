from pathlib import Path
from threading import RLock
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .agents import analyze
from .catalog import match_food, parse_query
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
    return decide(session_id, request, "accepted")


@app.post("/api/sessions/{session_id}/reject")
def reject(session_id: str, request: AcceptProposal):
    return decide(session_id, request, "rejected")


def decide(session_id: str, request: AcceptProposal, decision: str):
    with lock:
        report = reports.get(session_id)
        if not report:
            raise HTTPException(404, "Session not found in current process")
        if request.input_version != report["input_version"]:
            raise HTTPException(409, "Stale proposal")
        if request.proposal_id is not None and request.proposal_id != report["proposal"]["proposal_id"]:
            raise HTTPException(409, "Proposal identity mismatch")
        if report["proposal"]["blocked"]:
            raise HTTPException(409, "Continuation blocked by discomfort report")
        status = report["proposal"]["status"]
        if status == decision:
            return report
        if status != "pending":
            raise HTTPException(409, "Decision already finalized")
        report["proposal"]["status"] = decision
        report["proposal"]["decided_at"] = datetime.now(timezone.utc).isoformat()
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


@app.post("/api/nutrition/estimate")
def nutrition(entries: list[FoodEntry]):
    if len(entries) > 100:
        raise HTTPException(422, "Too many entries")
    items = []
    for entry in entries:
        food = match_food(entry.query, entry.food_id)
        if food is None and entry.kcal_per_100g is None:
            items.append({"name": entry.query or "未识别食物", "grams": entry.grams or 100,
                          "kcal": 0, "matched": False})
            continue
        kcal_per = entry.kcal_per_100g if entry.kcal_per_100g is not None else food["kcal"]
        _, parsed = parse_query(entry.query)
        grams = entry.grams or parsed or (food["unit_g"] if food else 100)
        items.append({
            "name": food["name"] if food else entry.query or "自定义食物",
            "food_id": food["id"] if food else None,
            "grams": grams,
            "kcal_per_100g": kcal_per,
            "kcal": round(kcal_per * grams / 100, 1),
            "matched": food is not None,
        })
    return {"items": items, "total_kcal": round(sum(x["kcal"] for x in items), 1),
            "data_status": "illustrative_unverified",
            "note": "示例食物库按名称匹配，尚未完成烹饪方式核验，仅供功能演示。"}


# Mount last so explicit API and OpenAPI routes retain priority.
frontend_build = ROOT / "frontend" / "dist"
if frontend_build.is_dir():
    app.mount("/", StaticFiles(directory=frontend_build, html=True), name="frontend")

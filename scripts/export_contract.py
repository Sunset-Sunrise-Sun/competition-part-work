"""Freeze the backend request JSON Schema for review and generated clients."""
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from app.schemas import SessionSummary

destination = root / "shared/session.schema.json"
destination.write_text(json.dumps(SessionSummary.model_json_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("Exported shared/session.schema.json")

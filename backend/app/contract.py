"""Versioned parameters shared with the browser implementation."""
import json
from pathlib import Path

CONTRACT = json.loads((Path(__file__).resolve().parents[2] / "shared" / "contract.json").read_text(encoding="utf-8"))
POLICY = CONTRACT["policy"]

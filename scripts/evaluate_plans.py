"""Reproduce browser/backend parity and a fixed-plan comparator on synthetic scenarios."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.agents import analyze
from app.schemas import SessionSummary
from app.contract import CONTRACT


def evaluate(output: Path):
    cases = json.loads((ROOT / "shared/plan_cases.json").read_text(encoding="utf-8"))
    summaries = [{"session_id": f"comparison-{i}", "input_version": 1,
        "schema_version": CONTRACT["schema_version"], "exercise": "squat", "source": "simulation",
        "reps": 12, "active_seconds": 60, "observable_seconds": 55, "form_events": 0,
        "fatigue": 4, "discomfort": False, "target_reps": 12, "profile": {"weight_kg": 65},
        **case["input"], "persist": False} for i, case in enumerate(cases)]
    with tempfile.TemporaryDirectory(prefix="localfit-contract-") as tmp:
        source, target = Path(tmp) / "inputs.json", Path(tmp) / "browser.json"
        source.write_text(json.dumps(summaries), encoding="utf-8")
        subprocess.run(["node", str(ROOT / "frontend/scripts/evaluate.mjs"), "plan", str(source), str(target)], cwd=ROOT, check=True)
        browser = json.loads(target.read_text(encoding="utf-8"))
    rows = []
    for case, raw, frontend in zip(cases, summaries, browser, strict=True):
        backend = analyze(SessionSummary(**raw))
        # Explain wording and trace timestamps/runtime differ by transport; compare the full proposal
        # and all numerical energy fields, in addition to schema, input, and evidence summaries.
        fields = ["schema_version", "policy_version", "session_id", "input_version", "source",
                  "coverage", "completion", "saved", "rep_details", "proposal"]
        differences = [key for key in fields if frontend[key] != backend[key]]
        for key, value in backend["energy"].items():
            if isinstance(value, (int, float, bool)) and frontend["energy"].get(key) != value:
                differences.append("energy." + key)
        for key in ("bmr_kcal", "tdee_kcal", "need_kcal"):
            if frontend["energy"]["daily"][key] != backend["energy"]["daily"][key]:
                differences.append("energy.daily." + key)
        actual = {key: backend["proposal"][key] for key in case["expected"]}
        fixed = {"target_reps": raw["target_reps"], "rest_seconds": 60,
                 "blocked": raw["discomfort"], "status": "blocked" if raw["discomfort"] else "pending"}
        constraints = {"no_increase": actual["target_reps"] <= raw["target_reps"],
                       "discomfort_blocks": actual["blocked"] == raw["discomfort"],
                       "requires_confirmation": actual["status"] in ("pending", "blocked")}
        rows.append({"scenario": case["name"], "input": raw, "expected": case["expected"],
                     "adaptive": actual, "fixed_with_same_discomfort_gate": fixed,
                     "adaptive_matches_expected": actual == case["expected"],
                     "fixed_matches_expected": fixed == case["expected"],
                     "cross_runtime_differences": differences, "constraints": constraints,
                     "reason": backend["proposal"]["reason"]})
    source_paths = sorted([*Path(ROOT / "backend/app").glob("*.py"),
        *Path(ROOT / "frontend/src").glob("*.ts"), *Path(ROOT / "shared").glob("*.json")])
    digest = hashlib.sha256()
    for path in source_paths:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8"))
    result = {"evidence_kind": "synthetic_rule_scenarios", "policy_version": CONTRACT["policy_version"],
              "source_sha256": digest.hexdigest(), "scenario_count": len(rows),
              "cross_runtime_agreement": sum(not r["cross_runtime_differences"] for r in rows),
              "adaptive_expected_matches": sum(r["adaptive_matches_expected"] for r in rows),
              "fixed_expected_matches": sum(r["fixed_matches_expected"] for r in rows),
              "all_constraints_pass": all(all(r["constraints"].values()) for r in rows),
              "limitation": "Scenario expectations encode our policy; this is not human efficacy or multi-agent benefit evidence.",
              "rows": rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Scenarios={len(rows)} parity={result['cross_runtime_agreement']} adaptive={result['adaptive_expected_matches']} fixed={result['fixed_expected_matches']}")
    if result["cross_runtime_agreement"] != len(rows) or result["adaptive_expected_matches"] != len(rows) or not result["all_constraints_pass"]:
        raise SystemExit("Comparison failed; inspect output differences.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / ".localrun/plan_comparison.json")
    evaluate(parser.parse_args().output)

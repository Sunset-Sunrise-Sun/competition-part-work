"""Run the repeatable software release checks; does not certify human/offline-device acceptance."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline-assets", action="store_true", help="Also require prepared model and WASM assets")
    args = parser.parse_args()
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("npm is required")
    commands = [
        ([sys.executable, "-m", "pytest", "backend/tests", "-q"], ROOT),
        ([npm, "test"], ROOT / "frontend"),
        ([npm, "run", "build"], ROOT / "frontend"),
        ([sys.executable, "scripts/evaluate_plans.py"], ROOT),
        (["node", "frontend/scripts/evaluate.mjs", "synthetic", "-", ".localrun/synthetic_replay.json"], ROOT),
    ]
    if args.offline_assets:
        commands.append(([sys.executable, "scripts/check_local_assets.py"], ROOT))
    result = {"started_at_utc": datetime.now(timezone.utc).isoformat(),
              "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "tracked_worktree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True).strip()),
              "scope": "software checks only; human trials, visual UI and whole-device offline restart pending", "checks": []}
    output = ROOT / ".localrun/release_checks.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    for command, cwd in commands:
        started = time.monotonic()
        completed = subprocess.run(command, cwd=cwd)
        result["checks"].append({"command": command, "cwd": cwd.relative_to(ROOT).as_posix(),
                                 "exit_code": completed.returncode, "seconds": round(time.monotonic() - started, 3)})
        result["passed"] = completed.returncode == 0
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if completed.returncode:
            raise SystemExit(completed.returncode)
    print("Software checks passed. Evidence: .localrun/release_checks.json")

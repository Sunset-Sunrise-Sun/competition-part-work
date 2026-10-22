"""Apply independent manual labels to a local recording. Never derives truth from predictions."""
import argparse
import json
import math
from pathlib import Path


def annotate(clips, labels):
    if len({c["clip_id"] for c in clips}) != len(clips):
        raise ValueError("Duplicate recording IDs")
    by_id = {label["clip_id"]: label for label in labels}
    if len(by_id) != len(labels) or set(by_id) != {c["clip_id"] for c in clips}:
        raise ValueError("Labels must match recording IDs exactly")
    for clip in clips:
        label = by_id[clip["clip_id"]]
        for field in ("participant_id", "scenario", "reference_reps", "count_eligible", "exclusion_reason"):
            clip[field] = label[field]
        if not label.get("annotator_id") or not label.get("reviewer_id") or label["annotator_id"] == label["reviewer_id"]:
            raise ValueError("Provide distinct annotator and reviewer IDs")
        clip["annotation"] = {key: label[key] for key in ("annotator_id", "reviewer_id")}
        clip["reference_cycles"] = label.get("reference_cycles", [])
        for field, allowed in (("quality_intervals", {"observed", "unknown"}), ("activity_intervals", {"work", "rest", "unknown"})):
            previous_end = -1
            for interval in label.get(field, []):
                start, end, value = interval["start_ms"], interval["end_ms"], interval["label"]
                if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end and start >= previous_end) or value not in allowed:
                    raise ValueError("Intervals must be ordered, disjoint, positive, with valid labels")
                previous_end = end
            key = "expected_quality" if field == "quality_intervals" else "expected_activity"
            for frame in clip["frames"]:
                frame.pop(key, None)
                for interval in label.get(field, []):
                    if interval["start_ms"] <= frame["time_ms"] < interval["end_ms"]:
                        frame[key] = interval["label"]
                        break
    return clips


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("recording", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.resolve() in (args.recording.resolve(), args.labels.resolve()):
        raise SystemExit("Choose a separate labelled output file.")
    data = annotate(json.loads(args.recording.read_text(encoding="utf-8")), json.loads(args.labels.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

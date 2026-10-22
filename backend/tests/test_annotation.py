import copy
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from annotate_replay import annotate


def inputs():
    clips = [{"clip_id": "test", "frames": [{"time_ms": i} for i in (0, 100, 200, 300)]}]
    labels = [{"clip_id": "test", "participant_id": "P01", "scenario": "occlusion",
               "reference_reps": 0, "count_eligible": False, "exclusion_reason": "occlusion",
               "annotator_id": "A", "reviewer_id": "B",
               "quality_intervals": [{"start_ms": 0, "end_ms": 100, "label": "observed"},
                                     {"start_ms": 100, "end_ms": 300, "label": "unknown"}]}]
    return clips, labels


def test_labels_are_independent_and_intervals_are_half_open():
    clips, labels = inputs()
    output = annotate(copy.deepcopy(clips), labels)[0]
    assert output["reference_reps"] == 0
    assert [f.get("expected_quality") for f in output["frames"]] == ["observed", "unknown", "unknown", None]
    assert "expected_quality" not in clips[0]["frames"][0]


@pytest.mark.parametrize("failure", ["duplicate", "missing", "same_reviewer", "overlap", "infinite"])
def test_invalid_annotations_fail(failure):
    clips, labels = inputs()
    if failure == "duplicate":
        labels.append(copy.deepcopy(labels[0]))
    elif failure == "missing":
        labels[0]["clip_id"] = "other"
    elif failure == "same_reviewer":
        labels[0]["reviewer_id"] = "A"
    elif failure == "overlap":
        labels[0]["quality_intervals"][1]["start_ms"] = 50
    else:
        labels[0]["quality_intervals"][1]["end_ms"] = float("inf")
    with pytest.raises(ValueError):
        annotate(clips, labels)

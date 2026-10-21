"""Generate original illustrative joints; no SMPL/SMPL-X weights or derivatives."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
# Hand-authored T-pose proportions for a diagram, not a fitted human body model.
joints = [
    [0,0,0], [.1,-.08,0], [-.1,-.08,0], [0,.12,0],
    [.1,-.46,0], [-.1,-.46,0], [0,.28,0], [.1,-.85,0], [-.1,-.85,0],
    [0,.42,0], [.1,-.9,.1], [-.1,-.9,.1], [0,.54,0],
    [.08,.43,0], [-.08,.43,0], [0,.68,0], [.2,.43,0], [-.2,.43,0],
    [.48,.43,0], [-.48,.43,0], [.72,.43,0], [-.72,.43,0],
    [0,.63,.05], [.035,.7,.05], [-.035,.7,.05],
]
parents = [-1,0,0,0,1,2,3,4,5,6,7,8,9,9,9,12,13,14,16,17,18,19,15,15,15]
for wrist, side in [(20,1),(21,-1)]:
    for finger in range(5):
        for segment in range(3):
            parent = wrist if segment == 0 else len(joints)-1
            joints.append([side*(.75+.025*segment),.43+(finger-2)*.015,.015*segment])
            parents.append(parent)
dirs = [[[0.0]*10 for _ in range(3)] for _ in joints]
for i, xyz in enumerate(joints):
    for axis in range(3):
        dirs[i][axis][0] = xyz[axis]*.06
    dirs[i][0][1] = xyz[0]*.025
data = dict(source="LocalFit contributors: original procedural demonstration skeleton",
            license="MIT", model="illustrative_only_not_SMPL_or_SMPLX",
            parents=parents, J_template=joints, J_shapedirs=dirs)
(ROOT/'frontend/src/body_template.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
print('Generated 55 original illustration joints; no external body-model data.')

/** Authored kinematic fixtures, deliberately NOT camera recordings or trained-model evidence. */
import type { Point } from './types';
import type { ReplayClip } from './replay';

export function fixturePose(time: number, exercise: 'squat' | 'jumping_jack'): Point[] {
  const p = Array.from({ length: 33 }, () => ({ x: 0.5, y: 0.2, visibility: 1 }));
  p[11] = { x: 0.44, y: 0.25, visibility: 1 };
  p[12] = { x: 0.56, y: 0.25, visibility: 1 };
  p[23] = { x: 0.47, y: 0.5, visibility: 1 };
  p[24] = { x: 0.53, y: 0.5, visibility: 1 };
  p[25] = { x: 0.47, y: 0.7, visibility: 1 };
  p[26] = { x: 0.53, y: 0.7, visibility: 1 };
  p[27] = { x: 0.47, y: 0.9, visibility: 1 };
  p[28] = { x: 0.53, y: 0.9, visibility: 1 };
  p[15] = { x: 0.35, y: 0.55, visibility: 1 };
  p[16] = { x: 0.65, y: 0.55, visibility: 1 };
  if (exercise === 'squat') {
    const angle = ((180 - (90 * (1 - Math.cos((time / 3000) * Math.PI * 2))) / 2) * Math.PI) / 180;
    p[23] = { x: 0.5 + Math.sin(angle) * 0.2, y: 0.6 + Math.cos(angle) * 0.2, visibility: 1 };
    p[25] = { x: 0.5, y: 0.6, visibility: 1 };
    p[27] = { x: 0.5, y: 0.9, visibility: 1 };
    p[11] = { x: p[23].x, y: p[23].y - 0.25, visibility: 1 };
  } else if (time % 1600 >= 300 && time % 1600 < 1100) {
    p[15].y = p[16].y = 0.1;
    p[27].x = 0.25;
    p[28].x = 0.75;
  }
  return p;
}

export function syntheticClips(): ReplayClip[] {
  return (['squat', 'jumping_jack'] as const).flatMap((exercise) =>
    ['normal', 'stationary', 'occlusion', 'out_of_frame', 'missing', 'degenerate'].map(
      (scenario) => ({
        format: 'localfit.landmarks.v1' as const,
        clip_id: `${exercise}-${scenario}`,
        participant_id: 'synthetic-fixture',
        exercise,
        source: 'simulation' as const,
        evidence_kind: 'synthetic' as const,
        scenario,
        reference_reps: scenario === 'normal' ? 3 : 0,
        count_eligible: scenario === 'normal' || scenario === 'stationary',
        exclusion_reason:
          scenario === 'normal' || scenario === 'stationary'
            ? ''
            : 'Deliberate invalid observation; evaluate gate and false counts.',
        down_threshold: 105,
        truncated: false,
        frames: Array.from({ length: (exercise === 'squat' ? 9000 : 4800) / 50 + 1 }, (_, i) => {
          let points = fixturePose(scenario === 'stationary' ? 0 : i * 50, exercise);
          if (scenario === 'occlusion') points = points.map((p) => ({ ...p, visibility: 0 }));
          if (scenario === 'out_of_frame') points = points.map((p) => ({ ...p, x: p.x + 2 }));
          if (scenario === 'missing') points = [];
          if (scenario === 'degenerate') {
            if (exercise === 'squat') points[25] = { ...points[23] };
            else points[24] = { ...points[23] };
          }
          return {
            time_ms: i * 50,
            aspect_ratio: 1,
            points,
            expected_quality:
              scenario === 'normal' || scenario === 'stationary'
                ? ('observed' as const)
                : ('unknown' as const),
          };
        }),
      }),
    ),
  );
}

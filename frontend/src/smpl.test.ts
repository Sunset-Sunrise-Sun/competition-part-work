import { describe, expect, it } from 'vitest';
import { simulatedPose } from './engine';
import { bodyRadii, defaultProfile, retargetPose, retargetSkeleton, mediapipeToSource } from './smpl';

describe('smpl retargeting', () => {
  it('maps MediaPipe landmarks onto the SMPL topology', () => {
    const points = simulatedPose(400, 'squat');
    const source = mediapipeToSource(points, undefined, 4 / 3, 'smpl');
    expect(source[0]).toBeTruthy();
    expect(source[16]).toBeTruthy();
    expect(source[4]).toBeTruthy();
    expect(source.length).toBe(55);
  });

  it('preserves personalized bone length when source proportions differ', () => {
    const short = defaultProfile({ heightCm: 150 });
    const tall = defaultProfile({ heightCm: 190 });
    const source = mediapipeToSource(simulatedPose(800, 'squat'), undefined, 1.2, 'smpl');
    const a = retargetSkeleton(source, short);
    const b = retargetSkeleton(source, tall);
    const femur = (joints: typeof a) =>
      Math.hypot(joints[4].x - joints[1].x, joints[4].y - joints[1].y, joints[4].z - joints[1].z);
    expect(femur(b)).toBeGreaterThan(femur(a));
  });

  it('projects retargeted joints into image space near the detected person', () => {
    const points = simulatedPose(0, 'squat');
    const result = retargetPose(points, undefined, 4 / 3, defaultProfile());
    expect(result.joints).toHaveLength(22);
    const leftHip = result.joints[1];
    expect(leftHip.u).toBeGreaterThan(0.2);
    expect(leftHip.u).toBeLessThan(0.7);
    expect(leftHip.v).toBeGreaterThan(0.3);
    expect(leftHip.v).toBeLessThan(0.8);
    expect(result.joints.every((j) => Number.isFinite(j.u) && Number.isFinite(j.v))).toBe(true);
  });

  it('adds SMPL-X face and finger joints when requested', () => {
    const result = retargetPose(simulatedPose(200, 'jumping_jack'), undefined, 1, defaultProfile({ model: 'smplx' }));
    expect(result.joints).toHaveLength(55);
    expect(result.joints[22].name).toBe('jaw');
    expect(result.bones.length).toBeGreaterThan(23);
  });

  it('makes heavier or more muscular bodies thicker', () => {
    const slim = bodyRadii(defaultProfile({ weightKg: 50, muscleUpper: 0.1, muscleLower: 0.1 }));
    const heavy = bodyRadii(defaultProfile({ weightKg: 110, muscleUpper: 0.9, muscleLower: 0.9 }));
    expect(heavy[16]).toBeGreaterThan(slim[16]);
    expect(heavy[4]).toBeGreaterThan(slim[4]);
  });
});

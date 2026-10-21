import type { Point } from './types';
// Legacy exported names remain API-compatible; parameters are an original diagram.
import official from './body_template.json';

export type Vec3 = { x: number; y: number; z: number };
export type BodyModel = 'smpl' | 'smplx';
export type BodyProfile = {
  heightCm: number;
  weightKg: number;
  muscleUpper: number;
  muscleCore: number;
  muscleLower: number;
  model: BodyModel;
};
export type SmplJoint = {
  name: string;
  x: number;
  y: number;
  z: number;
  u: number;
  v: number;
  visibility: number;
};
export type RetargetResult = {
  joints: SmplJoint[];
  bones: [number, number][];
  radii: number[];
  model: BodyModel;
};

export const SMPL_NAMES = [
  'pelvis',
  'L_hip',
  'R_hip',
  'spine1',
  'L_knee',
  'R_knee',
  'spine2',
  'L_ankle',
  'R_ankle',
  'spine3',
  'L_foot',
  'R_foot',
  'neck',
  'L_collar',
  'R_collar',
  'head',
  'L_shoulder',
  'R_shoulder',
  'L_elbow',
  'R_elbow',
  'L_wrist',
  'R_wrist',
  'jaw',
  'L_eye',
  'R_eye',
] as const;

export const SMPL_PARENT = (official.parents as number[]).map((p) => (p < 0 ? -1 : p));

export function profileToBetas(profile: BodyProfile): number[] {
  const heightM = profile.heightCm / 100;
  const beta0 = (heightM - 1.66) / 0.1;
  const bmi = profile.weightKg / Math.max(heightM * heightM, 0.5);
  const beta1 = Math.max(-3, Math.min(3, (bmi - 23.6) / 8));
  const beta2 = (profile.muscleCore - 0.4) * 2;
  const beta3 = (profile.muscleUpper - 0.45) * 2;
  const beta4 = (profile.muscleLower - 0.45) * 2;
  return [beta0, beta1, beta2, beta3, beta4, 0, 0, 0, 0, 0];
}

export function shapedRestPose(profile: BodyProfile): Vec3[] {
  const betas = profileToBetas(profile);
  const template = official.J_template as number[][];
  const dirs = official.J_shapedirs as number[][][];
  return template.map((joint, j) => {
    let x = joint[0],
      y = joint[1],
      z = joint[2];
    for (let k = 0; k < 10; k++) {
      x += betas[k] * dirs[j][0][k];
      y += betas[k] * dirs[j][1][k];
      z += betas[k] * dirs[j][2][k];
    }
    return { x, y, z };
  });
}

function bonesFromParents(count: number): [number, number][] {
  const bones: [number, number][] = [];
  for (let i = 1; i < count; i++) {
    const parent = SMPL_PARENT[i];
    if (parent >= 0) bones.push([parent, i]);
  }
  return bones;
}

export const SMPL_BONES = bonesFromParents(22);
export const SMPLX_BONES = bonesFromParents(55);

const ANCHORS: [number, number][] = [
  [0, 23],
  [0, 24],
  [16, 11],
  [17, 12],
  [4, 25],
  [5, 26],
  [18, 13],
  [19, 14],
  [7, 27],
  [8, 28],
  [15, 0],
];

const vis = (points: Point[], i: number, fallback = 0) => points[i]?.visibility ?? fallback;

function v(x: number, y: number, z: number): Vec3 {
  return { x, y, z };
}
function add(a: Vec3, b: Vec3): Vec3 {
  return v(a.x + b.x, a.y + b.y, a.z + b.z);
}
function sub(a: Vec3, b: Vec3): Vec3 {
  return v(a.x - b.x, a.y - b.y, a.z - b.z);
}
function scale(a: Vec3, s: number): Vec3 {
  return v(a.x * s, a.y * s, a.z * s);
}
function mid(a: Vec3, b: Vec3): Vec3 {
  return scale(add(a, b), 0.5);
}
function lerp(a: Vec3, b: Vec3, t: number): Vec3 {
  return add(scale(a, 1 - t), scale(b, t));
}
function length(a: Vec3): number {
  return Math.hypot(a.x, a.y, a.z);
}
function normalize(a: Vec3): Vec3 {
  const n = length(a);
  return n < 1e-8 ? v(0, 1, 0) : scale(a, 1 / n);
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

export function defaultProfile(partial: Partial<BodyProfile> = {}): BodyProfile {
  return {
    heightCm: 170,
    weightKg: 65,
    muscleUpper: 0.45,
    muscleCore: 0.4,
    muscleLower: 0.45,
    model: 'smpl',
    ...partial,
  };
}

export function bodyRadii(profile: BodyProfile): number[] {
  const heightM = profile.heightCm / 100;
  const bmi = profile.weightKg / Math.max(heightM * heightM, 0.5);
  const girth = 0.72 + clamp01((bmi - 18) / 14) * 0.5;
  const upper = girth * (0.72 + profile.muscleUpper * 0.55);
  const core = girth * (0.82 + profile.muscleCore * 0.42);
  const lower = girth * (0.74 + profile.muscleLower * 0.5);
  const radii = [
    core * 0.9,
    lower,
    lower,
    core,
    lower * 0.85,
    lower * 0.85,
    core * 1.05,
    lower * 0.55,
    lower * 0.55,
    core * 0.95,
    lower * 0.38,
    lower * 0.38,
    upper * 0.42,
    upper * 0.4,
    upper * 0.4,
    upper * 0.55,
    upper,
    upper,
    upper * 0.72,
    upper * 0.72,
    upper * 0.48,
    upper * 0.48,
    upper * 0.32,
    upper * 0.32,
    upper * 0.28,
    upper * 0.16,
    upper * 0.16,
    upper * 0.18,
    upper * 0.18,
  ];
  const scaled = radii.map((r) => r * (profile.heightCm / 170) * 0.085);
  while (scaled.length < 55) scaled.push(scaled[20] * 0.35);
  return scaled;
}

function fromWorld(point: Point): Vec3 {
  return v(point.x, -point.y, -(point.z ?? 0));
}

function fromImage(point: Point, aspect: number): Vec3 {
  return v((point.x - 0.5) * aspect, -(point.y - 0.5), -(point.z ?? 0) * 0.45);
}

function take(
  points: Point[],
  world: Point[] | undefined,
  aspect: number,
  index: number,
): Vec3 | null {
  const src = world && world.length > index ? world[index] : points[index];
  if (!src || (src.visibility ?? 1) < 0.25) return null;
  return world && world.length > index ? fromWorld(src) : fromImage(src, aspect);
}

export function mediapipeToSource(
  points: Point[],
  world: Point[] | undefined,
  aspect: number,
  model: BodyModel,
): (Vec3 | null)[] {
  const g = (i: number) => take(points, world, aspect, i);
  const Lhip = g(23);
  const Rhip = g(24);
  const Lsho = g(11);
  const Rsho = g(12);
  const pelvis = Lhip && Rhip ? mid(Lhip, Rhip) : Lhip || Rhip;
  const chest = Lsho && Rsho ? mid(Lsho, Rsho) : Lsho || Rsho;
  const Lknee = g(25);
  const Rknee = g(26);
  const Lank = g(27);
  const Rank = g(28);
  const nose = g(0);
  const mouth = g(9) && g(10) ? mid(g(9) as Vec3, g(10) as Vec3) : g(9) || g(10);
  const source: (Vec3 | null)[] = Array.from({ length: 55 }, () => null);
  source[0] = pelvis;
  source[1] = Lhip;
  source[2] = Rhip;
  source[3] = pelvis && chest ? lerp(pelvis, chest, 0.28) : pelvis;
  source[4] = Lknee;
  source[5] = Rknee;
  source[6] = pelvis && chest ? lerp(pelvis, chest, 0.55) : chest;
  source[7] = Lank;
  source[8] = Rank;
  source[9] = pelvis && chest ? lerp(pelvis, chest, 0.82) : chest;
  source[10] = g(31) || g(29) || Lank;
  source[11] = g(32) || g(30) || Rank;
  source[12] = chest;
  source[13] = chest && Lsho ? lerp(chest, Lsho, 0.45) : Lsho;
  source[14] = chest && Rsho ? lerp(chest, Rsho, 0.45) : Rsho;
  source[15] = nose || (chest && mouth ? lerp(chest, mouth, 1.2) : chest);
  source[16] = Lsho;
  source[17] = Rsho;
  source[18] = g(13);
  source[19] = g(14);
  source[20] = g(15);
  source[21] = g(16);
  if (model === 'smplx') {
    source[22] = mouth || nose;
    source[23] = g(2);
    source[24] = g(5);
  }
  return source;
}

export function retargetSkeleton(source: (Vec3 | null)[], profile: BodyProfile): Vec3[] {
  const rest = shapedRestPose(profile);
  const count = profile.model === 'smplx' ? 55 : 22;
  const out = rest.slice(0, count).map((p) => ({ ...p }));
  const root = source[0];
  if (root) out[0] = root;
  for (let i = 1; i < count; i++) {
    const parent = SMPL_PARENT[i];
    const restLen = length(sub(rest[i], rest[parent]));
    const child = source[i];
    const srcParent = source[parent];
    const dir =
      child && srcParent ? normalize(sub(child, srcParent)) : normalize(sub(rest[i], rest[parent]));
    out[i] = add(out[parent], scale(dir, restLen));
  }
  return out;
}

export function projectToImage(joints: Vec3[], points: Point[]): { u: number; v: number }[] {
  let sx = 0,
    sy = 0,
    su = 0,
    sv = 0,
    n = 0;
  for (const [smplIndex, mpIndex] of ANCHORS) {
    const joint = joints[smplIndex];
    const point = points[mpIndex];
    if (!joint || !point || (point.visibility ?? 0) < 0.45) continue;
    sx += joint.x;
    sy += joint.y;
    su += point.x;
    sv += point.y;
    n++;
  }
  if (n < 3) {
    return joints.map((joint) => ({ u: 0.5 + joint.x * 0.35, v: 0.82 - joint.y * 0.45 }));
  }
  const mx = sx / n,
    my = sy / n,
    mu = su / n,
    mv = sv / n;
  let num = 0,
    den = 0;
  for (const [smplIndex, mpIndex] of ANCHORS) {
    const joint = joints[smplIndex];
    const point = points[mpIndex];
    if (!joint || !point || (point.visibility ?? 0) < 0.45) continue;
    num += (joint.x - mx) * (point.x - mu) + (joint.y - my) * -(point.y - mv);
    den += (joint.x - mx) ** 2 + (joint.y - my) ** 2;
  }
  const scaleXY = den < 1e-8 ? 0.35 : num / den;
  return joints.map((joint) => ({
    u: mu + (joint.x - mx) * scaleXY,
    v: mv - (joint.y - my) * scaleXY,
  }));
}

function jointVisibility(points: Point[], index: number): number {
  const mapped: Record<number, number[]> = {
    0: [23, 24],
    1: [23],
    2: [24],
    3: [23, 11],
    4: [25],
    5: [26],
    6: [11, 12],
    7: [27],
    8: [28],
    9: [11, 12],
    10: [31, 29, 27],
    11: [32, 30, 28],
    12: [11, 12],
    13: [11],
    14: [12],
    15: [0],
    16: [11],
    17: [12],
    18: [13],
    19: [14],
    20: [15],
    21: [16],
    22: [19, 15],
    23: [20, 16],
    24: [9, 10],
    25: [2],
    26: [5],
    27: [19],
    28: [20],
  };
  const ids = mapped[index] ?? [];
  if (!ids.length) {
    if (index >= 25 && index <= 39) return vis(points, 15);
    if (index >= 40) return vis(points, 16);
    if (index >= 22) return vis(points, 0);
    return 0;
  }
  return ids.reduce((sum, i) => sum + vis(points, i), 0) / ids.length;
}

export function retargetPose(
  points: Point[],
  world: Point[] | undefined,
  aspect: number,
  profile: BodyProfile,
): RetargetResult {
  const source = mediapipeToSource(points, world, aspect, profile.model);
  const joints3d = retargetSkeleton(source, profile);
  const projected = projectToImage(joints3d, points);
  const bones = profile.model === 'smplx' ? SMPLX_BONES : SMPL_BONES;
  const radii = bodyRadii(profile);
  return {
    model: profile.model,
    bones,
    radii,
    joints: joints3d.map((joint, i) => ({
      name: SMPL_NAMES[i] ?? `j${i}`,
      ...joint,
      u: projected[i].u,
      v: projected[i].v,
      visibility: jointVisibility(points, i),
    })),
  };
}

export const RAW_CONNECTIONS: [number, number][] = [
  [11, 12],
  [11, 13],
  [13, 15],
  [12, 14],
  [14, 16],
  [11, 23],
  [12, 24],
  [23, 24],
  [23, 25],
  [25, 27],
  [24, 26],
  [26, 28],
];

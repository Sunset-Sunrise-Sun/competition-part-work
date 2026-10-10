import type { Exercise, Metrics, Point, SquatRep } from './types';
// x/y are normalized to different image axes: restore a shared scale first.
export function jointAngle(a: Point, b: Point, c: Point, aspectRatio = 1): number {
  if (!Number.isFinite(aspectRatio) || aspectRatio <= 0) return NaN;
  const ux = (a.x - b.x) * aspectRatio,
    uy = a.y - b.y,
    vx = (c.x - b.x) * aspectRatio,
    vy = c.y - b.y;
  const norm = Math.hypot(ux, uy) * Math.hypot(vx, vy);
  if (norm < 1e-8) return NaN;
  return (Math.acos(Math.max(-1, Math.min(1, (ux * vx + uy * vy) / norm))) * 180) / Math.PI;
}

export class ExerciseEngine {
  private reps = 0;
  private state = 'ready';
  private smoothed = 180;
  private lastRep = -Infinity;
  private lastEvent = -Infinity;
  private events = 0;
  private lostSince: number | null = null;
  private armed = false;
  private candidate: {
    start: number;
    bottom: number;
    minAngle: number;
    qualified: boolean;
    obscured: boolean;
  } | null = null;
  private squatReps: SquatRep[] = [];
  private lastSampleTime: number | null = null;
  constructor(
    private exercise: Exercise,
    private downThreshold = 105,
  ) {}

  update(points: Point[], time: number, aspectRatio = 1): Metrics {
    if (this.lastSampleTime !== null && time - this.lastSampleTime > 500) {
      this.candidate = null;
      this.armed = false;
      this.state = 'ready';
      this.smoothed = 180;
    }
    this.lastSampleTime = time;
    const needed = this.exercise === 'squat' ? [23, 25, 27] : [11, 12, 15, 16, 27, 28];
    const quality =
      Number.isFinite(aspectRatio) &&
      aspectRatio > 0 &&
      needed.every(
        (i) =>
          points[i] &&
          (points[i].visibility ?? 0) >= 0.65 &&
          points[i].x >= 0 &&
          points[i].x <= 1 &&
          points[i].y >= 0 &&
          points[i].y <= 1,
      );
    if (!quality) {
      if (this.candidate) this.candidate.obscured = true;
      if (this.lostSince === null) this.lostSince = time;
      if (time - this.lostSince > 500) {
        this.state = 'ready';
        this.smoothed = 180;
        this.armed = false;
        this.candidate = null;
      }
      return this.result(false, '关键点不可见，请调整机位；暂停动作评价。');
    }
    this.lostSince = null;
    let hint = '保持节奏，完整完成动作。';
    if (this.exercise === 'squat') {
      const raw = jointAngle(points[23], points[25], points[27], aspectRatio);
      if (!Number.isFinite(raw)) return this.result(false, '无法估计关节角度，请调整机位。');
      this.smoothed = this.smoothed * 0.6 + raw * 0.4;
      // Count the cycle separately from its experimental ROM grade.
      const countThreshold = Math.min(145, this.downThreshold + 25);
      if (this.armed && this.smoothed < 150 && !this.candidate) {
        this.candidate = {
          start: time,
          bottom: time,
          minAngle: this.smoothed,
          qualified: false,
          obscured: false,
        };
      }
      if (this.candidate) {
        if (this.smoothed < this.candidate.minAngle) {
          this.candidate.minAngle = this.smoothed;
          this.candidate.bottom = time;
        }
        if (this.smoothed < countThreshold) {
          this.candidate.qualified = true;
          this.state = 'down';
        }
      }
      if (this.smoothed > 155 && raw > 155) {
        const cycle = this.candidate;
        if (cycle?.qualified && time - cycle.start >= 700 && time - this.lastRep > 700) {
          this.reps++;
          this.lastRep = time;
          this.squatReps.push({
            number: this.reps,
            start_seconds: cycle.start / 1000,
            bottom_seconds: cycle.bottom / 1000,
            end_seconds: time / 1000,
            descent_seconds: (cycle.bottom - cycle.start) / 1000,
            ascent_seconds: (time - cycle.bottom) / 1000,
            min_angle_degrees: Math.round(cycle.minAngle * 10) / 10,
            rom: cycle.obscured
              ? 'unobservable'
              : cycle.minAngle <= this.downThreshold
                ? 'within_rule'
                : 'below_rule',
          });
          if (this.squatReps.length > 100) this.squatReps.shift();
        }
        this.candidate = null;
        this.armed = true;
        this.state = 'ready';
      }
      if (points[11] && (points[11].visibility ?? 0) >= 0.65) {
        const dx = Math.abs(points[11].x - points[23].x) * aspectRatio;
        const dy = Math.abs(points[11].y - points[23].y);
        if (dx > dy * 0.9) {
          hint = '躯干倾斜较明显，请检查机位与动作；此提示采用待验证规则。';
          if (time - this.lastEvent > 4000) {
            this.events++;
            this.lastEvent = time;
          }
        }
      }
    } else {
      const shoulder = Math.max(Math.abs(points[11].x - points[12].x), 0.05);
      const spread = Math.abs(points[27].x - points[28].x) / shoulder;
      const handsUp = points[15].y < points[11].y && points[16].y < points[12].y;
      const handsDown = points[15].y > points[11].y && points[16].y > points[12].y;
      if (handsUp && spread > 1.4) this.state = 'open';
      if (this.state === 'open' && handsDown && spread < 1.1 && time - this.lastRep > 500) {
        this.reps++;
        this.lastRep = time;
        this.state = 'ready';
      }
      this.smoothed = spread * 100;
    }
    return this.result(true, hint);
  }

  private result(quality: boolean, hint: string): Metrics {
    return {
      reps: this.reps,
      phase: this.state,
      quality,
      hint,
      angle: Math.round(this.smoothed),
      events: this.events,
      squatReps: [...this.squatReps],
    };
  }
}

export function simulatedPose(time: number, exercise: Exercise): Point[] {
  const p: Point[] = Array.from({ length: 33 }, () => ({ x: 0.5, y: 0.25, visibility: 1 }));
  const wave = (1 - Math.cos(time / 350)) / 2;
  p[11] = { x: 0.44, y: 0.24, visibility: 1 };
  p[12] = { x: 0.56, y: 0.24, visibility: 1 };
  p[23] = { x: 0.44 + wave * 0.13, y: 0.5 + wave * 0.18, visibility: 1 };
  p[24] = { x: 0.56 + wave * 0.13, y: 0.5 + wave * 0.18, visibility: 1 };
  p[25] = { x: 0.44, y: 0.7, visibility: 1 };
  p[26] = { x: 0.56, y: 0.7, visibility: 1 };
  p[27] = { x: 0.44, y: 0.9, visibility: 1 };
  p[28] = { x: 0.56, y: 0.9, visibility: 1 };
  p[13] = { x: 0.35, y: 0.38, visibility: 1 };
  p[14] = { x: 0.65, y: 0.38, visibility: 1 };
  p[15] = { x: 0.3, y: 0.5, visibility: 1 };
  p[16] = { x: 0.7, y: 0.5, visibility: 1 };
  if (exercise === 'jumping_jack') {
    p[15].y = p[16].y = 0.48 - wave * 0.4;
    p[27].x = 0.46 - wave * 0.15;
    p[28].x = 0.54 + wave * 0.15;
    p[23] = { x: 0.44, y: 0.5, visibility: 1 };
    p[24] = { x: 0.56, y: 0.5, visibility: 1 };
  }
  return p;
}

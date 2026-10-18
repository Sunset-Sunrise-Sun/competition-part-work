import type { Exercise, Metrics, Point, SquatRep } from './types';

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

const REQUIRED: Record<Exercise, number[]> = {
  squat: [23, 25, 27],
  jumping_jack: [11, 12, 15, 16, 23, 24, 27, 28],
  pull_up: [0, 11, 12, 15, 16, 23, 24],
  jump_rope: [11, 12, 15, 16, 23, 24, 25, 26],
};

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
  private hipSmooth = 0.55;
  private hipMin = 0.55;
  private hipMax = 0.55;
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
    const needed = REQUIRED[this.exercise];
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
    if (this.exercise === 'squat') return this.updateSquat(points, time, aspectRatio);
    if (this.exercise === 'jumping_jack') return this.updateJumpingJack(points, time, aspectRatio);
    if (this.exercise === 'pull_up') return this.updatePullUp(points, time);
    return this.updateJumpRope(points, time);
  }

  private updateSquat(points: Point[], time: number, aspectRatio: number): Metrics {
    let hint = '侧面全身入画，先站直再下蹲。';
    const raw = jointAngle(points[23], points[25], points[27], aspectRatio);
    if (!Number.isFinite(raw)) return this.result(false, '无法估计关节角度，请调整机位。');
    this.smoothed = this.smoothed * 0.6 + raw * 0.4;
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
      hint = '回到站立。';
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
    return this.result(true, hint);
  }

  private updateJumpingJack(points: Point[], time: number, aspectRatio: number): Metrics {
    const hipW = Math.max(Math.abs(points[23].x - points[24].x) * aspectRatio, 0.05);
    const footW = Math.abs(points[27].x - points[28].x) * aspectRatio;
    const spread = footW / hipW;
    const handsHigh = points[15].y < points[11].y - 0.04 && points[16].y < points[12].y - 0.04;
    const handsLow = points[15].y > points[11].y + 0.1 && points[16].y > points[12].y + 0.1;
    const feetOpen = spread > 1.65;
    const feetClosed = spread < 1.28;
    this.smoothed = spread * 50;
    if (handsLow && feetClosed) {
      this.armed = true;
      if (this.state === 'open' && time - this.lastRep > 450) {
        this.reps++;
        this.lastRep = time;
        this.state = 'ready';
        return this.result(true, '完成一次开合。手臂过头、双脚打开后再收回。');
      }
      this.state = 'ready';
      return this.result(true, '双手放体侧、双脚并拢，准备下一次打开。');
    }
    if (this.armed && handsHigh && feetOpen) {
      this.state = 'open';
      return this.result(true, '打开：手臂上举，双脚同时分开。');
    }
    if (handsHigh && !feetOpen) return this.result(true, '手臂已抬起，请同时把双脚分开。');
    if (feetOpen && !handsHigh) return this.result(true, '双脚已分开，请把双手举过肩膀。');
    return this.result(true, '开合跳要手脚同时打开再同时收回，正面全身入画。');
  }

  private updatePullUp(points: Point[], time: number): Metrics {
    const wristY = (points[15].y + points[16].y) / 2;
    const shoulderY = (points[11].y + points[12].y) / 2;
    const hipY = (points[23].y + points[24].y) / 2;
    const torso = Math.max(hipY - shoulderY, 0.08);
    const hang = (shoulderY - wristY) / torso;
    this.smoothed = Math.round(hang * 100);
    const onBar = wristY < shoulderY - 0.02;
    if (!onBar) {
      this.armed = false;
      this.state = 'ready';
      return this.result(true, '请双手抓住横杆，手腕应高于肩膀。借鉴 vision-demos：相对手部测躯干。');
    }
    const down = hang > 0.95;
    const up = hang < 0.45;
    if (down) {
      this.armed = true;
      if (this.state === 'up' && time - this.lastRep > 600) {
        this.reps++;
        this.lastRep = time;
        this.state = 'hang';
        return this.result(true, '回到悬垂，完成一次。浅拉也计数，幅度另评。');
      }
      this.state = 'hang';
      return this.result(true, '悬垂已看到。向上拉，让肩膀靠近手腕。');
    }
    if (this.armed && up) {
      this.state = 'up';
      return this.result(true, '拉到高点，再控制下放。');
    }
    return this.result(true, '保持抓杠，完整完成下放再上拉。');
  }

  private updateJumpRope(points: Point[], time: number): Metrics {
    const hipY = (points[23].y + points[24].y) / 2;
    this.hipSmooth = this.hipSmooth * 0.65 + hipY * 0.35;
    this.hipMin = Math.min(this.hipMin * 0.995 + this.hipSmooth * 0.005, this.hipSmooth);
    this.hipMax = Math.max(this.hipMax * 0.995 + this.hipSmooth * 0.005, this.hipSmooth);
    const amp = this.hipMax - this.hipMin;
    this.smoothed = Math.round(amp * 1000);
    const wristsLow = points[15].y > points[11].y && points[16].y > points[12].y;
    if (!wristsLow) return this.result(true, '跳绳时手腕应在腰侧摇绳，不要举过肩。');
    if (amp < 0.012) return this.result(true, '请小幅度连续跳起，正面或侧面全身入画。');
    const up = this.hipSmooth < this.hipMin + amp * 0.35;
    const down = this.hipSmooth > this.hipMax - amp * 0.35;
    const dt = this.lastRep === -Infinity ? 400 : time - this.lastRep;
    if (up) this.state = 'air';
    if (this.state === 'air' && down && dt > 240 && dt < 900) {
      this.reps++;
      this.lastRep = time;
      this.state = 'ready';
      return this.result(true, '着地一次。保持轻快节奏。');
    }
    if (this.state === 'air' && down && dt >= 900) this.state = 'ready';
    return this.result(true, this.state === 'air' ? '腾空，准备落地。' : '连续小跳，不要做成深蹲。');
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
  if (exercise === 'jumping_jack') {
    const wave = (1 - Math.cos((time / 550) * Math.PI)) / 2;
    const hop = wave * 0.035;
    p[0] = { x: 0.5, y: 0.16 - hop, visibility: 1 };
    p[11] = { x: 0.44, y: 0.28 - hop, visibility: 1 };
    p[12] = { x: 0.56, y: 0.28 - hop, visibility: 1 };
    p[13] = { x: 0.38 - wave * 0.12, y: 0.42 - hop - wave * 0.18, visibility: 1 };
    p[14] = { x: 0.62 + wave * 0.12, y: 0.42 - hop - wave * 0.18, visibility: 1 };
    p[15] = { x: 0.34 - wave * 0.16, y: 0.54 - hop - wave * 0.4, visibility: 1 };
    p[16] = { x: 0.66 + wave * 0.16, y: 0.54 - hop - wave * 0.4, visibility: 1 };
    p[23] = { x: 0.47 - wave * 0.02, y: 0.52 - hop, visibility: 1 };
    p[24] = { x: 0.53 + wave * 0.02, y: 0.52 - hop, visibility: 1 };
    p[25] = { x: 0.46 - wave * 0.1, y: 0.7 - hop, visibility: 1 };
    p[26] = { x: 0.54 + wave * 0.1, y: 0.7 - hop, visibility: 1 };
    p[27] = { x: 0.47 - wave * 0.17, y: 0.9 - hop, visibility: 1 };
    p[28] = { x: 0.53 + wave * 0.17, y: 0.9 - hop, visibility: 1 };
    return p;
  }
  if (exercise === 'pull_up') {
    const wave = (1 - Math.cos((time / 700) * Math.PI)) / 2;
    const lift = wave * 0.16;
    p[15] = { x: 0.38, y: 0.12, visibility: 1 };
    p[16] = { x: 0.62, y: 0.12, visibility: 1 };
    p[13] = { x: 0.36, y: 0.22 - lift * 0.3, visibility: 1 };
    p[14] = { x: 0.64, y: 0.22 - lift * 0.3, visibility: 1 };
    p[11] = { x: 0.42, y: 0.38 - lift, visibility: 1 };
    p[12] = { x: 0.58, y: 0.38 - lift, visibility: 1 };
    p[0] = { x: 0.5, y: 0.24 - lift, visibility: 1 };
    p[23] = { x: 0.45, y: 0.62 - lift, visibility: 1 };
    p[24] = { x: 0.55, y: 0.62 - lift, visibility: 1 };
    p[25] = { x: 0.45, y: 0.74 - lift, visibility: 1 };
    p[26] = { x: 0.55, y: 0.74 - lift, visibility: 1 };
    p[27] = { x: 0.45, y: 0.9 - lift, visibility: 1 };
    p[28] = { x: 0.55, y: 0.9 - lift, visibility: 1 };
    return p;
  }
  if (exercise === 'jump_rope') {
    const wave = (1 - Math.cos((time / 280) * Math.PI)) / 2;
    const hop = wave * 0.05;
    p[0] = { x: 0.5, y: 0.16 - hop, visibility: 1 };
    p[11] = { x: 0.44, y: 0.28 - hop, visibility: 1 };
    p[12] = { x: 0.56, y: 0.28 - hop, visibility: 1 };
    p[13] = { x: 0.34, y: 0.42 - hop, visibility: 1 };
    p[14] = { x: 0.66, y: 0.42 - hop, visibility: 1 };
    p[15] = { x: 0.3, y: 0.5 - hop, visibility: 1 };
    p[16] = { x: 0.7, y: 0.5 - hop, visibility: 1 };
    p[23] = { x: 0.46, y: 0.52 - hop, visibility: 1 };
    p[24] = { x: 0.54, y: 0.52 - hop, visibility: 1 };
    p[25] = { x: 0.46, y: 0.7 - hop, visibility: 1 };
    p[26] = { x: 0.54, y: 0.7 - hop, visibility: 1 };
    p[27] = { x: 0.46, y: 0.88 - hop, visibility: 1 };
    p[28] = { x: 0.54, y: 0.88 - hop, visibility: 1 };
    return p;
  }
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
  return p;
}

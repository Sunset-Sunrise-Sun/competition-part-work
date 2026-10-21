import type { Point } from './types';

export type ActivityState = 'work' | 'rest' | 'unknown';
/** Causal movement heuristic, not a physiological intensity measurement. */
export class ActivityTracker {
  private previous: { points: Point[]; time: number } | null = null;
  private lastMovement = -Infinity;
  update(points: Point[], time: number, quality: boolean, aspect = 1): ActivityState {
    const indices = [11, 12, 23, 24, 25, 26, 27, 28];
    if (!quality || !Number.isFinite(time) || !Number.isFinite(aspect) || aspect <= 0) {
      this.previous = null;
      this.lastMovement = -Infinity;
      return 'unknown';
    }
    const previous = this.previous;
    this.previous = { points: points.map((p) => ({ ...p })), time };
    if (!previous || time <= previous.time || time - previous.time > 500) {
      this.lastMovement = -Infinity;
      return 'unknown';
    }
    const usable = indices.filter(
      (i) =>
        points[i] &&
        previous.points[i] &&
        (points[i].visibility ?? 0) >= 0.65 &&
        (previous.points[i].visibility ?? 0) >= 0.65,
    );
    if (usable.length < 4) {
      this.lastMovement = -Infinity;
      return 'unknown';
    }
    const speed =
      usable.reduce(
        (sum, i) =>
          sum +
          Math.hypot(
            (points[i].x - previous.points[i].x) * aspect,
            points[i].y - previous.points[i].y,
          ),
        0,
      ) /
      usable.length /
      ((time - previous.time) / 1000);
    if (speed > 0.08) this.lastMovement = time;
    return time - this.lastMovement <= 400 ? 'work' : 'rest';
  }
}

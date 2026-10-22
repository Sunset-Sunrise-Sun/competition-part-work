import { ExerciseEngine } from './engine';
import { ActivityTracker, type ActivityState } from './activity';
import type { Point } from './types';
import contract from '../../shared/contract.json';

export type ReplayFrame = {
  time_ms: number;
  aspect_ratio: number;
  points: Point[];
  boundary?: boolean;
  expected_quality?: 'observed' | 'unknown';
  expected_activity?: ActivityState;
};
export type ReplayClip = {
  format: 'localfit.landmarks.v1';
  clip_id: string;
  participant_id: string;
  exercise: 'squat' | 'jumping_jack';
  source: 'camera' | 'video' | 'simulation';
  evidence_kind: 'recorded_landmarks' | 'synthetic';
  scenario: string;
  reference_reps: number | null;
  count_eligible: boolean | null;
  exclusion_reason: string;
  down_threshold: number;
  truncated: boolean;
  frames: ReplayFrame[];
  annotation?: { annotator_id: string; reviewer_id: string };
  reference_cycles?: {
    end_ms: number;
    rom?: 'within_rule' | 'below_rule' | 'unobservable';
    descent_seconds?: number;
    ascent_seconds?: number;
  }[];
};

/** Opt-in, bounded, in-memory only. No images, filenames, identity or network requests. */
export class LandmarkRecorder {
  frames: ReplayFrame[] = [];
  truncated = false;
  private pendingBoundary = true;
  constructor(private limit = 20000) {}
  boundary() {
    this.pendingBoundary = true;
  }
  add(points: Point[], time: number, aspect: number) {
    if (this.frames.length >= this.limit) {
      this.truncated = true;
      return;
    }
    if (!Number.isFinite(time) || time < 0 || !Number.isFinite(aspect) || aspect <= 0) return;
    if (this.frames.length && time <= this.frames[this.frames.length - 1].time_ms) return;
    this.frames.push({
      time_ms: time,
      aspect_ratio: aspect,
      points: points.map(({ x, y, visibility }) => ({ x, y, visibility })),
      ...(this.pendingBoundary ? { boundary: true } : {}),
    });
    this.pendingBoundary = false;
  }
}

export function evaluateClip(clip: ReplayClip) {
  if (
    clip.format !== 'localfit.landmarks.v1' ||
    !['squat', 'jumping_jack'].includes(clip.exercise) ||
    !['camera', 'video', 'simulation'].includes(clip.source) ||
    !['recorded_landmarks', 'synthetic'].includes(clip.evidence_kind) ||
    (clip.source === 'simulation' && clip.evidence_kind !== 'synthetic') ||
    !clip.clip_id ||
    !clip.participant_id ||
    !clip.scenario ||
    !Array.isArray(clip.frames) ||
    clip.frames.length === 0 ||
    clip.frames.length > 20000 ||
    clip.truncated !== false ||
    !Number.isFinite(clip.down_threshold) ||
    clip.down_threshold < 60 ||
    clip.down_threshold > 140 ||
    ![true, false, null].includes(clip.count_eligible) ||
    (clip.reference_reps !== null &&
      (!Number.isInteger(clip.reference_reps) || clip.reference_reps < 0)) ||
    (clip.count_eligible === true && clip.reference_reps === null) ||
    (clip.count_eligible === false && !clip.exclusion_reason)
  )
    throw new Error('Invalid, unlabelled eligible, or truncated replay clip: ' + clip.clip_id);
  if (
    clip.evidence_kind === 'recorded_landmarks' &&
    clip.count_eligible === true &&
    (!clip.annotation?.annotator_id ||
      !clip.annotation.reviewer_id ||
      clip.annotation.annotator_id === clip.annotation.reviewer_id ||
      clip.participant_id === 'TO_LABEL' ||
      clip.scenario === 'TO_LABEL')
  )
    throw new Error(
      'Recorded count evaluation requires independent annotation/review and anonymous participant ID.',
    );
  const engine = new ExerciseEngine(clip.exercise, clip.down_threshold);
  let tracker = new ActivityTracker();
  let previous = -1;
  let last;
  const quality = {
    observed_as_observed: 0,
    observed_as_unknown: 0,
    unknown_as_observed: 0,
    unknown_as_unknown: 0,
  };
  const activity: Record<string, number> = {};
  const reasons: Record<string, number> = {};
  const durations = { work: 0, rest: 0, unknown: 0 };
  const events: { time_ms: number; reps: number }[] = [];
  let lastReps = 0;
  for (const frame of clip.frames) {
    if (
      !Number.isFinite(frame.time_ms) ||
      frame.time_ms < 0 ||
      frame.time_ms <= previous ||
      !Number.isFinite(frame.aspect_ratio) ||
      frame.aspect_ratio <= 0 ||
      !Array.isArray(frame.points) ||
      (frame.points.length !== 0 && frame.points.length !== 33) ||
      frame.points.some(
        (p) =>
          !p || !Number.isFinite(p.x) || !Number.isFinite(p.y) || !Number.isFinite(p.visibility),
      ) ||
      (frame.expected_quality !== undefined &&
        !['observed', 'unknown'].includes(frame.expected_quality)) ||
      (frame.expected_activity !== undefined &&
        !['work', 'rest', 'unknown'].includes(frame.expected_activity)) ||
      (frame.boundary !== undefined && typeof frame.boundary !== 'boolean')
    )
      throw new Error('Malformed frame in ' + clip.clip_id);
    if (frame.boundary) {
      engine.interrupt();
      tracker = new ActivityTracker();
    }
    last = engine.update(frame.points, frame.time_ms, frame.aspect_ratio);
    const state = tracker.update(frame.points, frame.time_ms, last.quality, frame.aspect_ratio);
    if (previous >= 0)
      durations[frame.boundary ? 'unknown' : state] += (frame.time_ms - previous) / 1000;
    previous = frame.time_ms;
    const actual = last.quality ? 'observed' : 'unknown';
    if (frame.expected_quality) quality[`${frame.expected_quality}_as_${actual}`]++;
    if (frame.expected_activity) {
      const key = `${frame.expected_activity}_as_${state}`;
      activity[key] = (activity[key] ?? 0) + 1;
    }
    reasons[last.quality_code ?? actual] = (reasons[last.quality_code ?? actual] ?? 0) + 1;
    if (last.reps > lastReps) events.push({ time_ms: frame.time_ms, reps: last.reps });
    lastReps = last.reps;
  }
  const cycles = clip.reference_cycles ?? [];
  if (
    !Array.isArray(cycles) ||
    (cycles.length > 0 && clip.exercise !== 'squat') ||
    cycles.some(
      (c, i) =>
        !Number.isFinite(c.end_ms) ||
        c.end_ms < 0 ||
        c.end_ms > previous ||
        (i > 0 && c.end_ms <= cycles[i - 1].end_ms) ||
        (c.rom !== undefined && !['within_rule', 'below_rule', 'unobservable'].includes(c.rom)) ||
        [c.descent_seconds, c.ascent_seconds].some(
          (v) => v !== undefined && (!Number.isFinite(v) || v < 0),
        ),
    )
  )
    throw new Error('Invalid reference cycle annotations: ' + clip.clip_id);
  const remaining = [...last!.squatReps];
  const amplitude: Record<string, number> = {};
  const descentErrors: number[] = [],
    ascentErrors: number[] = [];
  let matched = 0;
  for (const reference of cycles) {
    let nearest = -1,
      distance = 500.001;
    remaining.forEach((rep, index) => {
      const error = Math.abs(rep.end_seconds * 1000 - reference.end_ms);
      if (error < distance) {
        distance = error;
        nearest = index;
      }
    });
    if (nearest < 0) continue;
    const [rep] = remaining.splice(nearest, 1);
    matched++;
    if (reference.rom) {
      const key = `${reference.rom}_as_${rep.rom}`;
      amplitude[key] = (amplitude[key] ?? 0) + 1;
    }
    if (reference.descent_seconds !== undefined)
      descentErrors.push(Math.abs(rep.descent_seconds - reference.descent_seconds));
    if (reference.ascent_seconds !== undefined)
      ascentErrors.push(Math.abs(rep.ascent_seconds - reference.ascent_seconds));
  }
  const mean = (values: number[]) =>
    values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  return {
    clip_id: clip.clip_id,
    participant_id: clip.participant_id,
    scenario: clip.scenario,
    exercise: clip.exercise,
    evidence_kind: clip.evidence_kind,
    source: clip.source,
    count_eligible: clip.count_eligible,
    exclusion_reason: clip.exclusion_reason,
    reference_reps: clip.reference_reps,
    predicted_reps: last!.reps,
    absolute_error:
      clip.reference_reps === null ? null : Math.abs(last!.reps - clip.reference_reps),
    annotated_quality_frames: Object.values(quality).reduce((a, b) => a + b, 0),
    quality_confusion: quality,
    activity_confusion: activity,
    quality_reasons: reasons,
    classified_seconds: durations,
    rep_events: events,
    rep_details: last!.squatReps,
    squat_cycle_comparison: {
      available: cycles.length > 0,
      reference_cycles: cycles.length,
      matched_cycles: matched,
      unmatched_reference_cycles: cycles.length - matched,
      unmatched_predicted_cycles: cycles.length ? remaining.length : null,
      matching_tolerance_ms: 500,
      amplitude_confusion: amplitude,
      descent_samples: descentErrors.length,
      descent_mae_seconds: mean(descentErrors),
      ascent_samples: ascentErrors.length,
      ascent_mae_seconds: mean(ascentErrors),
    },
  };
}

export function evaluateDataset(clips: ReplayClip[]) {
  if (
    !Array.isArray(clips) ||
    clips.length === 0 ||
    new Set(clips.map((c) => c.clip_id)).size !== clips.length
  )
    throw new Error('Provide non-empty clips with unique IDs.');
  const rows = clips.map(evaluateClip);
  const groups = ['synthetic', 'recorded_landmarks'].flatMap((kind) =>
    ['squat', 'jumping_jack']
      .map((exercise) => {
        const all = rows.filter((r) => r.evidence_kind === kind && r.exercise === exercise);
        const eligible = all.filter((r) => r.count_eligible === true);
        const observed = all.reduce(
          (n, r) =>
            n + r.quality_confusion.observed_as_observed + r.quality_confusion.observed_as_unknown,
          0,
        );
        const unknown = all.reduce(
          (n, r) =>
            n + r.quality_confusion.unknown_as_observed + r.quality_confusion.unknown_as_unknown,
          0,
        );
        return {
          evidence_kind: kind,
          exercise,
          total_clips: all.length,
          participants: new Set(all.map((r) => r.participant_id)).size,
          eligible_clips: eligible.length,
          excluded_clips: all.filter((r) => r.count_eligible === false).length,
          unlabelled_clips: all.filter((r) => r.count_eligible === null).length,
          count_mae: eligible.length
            ? eligible.reduce((n, r) => n + r.absolute_error!, 0) / eligible.length
            : null,
          within_one_rate: eligible.length
            ? eligible.filter((r) => r.absolute_error! <= 1).length / eligible.length
            : null,
          normal_false_rejection_rate: observed
            ? all.reduce((n, r) => n + r.quality_confusion.observed_as_unknown, 0) / observed
            : null,
          invalid_false_acceptance_rate: unknown
            ? all.reduce((n, r) => n + r.quality_confusion.unknown_as_observed, 0) / unknown
            : null,
        };
      })
      .filter((g) => g.total_clips > 0),
  );
  return {
    algorithm_version: contract.algorithm_version,
    evidence_scope: 'landmark replay; not end-to-end pose model accuracy',
    groups,
    rows,
  };
}

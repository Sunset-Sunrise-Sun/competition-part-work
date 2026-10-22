import { describe, expect, it } from 'vitest';
import { evaluateClip, evaluateDataset, LandmarkRecorder } from './replay';
import { fixturePose, syntheticClips } from './replayFixtures';
import { ExerciseEngine } from './engine';

describe('core algorithm replay', () => {
  it.each(syntheticClips())('authored kinematics: $clip_id', (clip) => {
    const result = evaluateClip(clip);
    expect(result.predicted_reps).toBe(clip.reference_reps);
    expect(result.quality_confusion.unknown_as_observed).toBe(0);
    expect(result.quality_confusion.observed_as_unknown).toBe(0);
  });
  it.each([10, 20, 30])('squat count stable at %i FPS', (fps) => {
    const engine = new ExerciseEngine('squat');
    let last;
    for (let i = 0; i <= 9 * fps; i++)
      last = engine.update(fixturePose((i * 1000) / fps, 'squat'), (i * 1000) / fps);
    expect(last!.reps).toBe(3);
  });
  it.each(['squat', 'jumping_jack'] as const)('mid-cycle start cannot count %s', (exercise) => {
    const engine = new ExerciseEngine(exercise);
    const start = exercise === 'squat' ? 1500 : 550;
    const end = exercise === 'squat' ? 3000 : 1550;
    let last;
    for (let t = start; t <= end; t += 50)
      last = engine.update(fixturePose(t, exercise), t - start);
    expect(last!.reps).toBe(0);
  });
  it.each(['squat', 'jumping_jack'] as const)(
    'pause cancels pending %s but preserves completed reps',
    (exercise) => {
      const engine = new ExerciseEngine(exercise);
      const cycle = exercise === 'squat' ? 3000 : 1600;
      for (let t = 0; t <= cycle * 1.5; t += 50) engine.update(fixturePose(t, exercise), t);
      engine.interrupt();
      let last;
      for (let t = cycle * 1.5 + 50; t <= cycle * 2; t += 50)
        last = engine.update(fixturePose(t, exercise), t);
      expect(last!.reps).toBe(1);
    },
  );
  it('short jack occlusion requires a fresh closed-open-closed cycle', () => {
    const engine = new ExerciseEngine('jumping_jack');
    let last;
    for (let t = 0; t <= 1600; t += 50)
      last = engine.update(t === 800 ? [] : fixturePose(t, 'jumping_jack'), t);
    expect(last!.reps).toBe(0);
    for (let t = 1650; t <= 3200; t += 50) last = engine.update(fixturePose(t, 'jumping_jack'), t);
    expect(last!.reps).toBe(1);
  });
  it('a single open pose spike is not a repetition', () => {
    const engine = new ExerciseEngine('jumping_jack');
    let last;
    for (let t = 0; t <= 1500; t += 50)
      last = engine.update(fixturePose(t === 500 ? 500 : 0, 'jumping_jack'), t);
    expect(last!.reps).toBe(0);
  });
  it.each([NaN, Infinity, -1, 100])('bad timestamp %s returns unknown without count', (time) => {
    const engine = new ExerciseEngine('squat');
    engine.update(fixturePose(0, 'squat'), 100);
    const result = engine.update(fixturePose(1000, 'squat'), time);
    expect(result.quality_code).toBe('invalid_timestamp');
    expect(result.reps).toBe(0);
  });
  it('keeps excluded and unlabelled clips in the report without inventing a count score', () => {
    const clip = { ...syntheticClips()[0], reference_reps: null, count_eligible: null };
    const group = evaluateDataset([clip]).groups[0];
    expect(group.unlabelled_clips).toBe(1);
    expect(group.count_mae).toBeNull();
    expect(evaluateDataset(syntheticClips()).groups[0].excluded_clips).toBe(4);
  });
  it('rejects duplicate IDs, malformed timestamps and truncated clips', () => {
    const clip = syntheticClips()[0];
    expect(() => evaluateDataset([clip, clip])).toThrow();
    expect(() => evaluateClip({ ...clip, truncated: true })).toThrow();
    clip.frames[1].time_ms = 0;
    expect(() => evaluateClip(clip)).toThrow();
  });
  it('recorder clones points, marks pause boundaries and caps memory', () => {
    const recorder = new LandmarkRecorder(2);
    const points = fixturePose(0, 'squat');
    recorder.add(points, 0, 1);
    points[0].x = 99;
    recorder.boundary();
    recorder.add(points, 50, 1);
    recorder.add(points, 100, 1);
    expect(recorder.frames).toHaveLength(2);
    expect(recorder.frames[0].points[0].x).not.toBe(99);
    expect(recorder.frames[1].boundary).toBe(true);
    expect(recorder.truncated).toBe(true);
  });
  it('compares independent cycle timing and exposes unmatched cycles', () => {
    const clip = syntheticClips()[0];
    clip.reference_cycles = [
      { end_ms: 3000, rom: 'within_rule', descent_seconds: 1.5, ascent_seconds: 1.5 },
      { end_ms: 4500, rom: 'unobservable' },
    ];
    const score = evaluateClip(clip).squat_cycle_comparison;
    expect(score.matched_cycles).toBe(1);
    expect(score.unmatched_reference_cycles).toBe(1);
    expect(score.unmatched_predicted_cycles).toBe(2);
    expect(score.amplitude_confusion.within_rule_as_within_rule).toBe(1);
    expect(score.descent_samples).toBe(1);
    expect(score.descent_mae_seconds).toBeGreaterThanOrEqual(0);
  });
  it('recorded eligible clips require independent review', () => {
    const clip = {
      ...syntheticClips()[0],
      source: 'video' as const,
      evidence_kind: 'recorded_landmarks' as const,
    };
    expect(() => evaluateClip(clip)).toThrow(/review/);
    expect(
      evaluateClip({ ...clip, annotation: { annotator_id: 'A', reviewer_id: 'B' } }).absolute_error,
    ).toBe(0);
  });
});

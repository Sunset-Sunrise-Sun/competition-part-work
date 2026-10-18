import { describe, expect, it } from 'vitest';
import { acceptLocal, analyzeLocal } from './localCoach';

describe('browser coach fallback', () => {
  it('reduces the next target when fatigue is high and evidence is enough', () => {
    const report = analyzeLocal({
      session_id: 'browser-1',
      input_version: 1,
      exercise: 'squat',
      source: 'video',
      reps: 8,
      active_seconds: 60,
      observable_seconds: 55,
      form_events: 0,
      fatigue: 8,
      discomfort: false,
      target_reps: 12,
      profile: { weight_kg: 65, height_cm: 170 },
    });
    expect(report.proposal.target_reps).toBeLessThan(12);
    expect(report.source).toBe('video');
    expect(report.trace).toHaveLength(4);
  });

  it('blocks acceptance after a discomfort report', () => {
    const report = analyzeLocal({
      session_id: 'browser-2',
      input_version: 1,
      exercise: 'jumping_jack',
      source: 'camera',
      reps: 4,
      active_seconds: 20,
      observable_seconds: 18,
      form_events: 0,
      fatigue: 3,
      discomfort: true,
      target_reps: 12,
      profile: { weight_kg: 65 },
    });
    expect(report.proposal.blocked).toBe(true);
    expect(() => acceptLocal(report)).toThrow();
  });
});

import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  acceptLocal,
  analyzeLocal,
  clearHistory,
  decideLocal,
  latestReport,
  loadHistory,
  reportFor,
  type LocalSummary,
} from './localCoach';
import planCases from '../../shared/plan_cases.json';

beforeEach(() => {
  const values = new Map<string, string>();
  vi.stubGlobal('sessionStorage', {
    getItem: (k: string) => values.get(k) ?? null,
    setItem: (k: string, v: string) => values.set(k, v),
    removeItem: (k: string) => values.delete(k),
  });
  clearHistory();
});
const base: LocalSummary = {
  session_id: 'versioned',
  input_version: 1,
  exercise: 'squat',
  source: 'simulation',
  reps: 8,
  active_seconds: 60,
  observable_seconds: 55,
  work_seconds: 30,
  rest_seconds: 20,
  form_events: 0,
  fatigue: 8,
  discomfort: false,
  target_reps: 12,
  profile: { weight_kg: 65 },
};

describe('browser coach fallback', () => {
  it.each(planCases)('shared decision contract: $name', (entry) => {
    const result = analyzeLocal({
      ...base,
      work_seconds: undefined,
      rest_seconds: undefined,
      ...entry.input,
    });
    expect(result.proposal).toMatchObject(entry.expected);
  });
  it('rejects stale analysis and stale decisions', () => {
    const old = analyzeLocal(base);
    expect(() => analyzeLocal(base)).toThrow();
    analyzeLocal({ ...base, input_version: 2 });
    expect(() => acceptLocal(old)).toThrow();
  });
  it('decision is idempotent and cannot be reversed', () => {
    const report = analyzeLocal(base);
    const first = acceptLocal(report);
    expect(acceptLocal(report)).toEqual(first);
    expect(() => decideLocal(report, 'rejected')).toThrow();
    expect(first.proposal.decided_at).toBeTruthy();
  });
  it('reject preserves proposal without enabling later acceptance', () => {
    const report = analyzeLocal(base);
    expect(decideLocal(report, 'rejected').proposal.status).toBe('rejected');
    expect(() => acceptLocal(report)).toThrow();
  });
  it('ignores mutated client fields and protects canonical state', () => {
    const report = analyzeLocal(base);
    report.proposal.target_reps = 100;
    expect(acceptLocal(report).proposal.target_reps).toBe(10);
    expect(latestReport()!.proposal.target_reps).toBe(10);
  });
  it('deleting history also removes the current report and pending decisions', () => {
    const report = analyzeLocal({ ...base, persist: true });
    expect(loadHistory()).toHaveLength(1);
    clearHistory();
    expect(loadHistory()).toEqual([]);
    expect(latestReport()).toBeNull();
    expect(() => reportFor(report.session_id)).toThrow();
    expect(() => acceptLocal(report)).toThrow();
  });
  it('does not persist without consent and rejects impossible classified time', () => {
    analyzeLocal(base);
    expect(loadHistory()).toEqual([]);
    expect(() =>
      analyzeLocal({ ...base, input_version: 2, work_seconds: 60, rest_seconds: 0 }),
    ).toThrow();
  });
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

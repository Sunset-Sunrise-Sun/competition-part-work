import { beforeEach, describe, it, expect, vi } from 'vitest';
const flags = vi.hoisted(() => ({ mode: 'browser' }));
vi.mock('./runtime', () => ({
  get runtimeMode() {
    return flags.mode;
  },
}));
import { request, acceptReport, decideReport } from './api';
import { clearHistory } from './localCoach';
import type { Report } from './types';
beforeEach(() => {
  vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => {}, removeItem: () => {} });
  clearHistory();
  flags.mode = 'browser';
});
const summary = (id: string) => ({
  session_id: id,
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
});
describe('runtime authority', () => {
  it('browser flow never sends a network request and explanation is session-specific', async () => {
    const network = vi.fn();
    vi.stubGlobal('fetch', network);
    const first = await request<Report>('/sessions/analyze', {
      method: 'POST',
      body: JSON.stringify(summary('one')),
    });
    await request('/sessions/analyze', {
      method: 'POST',
      body: JSON.stringify({ ...summary('two'), discomfort: true }),
    });
    const explanation = await request<{ text: string }>('/sessions/one/explanation', {
      method: 'POST',
    });
    expect(explanation.text).toBe(first.proposal.reason);
    expect((await acceptReport(first)).proposal.status).toBe('accepted');
    await expect(decideReport(first, 'reject')).rejects.toThrow();
    expect(network).not.toHaveBeenCalled();
  });
  it.each([404, 500])('backend HTTP %s cannot silently create a browser report', async (status) => {
    flags.mode = 'backend';
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('failure', { status })));
    await expect(
      request('/sessions/analyze', { method: 'POST', body: JSON.stringify(summary('failure')) }),
    ).rejects.toThrow('未切换');
    flags.mode = 'browser';
    await expect(request('/sessions/failure/explanation', { method: 'POST' })).rejects.toThrow();
  });
  it('backend network failure remains a failure', async () => {
    flags.mode = 'backend';
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    await expect(request('/health')).rejects.toThrow('offline');
  });
});

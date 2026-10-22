import {
  analyzeLocal,
  clearHistory,
  decideLocal,
  estimateFood,
  reportFor,
  loadHistory,
  type LocalSummary,
} from './localCoach';
import { runtimeMode } from './runtime';
import type { Report } from './types';
import contract from '../../shared/contract.json';

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (runtimeMode === 'browser') return localRequest<T>(path, options);
  const response = await fetch('/api' + path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
    signal: AbortSignal.timeout(25000),
  });
  if (!response.ok)
    throw new Error(
      `本地后端请求失败 (${response.status})，未切换计算模式：${await response.text()}`,
    );
  return response.json();
}

export const decideReport = (report: Report, decision: 'accept' | 'reject') =>
  request<Report>(`/sessions/${report.session_id}/${decision}`, {
    method: 'POST',
    body: JSON.stringify({
      input_version: report.input_version,
      proposal_id: report.proposal.proposal_id,
    }),
  });
export const acceptReport = (report: Report) => decideReport(report, 'accept');

function localRequest<T>(path: string, options: RequestInit = {}): T {
  const method = (options.method || 'GET').toUpperCase();
  const body = options.body ? JSON.parse(String(options.body)) : null;
  if (path === '/health' && method === 'GET')
    return {
      status: 'browser',
      version: '0.2.0',
      schema_version: contract.schema_version,
      policy_version: contract.policy_version,
    } as T;
  if (path === '/sessions/analyze' && method === 'POST')
    return analyzeLocal(body as LocalSummary) as T;
  const route = path.match(/^\/sessions\/([^/]+)\/(accept|reject|explanation)$/);
  if (route && method === 'POST') {
    const report = reportFor(route[1]);
    if (route[2] === 'explanation')
      return {
        text: report.proposal.reason,
        runtime: 'browser',
        input_version: report.input_version,
      } as T;
    return decideLocal(
      {
        ...report,
        input_version: body?.input_version,
        proposal: {
          ...report.proposal,
          proposal_id: body?.proposal_id ?? report.proposal.proposal_id,
        },
      },
      route[2] === 'accept' ? 'accepted' : 'rejected',
    ) as T;
  }
  if (path === '/history' && method === 'GET') return loadHistory() as T;
  if (path === '/history' && method === 'DELETE') {
    clearHistory();
    return { deleted: true } as T;
  }
  if (path === '/nutrition/estimate' && method === 'POST') {
    const first = Array.isArray(body) ? body[0] : body;
    const entry = first ?? { query: '米饭', grams: 150 };
    return estimateFood(entry.query || entry.food_id || '', entry.grams, entry) as T;
  }
  throw new Error('浏览器模式不支持此接口。');
}

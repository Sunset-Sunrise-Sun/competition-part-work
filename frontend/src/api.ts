import {
  acceptLocal,
  analyzeLocal,
  clearHistory,
  estimateFood,
  latestReport,
  loadHistory,
  type LocalSummary,
} from './localCoach';
import type { Report } from './types';

function isNetworkError(error: unknown): boolean {
  return !(error instanceof Error && error.message.startsWith('服务请求失败'));
}

function isPublicStaticHost(): boolean {
  return typeof location !== 'undefined' && location.hostname.endsWith('github.io');
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (isPublicStaticHost()) return localRequest<T>(path, options);
  try {
    const response = await fetch('/api' + path, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...options.headers },
      signal: AbortSignal.timeout(25000),
    });
    if (!response.ok) {
      const text = await response.text();
      if (response.status >= 500 || response.status === 404 || response.status === 405 || !/^\s*[{[]/.test(text)) {
        return localRequest<T>(path, options);
      }
      throw new Error(`服务请求失败 (${response.status})：${text}`);
    }
    return response.json();
  } catch (error) {
    if (!isNetworkError(error)) throw error;
    return localRequest<T>(path, options);
  }
}

export const acceptReport = async (report: Report) => {
  try {
    return await request<Report>(`/sessions/${report.session_id}/accept`, {
      method: 'POST',
      body: JSON.stringify({ input_version: report.input_version }),
    });
  } catch (error) {
    if (!isNetworkError(error) && report.trace[0]?.runtime !== 'browser') throw error;
    return acceptLocal(report);
  }
};

function localRequest<T>(path: string, options: RequestInit = {}): T {
  const method = (options.method || 'GET').toUpperCase();
  const body = options.body ? JSON.parse(String(options.body)) : null;
  if (path === '/health') return { status: 'browser', version: '0.1.0' } as T;
  if (path === '/sessions/analyze' && method === 'POST') return analyzeLocal(body as LocalSummary) as T;
  if (path.endsWith('/explanation') && method === 'POST') {
    const reason = latestReport()?.proposal.reason || '浏览器本地模式：规则解释。';
    return { text: reason, runtime: 'browser' } as T;
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
  throw new Error('当前为浏览器本地模式，该接口不可用。');
}

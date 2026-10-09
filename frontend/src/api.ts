import type {Report} from './types';
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch('/api' + path, {...options, headers: {'Content-Type': 'application/json', ...options.headers}, signal: AbortSignal.timeout(25000)});
  if (!response.ok) throw new Error(`服务请求失败 (${response.status})：${await response.text()}`);
  return response.json();
}
export const acceptReport = (report: Report) => request<Report>(`/sessions/${report.session_id}/accept`, {
  method: 'POST', body: JSON.stringify({input_version: report.input_version})});

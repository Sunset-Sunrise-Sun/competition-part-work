import type { Exercise } from './catalog';
import { isExercise } from './catalog';
import { dailyRequirement, sessionEnergy, type ActivityLevel, type Sex } from './energy';
import { estimateFoods } from './foods';
import type { Report, SquatRep } from './types';
import contract from '../../shared/contract.json';
const policy = contract.policy;

export type LocalSummary = {
  schema_version?: string;
  session_id: string;
  input_version: number;
  exercise: Exercise;
  source: 'simulation' | 'camera' | 'video';
  reps: number;
  active_seconds: number;
  observable_seconds: number;
  work_seconds?: number;
  rest_seconds?: number;
  form_events: number;
  fatigue: number;
  discomfort: boolean;
  target_reps: number;
  persist?: boolean;
  profile: {
    weight_kg: number;
    height_cm?: number;
    age_years?: number;
    sex?: Sex;
    activity?: ActivityLevel;
    experience?: string;
    goal?: string;
  };
  rep_details?: SquatRep[];
};

const HISTORY_KEY = 'localfit-browser-history';
let lastReport: Report | null = null;
const reports = new Map<string, Report>();

export function reportFor(sessionId: string): Report {
  const report = reports.get(sessionId);
  if (!report) throw new Error('当前会话不存在或已清除，请重新训练。');
  return structuredClone(report);
}

export function analyzeLocal(summary: LocalSummary): Report {
  if (summary.schema_version !== undefined && summary.schema_version !== contract.schema_version)
    throw new Error('不支持的数据合同版本。');
  if (
    typeof summary.discomfort !== 'boolean' ||
    (summary.persist !== undefined && typeof summary.persist !== 'boolean') ||
    (summary.profile.goal !== undefined && !['habit', 'fitness'].includes(summary.profile.goal)) ||
    (summary.profile.experience !== undefined &&
      !['beginner', 'regular'].includes(summary.profile.experience))
  )
    throw new Error('布尔值或用户目标参数无效。');
  if (
    !isExercise(summary.exercise) ||
    !['simulation', 'camera', 'video'].includes(summary.source) ||
    !/^[a-zA-Z0-9_-]{1,100}$/.test(summary.session_id)
  )
    throw new Error('动作、来源或会话标识无效。');
  const previous = reports.get(summary.session_id);
  if (previous && summary.input_version <= previous.input_version)
    throw new Error('拒绝过期或重复的摘要版本。');
  for (const [value, min, max] of [
    [summary.profile.height_cm, 120, 220],
    [summary.profile.age_years, 14, 80],
  ] as const) {
    if (value !== undefined && (!Number.isFinite(value) || value < min || value > max))
      throw new Error('身高或年龄无效。');
  }
  if (
    summary.profile.sex !== undefined &&
    !['female', 'male', 'unspecified'].includes(summary.profile.sex)
  )
    throw new Error('公式参数无效。');
  if (
    summary.profile.activity !== undefined &&
    !['sedentary', 'light', 'moderate', 'active'].includes(summary.profile.activity)
  )
    throw new Error('活动参数无效。');
  if (
    !Number.isFinite(summary.active_seconds) ||
    summary.active_seconds < 0 ||
    summary.active_seconds > 86400 ||
    !Number.isFinite(summary.observable_seconds) ||
    summary.observable_seconds < 0 ||
    summary.observable_seconds > summary.active_seconds ||
    !Number.isInteger(summary.input_version) ||
    summary.input_version < 1 ||
    !Number.isInteger(summary.target_reps) ||
    summary.target_reps < 1 ||
    summary.target_reps > 100 ||
    !Number.isFinite(summary.profile.weight_kg) ||
    summary.profile.weight_kg < 30 ||
    summary.profile.weight_kg > 250 ||
    !Number.isInteger(summary.reps) ||
    summary.reps < 0 ||
    summary.reps > 10000 ||
    !Number.isInteger(summary.form_events) ||
    summary.form_events < 0 ||
    summary.form_events > 10000 ||
    !Number.isInteger(summary.fatigue) ||
    summary.fatigue < 0 ||
    summary.fatigue > 10
  )
    throw new Error('训练摘要参数无效。');
  const coverage = Math.min(1, summary.observable_seconds / Math.max(summary.active_seconds, 1));
  const completion = Math.min(1, summary.reps / summary.target_reps);
  const details = summary.rep_details ?? [];
  if (details.length > 100 || (details.length > 0 && summary.exercise !== 'squat'))
    throw new Error('单次记录当前只支持深蹲，最多 100 条。');
  let previousEnd = -1,
    previousNumber = 0;
  for (const rep of details) {
    if (
      ![
        rep.start_seconds,
        rep.bottom_seconds,
        rep.end_seconds,
        rep.descent_seconds,
        rep.ascent_seconds,
        rep.min_angle_degrees,
      ].every(Number.isFinite) ||
      !Number.isInteger(rep.number) ||
      rep.number <= previousNumber ||
      rep.number > summary.reps ||
      rep.start_seconds < 0 ||
      rep.start_seconds < previousEnd ||
      rep.bottom_seconds < rep.start_seconds ||
      rep.end_seconds < rep.bottom_seconds ||
      rep.end_seconds > summary.active_seconds + 0.001 ||
      rep.min_angle_degrees < 0 ||
      rep.min_angle_degrees > 180 ||
      !['within_rule', 'below_rule', 'unobservable'].includes(rep.rom) ||
      Math.abs(rep.descent_seconds - (rep.bottom_seconds - rep.start_seconds)) > 0.001 ||
      Math.abs(rep.ascent_seconds - (rep.end_seconds - rep.bottom_seconds)) > 0.001
    )
      throw new Error('单次记录时序或幅度无效。');
    previousEnd = rep.end_seconds;
    previousNumber = rep.number;
  }
  const rom_counts = {
    within_rule: details.filter((r) => r.rom === 'within_rule').length,
    below_rule: details.filter((r) => r.rom === 'below_rule').length,
    unobservable: details.filter((r) => r.rom === 'unobservable').length,
  };
  const blocked = summary.discomfort;
  const lowEvidence =
    coverage < policy.minimum_coverage || summary.active_seconds < policy.minimum_seconds;
  let target = summary.target_reps;
  let rest = policy.baseline_rest_seconds;
  let reason = '本次记录暂不支持增加训练量，保持计划并继续观察。';
  if (blocked) reason = '用户报告不适：暂停训练，取消继续训练建议。';
  else if (lowEvidence) reason = '有效观察不足：保持计划，先调整机位或补充训练记录。';
  else if (summary.fatigue >= policy.high_fatigue || completion < policy.minimum_completion) {
    target = Math.max(1, Math.round(target * policy.reduction_factor));
    rest = policy.reduced_rest_seconds;
    reason = '主观疲劳较高或完成度不足，建议减少下一组目标并延长休息。';
  } else if (
    summary.form_events > policy.deviation_limit ||
    rom_counts.below_rule > policy.deviation_limit
  ) {
    rest = policy.deviation_rest_seconds;
    reason = '出现多次可观察偏差或未达到实验幅度，保持次数，增加休息并复核动作。';
  }
  const energy = {
    ...sessionEnergy({
      exercise: summary.exercise,
      weightKg: summary.profile.weight_kg,
      activeSeconds: summary.active_seconds,
      observableSeconds: summary.observable_seconds,
      reps: summary.reps,
      repDetails: details,
      workSeconds: summary.work_seconds,
      restSeconds: summary.rest_seconds,
    }),
    daily: dailyRequirement({
      weightKg: summary.profile.weight_kg,
      heightCm: summary.profile.height_cm ?? 170,
      ageYears: summary.profile.age_years ?? 22,
      sex: summary.profile.sex ?? 'unspecified',
      activity: summary.profile.activity ?? 'light',
      goal: summary.profile.goal,
    }),
  };
  const now = new Date().toISOString();
  const report: Report = {
    schema_version: contract.schema_version,
    policy_version: contract.policy_version,
    session_id: summary.session_id,
    input_version: summary.input_version,
    source: summary.source,
    coverage: Math.round(coverage * 1000) / 1000,
    completion: Math.round(completion * 1000) / 1000,
    saved: Boolean(summary.persist),
    rep_details: details,
    energy,
    proposal: {
      target_reps: target,
      rest_seconds: rest,
      reason,
      blocked,
      status: blocked ? 'blocked' : 'pending',
      proposal_id: `${summary.session_id}:${summary.input_version}`,
      decided_at: null,
    },
    trace: [
      {
        role: 'training_analyst',
        runtime: 'browser',
        decision: '汇总动作证据；识别覆盖率不足时不判断动作质量。',
        evidence: { reps: summary.reps, completion, coverage, experimental_rom: rom_counts },
        timestamp: now,
      },
      {
        role: 'plan_adapter',
        runtime: 'browser',
        decision: reason,
        evidence: { fatigue: summary.fatigue, discomfort: blocked, low_evidence: lowEvidence },
        timestamp: now,
      },
      {
        role: 'safety_gate',
        runtime: 'browser',
        decision: blocked ? '阻止继续训练。' : '候选计划通过预设规则，等待用户确认。',
        evidence: { blocked, target_reps: target, rest_seconds: rest },
        timestamp: now,
      },
      {
        role: 'reporter',
        runtime: 'browser',
        decision: '生成可追踪摘要，不推断医疗状态。',
        evidence: { source: summary.source, energy },
        timestamp: now,
      },
    ],
  };
  // Commit memory only after requested persistence succeeds; the same version can retry on failure.
  if (summary.persist) saveHistory(report);
  lastReport = structuredClone(report);
  reports.set(summary.session_id, structuredClone(report));
  if (reports.size > 100) reports.delete(reports.keys().next().value!);
  return report;
}

export function latestReport() {
  return lastReport ? structuredClone(lastReport) : null;
}

export function decideLocal(report: Report, decision: 'accepted' | 'rejected'): Report {
  const current = reportFor(report.session_id);
  if (
    current.input_version !== report.input_version ||
    current.proposal.proposal_id !== report.proposal.proposal_id
  )
    throw new Error('提案已过期，请查看当前版本。');
  if (current.proposal.blocked) throw new Error('不适报告已阻止继续训练。');
  if (current.proposal.status === decision) return current;
  if (current.proposal.status !== 'pending') throw new Error('已作出的决定不能被覆盖。');
  const next = {
    ...current,
    proposal: { ...current.proposal, status: decision, decided_at: new Date().toISOString() },
  };
  if (current.saved) saveHistory(next);
  reports.set(next.session_id, structuredClone(next));
  lastReport = next;
  return structuredClone(next);
}

export const acceptLocal = (report: Report) => decideLocal(report, 'accepted');

export function estimateFood(
  query: string,
  grams?: number,
  extra?: { food_id?: string; kcal_per_100g?: number },
) {
  return estimateFoods([
    { query, food_id: extra?.food_id, grams, kcal_per_100g: extra?.kcal_per_100g },
  ]);
}

export function loadHistory(): Report[] {
  try {
    const items = JSON.parse(sessionStorage.getItem(HISTORY_KEY) || '[]');
    return Array.isArray(items)
      ? items
          .filter(
            (item) =>
              item &&
              typeof item.session_id === 'string' &&
              item.proposal &&
              Array.isArray(item.trace),
          )
          .slice(0, 20)
      : [];
  } catch {
    return [];
  }
}

export function clearHistory() {
  try {
    sessionStorage.removeItem(HISTORY_KEY);
  } finally {
    reports.clear();
    lastReport = null;
  }
}

function saveHistory(report: Report) {
  const items = loadHistory().filter((item) => item.session_id !== report.session_id);
  items.unshift(report);
  sessionStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, 20)));
}

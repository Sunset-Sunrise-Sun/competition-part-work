import { dailyRequirement, sessionEnergy, type ActivityLevel, type Sex } from './energy';
import type { Report, SquatRep } from './types';

export type LocalSummary = {
  session_id: string;
  input_version: number;
  exercise: 'squat' | 'jumping_jack' | 'pull_up' | 'jump_rope';
  source: 'simulation' | 'camera' | 'video';
  reps: number;
  active_seconds: number;
  observable_seconds: number;
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

const FOODS: Record<string, [string, number]> = {
  rice: ['熟米饭', 130],
  egg: ['鸡蛋', 143],
  milk: ['全脂牛奶', 61],
  broccoli: ['西兰花', 34],
};

const HISTORY_KEY = 'localfit-browser-history';
let lastReport: Report | null = null;

export function analyzeLocal(summary: LocalSummary): Report {
  const coverage = Math.min(1, summary.observable_seconds / Math.max(summary.active_seconds, 1));
  const completion = Math.min(1, summary.reps / summary.target_reps);
  const details = summary.rep_details ?? [];
  const rom_counts = {
    within_rule: details.filter((r) => r.rom === 'within_rule').length,
    below_rule: details.filter((r) => r.rom === 'below_rule').length,
    unobservable: details.filter((r) => r.rom === 'unobservable').length,
  };
  const blocked = summary.discomfort;
  const lowEvidence = coverage < 0.6 || summary.active_seconds < 10;
  let target = summary.target_reps;
  let rest = 60;
  let reason = '本次记录暂不支持增加训练量，保持计划并继续观察。';
  if (blocked) reason = '用户报告不适：暂停训练，取消继续训练建议。';
  else if (lowEvidence) reason = '有效观察不足：保持计划，先调整机位或补充训练记录。';
  else if (summary.fatigue >= 7 || completion < 0.7) {
    target = Math.max(1, Math.round(target * 0.8));
    rest = 90;
    reason = '主观疲劳较高或完成度不足，建议减少下一组目标并延长休息。';
  } else if (summary.form_events > 2 || rom_counts.below_rule > 2) {
    rest = 75;
    reason = '出现多次可观察偏差或未达到实验幅度，保持次数，增加休息并复核动作。';
  }
  const energy = {
    ...sessionEnergy({
      exercise: summary.exercise,
      weightKg: summary.profile.weight_kg,
      activeSeconds: summary.active_seconds,
      observableSeconds: summary.observable_seconds,
      repDetails: details,
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
  lastReport = report;
  if (summary.persist) saveHistory(report);
  return report;
}

export function latestReport() {
  return lastReport;
}

export function acceptLocal(report: Report): Report {
  if (report.proposal.blocked) throw new Error('不适报告已阻止继续训练。');
  const next = {
    ...report,
    proposal: { ...report.proposal, status: 'accepted' },
  };
  if (report.saved) saveHistory(next);
  return next;
}

export function estimateFood(foodId: string, grams: number) {
  const item = FOODS[foodId];
  if (!item) throw new Error('未知食品条目');
  const total = Math.round((item[1] * grams) / 10) / 10;
  return {
    total_kcal: total,
    note: '示例数据，尚未完成食品条目及烹饪方式核验，仅供功能演示。浏览器本地计算。',
  };
}

export function loadHistory(): Report[] {
  try {
    return JSON.parse(sessionStorage.getItem(HISTORY_KEY) || '[]');
  } catch {
    return [];
  }
}

export function clearHistory() {
  sessionStorage.removeItem(HISTORY_KEY);
}

function saveHistory(report: Report) {
  const items = loadHistory().filter((item) => item.session_id !== report.session_id);
  items.unshift(report);
  sessionStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, 20)));
}

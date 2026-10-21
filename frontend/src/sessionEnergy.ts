import catalog from '../../shared/energy_catalog.json';
import type { Exercise } from './catalog';
import type { SquatRep } from './types';

export function sessionEnergy(input: {
  exercise: Exercise;
  weightKg: number;
  activeSeconds: number;
  observableSeconds: number;
  reps?: number;
  repDetails?: SquatRep[];
  workSeconds?: number;
  restSeconds?: number;
}) {
  const spec = catalog[input.exercise];
  const total = input.activeSeconds,
    observed = input.observableSeconds;
  if (
    ![total, observed, input.weightKg].every(Number.isFinite) ||
    total < 0 ||
    observed < 0 ||
    observed > total ||
    input.weightKg < 30 ||
    input.weightKg > 250
  )
    throw new Error('能耗输入无效。');
  const explicit = input.workSeconds !== undefined || input.restSeconds !== undefined;
  if (explicit && (input.workSeconds === undefined || input.restSeconds === undefined))
    throw new Error('活动与静止时长必须一起提供。');
  const phases = (input.repDetails ?? [])
    .filter((r) => r.rom !== 'unobservable')
    .reduce((sum, r) => sum + r.descent_seconds + r.ascent_seconds, 0);
  const work = explicit ? input.workSeconds! : Math.min(phases, observed, total);
  const rest = explicit ? input.restSeconds! : 0;
  if (
    ![work, rest].every(Number.isFinite) ||
    work < 0 ||
    rest < 0 ||
    work + rest > observed + 0.001
  )
    throw new Error('活动和静止时长不能超过有效观察时长。');
  const unknown = Math.max(0, total - work - rest);
  const round = (n: number) => Math.round((n + Number.EPSILON) * 10) / 10;
  const low = ((spec.work[0] * work + spec.rest * rest) * input.weightKg) / 3600;
  const high = ((spec.work[1] * work + spec.rest * rest) * input.weightKg) / 3600;
  const basal = (input.weightKg * (work + rest)) / 3600;
  return {
    low_kcal: round(low),
    high_kcal: round(high),
    net_low_kcal: round(Math.max(0, low - basal)),
    net_high_kcal: round(Math.max(0, high - basal)),
    work_seconds: round(work),
    rest_seconds: round(rest),
    unknown_seconds: round(unknown),
    available: work + rest > 0,
    met_work: spec.work,
    met_rest: spec.rest,
    compendium_id: spec.id,
    kind: 'observed_segments_scenario',
    note: `仅估算已分类片段：活动 ${round(work)} 秒、静止 ${round(rest)} 秒、未知 ${round(unknown)} 秒。未知未计入；活动/静止为待验证视觉规则，MET 为情景假设。总消耗包含静息，净消耗扣除已分类片段的 1 MET；不是完整训练实测值。`,
  };
}

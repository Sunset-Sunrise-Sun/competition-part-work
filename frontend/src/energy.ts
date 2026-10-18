import { EXERCISES, type Exercise } from './catalog';
import type { SquatRep } from './types';

export type ActivityLevel = 'sedentary' | 'light' | 'moderate' | 'active';
export type Sex = 'female' | 'male' | 'unspecified';

const FALLBACK = { work: [4, 6] as const, rest: 1.5, id: '02000', label: '一般健身活动' };
const PAL: Record<ActivityLevel, number> = {
  sedentary: 1.2,
  light: 1.375,
  moderate: 1.55,
  active: 1.725,
};

export function mifflinBmr(sex: Sex, weightKg: number, heightCm: number, ageYears: number) {
  const base = 10 * weightKg + 6.25 * heightCm - 5 * ageYears;
  if (sex === 'male') return base + 5;
  if (sex === 'female') return base - 161;
  return base - 78;
}

export function dailyRequirement(input: {
  weightKg: number;
  heightCm: number;
  ageYears: number;
  sex: Sex;
  activity: ActivityLevel;
  goal?: string;
}) {
  const pal = PAL[input.activity] ?? 1.375;
  const bmr = mifflinBmr(input.sex, input.weightKg, input.heightCm, input.ageYears);
  const tdee = bmr * pal;
  const need = input.goal === 'fitness' ? tdee + 200 : tdee;
  return {
    bmr_kcal: Math.round(bmr),
    tdee_kcal: Math.round(tdee),
    need_kcal: Math.round(need),
    pal,
    formula: 'Mifflin-St Jeor × 活动系数',
    note: '每日热量需求为情景估算，不是处方；健身目标按维持量上浮约 200 kcal。',
  };
}

function typicalRepSeconds(exercise: Exercise) {
  const family = EXERCISES[exercise]?.family;
  if (family === 'rope' || family === 'bounce' || family === 'high_knee' || family === 'jog' || family === 'punch' || family === 'climber' || family === 'circle')
    return 0.6;
  if (family === 'hold_plank' || family === 'hold_squat') return 8;
  if (family === 'burpee') return 4;
  return 2;
}

export function sessionEnergy(input: {
  exercise: Exercise;
  weightKg: number;
  activeSeconds: number;
  observableSeconds: number;
  reps?: number;
  repDetails?: SquatRep[];
}) {
  const item = EXERCISES[input.exercise];
  const spec = item ? { work: item.met, rest: item.rest, id: item.id, label: item.name } : FALLBACK;
  const phases = (input.repDetails ?? []).reduce((sum, r) => sum + r.descent_seconds + r.ascent_seconds, 0);
  const fromReps = (input.reps ?? input.repDetails?.length ?? 0) * typicalRepSeconds(input.exercise);
  const fromVisible = Math.max(input.observableSeconds, input.activeSeconds * 0.5) * 0.85;
  let work = Math.max(phases, fromReps, fromVisible);
  if (work <= 0) work = Math.min(input.activeSeconds, input.observableSeconds * 0.7);
  work = Math.min(Math.max(work, 0), input.activeSeconds);
  const rest = Math.max(0, input.activeSeconds - work);
  const hoursW = work / 3600;
  const hoursR = rest / 3600;
  const hoursA = input.activeSeconds / 3600;
  const low = spec.work[0] * input.weightKg * hoursW + spec.rest * input.weightKg * hoursR;
  const high = spec.work[1] * input.weightKg * hoursW + spec.rest * input.weightKg * hoursR;
  const basal = 1 * input.weightKg * hoursA;
  return {
    low_kcal: Math.round(low * 10) / 10,
    high_kcal: Math.round(high * 10) / 10,
    net_low_kcal: Math.round(Math.max(0, low - basal) * 10) / 10,
    net_high_kcal: Math.round(Math.max(0, high - basal) * 10) / 10,
    work_seconds: Math.round(work * 10) / 10,
    rest_seconds: Math.round(rest * 10) / 10,
    note: `${spec.label} ${spec.work[0]}–${spec.work[1]} MET × ${input.weightKg}kg × ${Math.max(1, Math.round(input.activeSeconds))}秒 / 3600。短组只有数 kcal 是公式结果，不是漏算；一小时连续约 ${Math.round(spec.work[0] * input.weightKg)}–${Math.round(spec.work[1] * input.weightKg)} kcal。净消耗已扣 1.0 MET。`,
  };
}

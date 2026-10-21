export type ActivityLevel = 'sedentary' | 'light' | 'moderate' | 'active';
export type Sex = 'female' | 'male' | 'unspecified';

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
    note: `每日需求为情景估算；${input.sex === 'unspecified' ? '未指定公式性别项时使用中间常数 -78，并非个体测量；' : ''}活动系数为自评假设，健身目标 +200 kcal 为演示策略，不是个体处方。`,
  };
}

export { sessionEnergy } from './sessionEnergy';

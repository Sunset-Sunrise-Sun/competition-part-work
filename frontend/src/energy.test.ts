import { describe, expect, it } from 'vitest';
import { dailyRequirement, sessionEnergy } from './energy';

describe('energy', () => {
  it('increases daily need with body size and activity', () => {
    const light = dailyRequirement({
      weightKg: 55,
      heightCm: 160,
      ageYears: 22,
      sex: 'female',
      activity: 'light',
    });
    const active = dailyRequirement({
      weightKg: 80,
      heightCm: 180,
      ageYears: 22,
      sex: 'male',
      activity: 'active',
    });
    expect(active.need_kcal).toBeGreaterThan(light.need_kcal);
    expect(light.bmr_kcal).toBeGreaterThan(1000);
  });

  it('splits session energy into work, rest, gross and net', () => {
    const energy = sessionEnergy({
      exercise: 'squat',
      weightKg: 65,
      activeSeconds: 60,
      observableSeconds: 50,
      repDetails: [
        {
          number: 1,
          start_seconds: 1,
          bottom_seconds: 2,
          end_seconds: 3,
          descent_seconds: 1,
          ascent_seconds: 1,
          min_angle_degrees: 90,
          rom: 'within_rule',
        },
      ],
    });
    expect(energy.work_seconds).toBe(2);
    expect(energy.rest_seconds).toBe(58);
    expect(energy.net_low_kcal).toBeLessThan(energy.low_kcal);
  });
});

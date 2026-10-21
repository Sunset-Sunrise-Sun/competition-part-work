import { describe, expect, it } from 'vitest';
import { dailyRequirement, sessionEnergy } from './energy';
import cases from '../../shared/energy_cases.json';
import dailyCases from '../../shared/daily_cases.json';
import type { Sex, ActivityLevel } from './energy';
import catalog from '../../shared/energy_catalog.json';
import { EXERCISES, type Exercise } from './catalog';

describe('energy', () => {
  it.each(dailyCases)('shared daily rounding: $name', (entry) => {
    expect(
      dailyRequirement({
        ...entry.input,
        sex: entry.input.sex as Sex,
        activity: entry.input.activity as ActivityLevel,
      }),
    ).toMatchObject(entry.expected);
  });
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
    expect(energy.rest_seconds).toBe(0);
    expect(energy.unknown_seconds).toBe(58);
    expect(energy.low_kcal).toBeGreaterThan(0);
    expect(energy.net_low_kcal).toBeLessThanOrEqual(energy.low_kcal);
  });
  it.each(cases)('matches shared cross-runtime golden case: $name', (entry) => {
    const actual = sessionEnergy({ ...entry, exercise: entry.exercise as Exercise });
    expect(actual).toMatchObject(entry.expected);
  });
  it('keeps all catalog parameters aligned with the authoritative shared catalog', () => {
    for (const id of Object.keys(EXERCISES) as Exercise[]) {
      expect(EXERCISES[id].met).toEqual(catalog[id].work);
      expect(EXERCISES[id].rest).toEqual(catalog[id].rest);
    }
  });
  it('rejects invented duration and does not impute work from counts', () => {
    const base = {
      exercise: 'squat' as const,
      weightKg: 65,
      activeSeconds: 10,
      observableSeconds: 0,
      reps: 500,
    };
    expect(sessionEnergy(base).available).toBe(false);
    expect(() => sessionEnergy({ ...base, workSeconds: 10, restSeconds: 0 })).toThrow();
    expect(() => sessionEnergy({ ...base, workSeconds: 0 })).toThrow();
  });
});

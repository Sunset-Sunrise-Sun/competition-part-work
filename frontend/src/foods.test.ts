import { describe, expect, it } from 'vitest';
import { estimateFoods, searchFoods } from './foods';

describe('food matching', () => {
  it('matches common aliases and english names', () => {
    expect(searchFoods('米饭')[0].food.id).toBe('rice');
    expect(searchFoods('rice')[0].food.id).toBe('rice');
    expect(searchFoods('宫保鸡丁')[0].food.id).toBe('kungpao_chicken');
    expect(searchFoods('两个鸡蛋')[0].food.id).toBe('egg');
  });

  it('reads grams from free text and portion words', () => {
    const rice = estimateFoods([{ query: '米饭150克' }]);
    expect(rice.items[0].matched).toBe(true);
    expect(rice.items[0].grams).toBe(150);
    expect(rice.total_kcal).toBeGreaterThan(100);
    const eggs = estimateFoods([{ query: '两个鸡蛋' }]);
    expect(eggs.items[0].grams).toBe(100);
  });

  it('allows unmatched custom kcal', () => {
    const custom = estimateFoods([{ query: '自制能量棒', kcal_per_100g: 400, grams: 50 }]);
    expect(custom.items[0].matched).toBe(false);
    expect(custom.total_kcal).toBe(200);
  });
});

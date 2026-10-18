import rawFoods from './foods.json';

export type FoodItem = {
  id: string;
  name: string;
  kcal: number;
  unit: string;
  unit_g: number;
  group: string;
  aliases: string[];
};

export const FOODS: FoodItem[] = rawFoods;

const UNIT_NAMES = '个只根片块份碗杯瓶袋包勺把球';
const CN_NUM: Record<string, number> = {
  半: 0.5,
  一: 1,
  两: 2,
  二: 2,
  三: 3,
  四: 4,
  五: 5,
  六: 6,
  七: 7,
  八: 8,
  九: 9,
  十: 10,
};

export function normalizeFood(text: string) {
  return text.toLowerCase().replace(/[\s()（）·\-_/.,，。]/g, '');
}

function editDistance(a: string, b: string) {
  if (Math.abs(a.length - b.length) > 2) return 99;
  const row = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let prev = i - 1;
    row[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const cur = row[j];
      row[j] = a[i - 1] === b[j - 1] ? prev : 1 + Math.min(prev, row[j], row[j - 1]);
      prev = cur;
    }
  }
  return row[b.length];
}

export function parseFoodQuery(query: string) {
  const raw = query.trim();
  let text = raw;
  let grams: number | undefined;
  let count: number | undefined;
  let unit: string | undefined;
  const unitHit = raw.match(new RegExp(`(\\d+(?:\\.\\d+)?|[${Object.keys(CN_NUM).join('')}])\\s*([${UNIT_NAMES}])`));
  if (unitHit) {
    count = CN_NUM[unitHit[1]] ?? Number(unitHit[1]);
    unit = unitHit[2];
    text = raw.replace(unitHit[0], ' ').trim();
  }
  const gramMatch = raw.match(/(\d+(?:\.\d+)?)\s*(g|克|ml|毫升)/i);
  if (gramMatch) {
    grams = Number(gramMatch[1]);
    text = text.replace(gramMatch[0], ' ').trim();
  } else if (count == null) {
    const trailing = text.match(/^(.*\D)(\d+(?:\.\d+)?)$/);
    if (trailing && normalizeFood(trailing[1]).length >= 2) {
      text = trailing[1].trim();
      grams = Number(trailing[2]);
    }
  }
  return { text: text || raw, grams, count, unit };
}

export function scoreFood(query: string, food: FoodItem) {
  const q = normalizeFood(query);
  if (!q) return 0;
  const names = [food.id, food.name, ...food.aliases].map(normalizeFood);
  if (names.includes(q)) return 100;
  if (names.some((n) => n.startsWith(q) || q.startsWith(n))) return 86;
  if (names.some((n) => n.includes(q) || q.includes(n))) return 72;
  let best = 0;
  for (const n of names) {
    if (n.length < 2) continue;
    const d = editDistance(q, n);
    if (d <= 1) best = Math.max(best, 64);
    else if (d === 2 && q.length >= 4) best = Math.max(best, 48);
  }
  return best;
}

export function searchFoods(query: string, limit = 8) {
  const { text } = parseFoodQuery(query);
  return FOODS.map((food) => ({ food, score: scoreFood(text, food) }))
    .filter((item) => item.score >= 48)
    .sort((a, b) => b.score - a.score || a.food.name.localeCompare(b.food.name, 'zh'))
    .slice(0, limit);
}

export function resolveFood(query: string, foodId?: string) {
  if (foodId) {
    const exact = FOODS.find((item) => item.id === foodId);
    if (exact) return { food: exact, score: 100, parsed: parseFoodQuery(query || exact.name) };
  }
  const parsed = parseFoodQuery(query);
  const [best] = searchFoods(parsed.text, 1);
  return { food: best?.food, score: best?.score ?? 0, parsed };
}

export function portionGrams(food: FoodItem, parsed: ReturnType<typeof parseFoodQuery>, override?: number) {
  if (override && override > 0) return override;
  if (parsed.grams && parsed.grams > 0) return parsed.grams;
  if (parsed.count && parsed.count > 0) return Math.round(parsed.count * food.unit_g);
  return food.unit_g;
}

export type FoodEstimate = {
  food_id?: string;
  name: string;
  grams: number;
  kcal_per_100g: number;
  total_kcal: number;
  matched: boolean;
  suggestions: { id: string; name: string; kcal: number }[];
  note: string;
};

export function estimateFoods(
  entries: { query?: string; food_id?: string; grams?: number; kcal_per_100g?: number }[],
): { items: FoodEstimate[]; total_kcal: number; note: string } {
  const items = entries.map((entry) => {
    const resolved = resolveFood(entry.query || '', entry.food_id);
    const custom = entry.kcal_per_100g;
    if (!resolved.food && custom == null) {
      return {
        name: entry.query || '未识别食物',
        grams: entry.grams || 100,
        kcal_per_100g: 0,
        total_kcal: 0,
        matched: false,
        suggestions: searchFoods(entry.query || '', 5).map(({ food }) => ({
          id: food.id,
          name: food.name,
          kcal: food.kcal,
        })),
        note: '没有直接匹配。可改写名称，或填写每 100 克热量后估算。',
      };
    }
    const food = resolved.food;
    const kcal = custom ?? food!.kcal;
    const grams = food ? portionGrams(food, resolved.parsed, entry.grams) : entry.grams || 100;
    return {
      food_id: food?.id,
      name: food?.name || entry.query || '自定义食物',
      grams,
      kcal_per_100g: kcal,
      total_kcal: Math.round((kcal * grams) / 10) / 10,
      matched: Boolean(food),
      suggestions: [],
      note: food
        ? `${food.name} 约 ${kcal} kcal/100g，按 ${grams} g 估算。示例成分数据，未核验烹饪方式。`
        : `按自定义 ${kcal} kcal/100g 估算。`,
    };
  });
  return {
    items,
    total_kcal: Math.round(items.reduce((sum, item) => sum + item.total_kcal, 0) * 10) / 10,
    note: '示例食物库本地匹配，不是营养处方；来源为常见食物成分表量级。',
  };
}

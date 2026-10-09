export type Exercise = 'squat' | 'jumping_jack';
export type Point = { x: number; y: number; z?: number; visibility?: number };
export type Metrics = { reps: number; phase: string; quality: boolean; hint: string; angle: number; events: number };
export type Report = { session_id: string; input_version: number; source: string; coverage: number; completion: number;
  saved: boolean; energy: {low_kcal: number; high_kcal: number; note: string};
  proposal: {target_reps: number; rest_seconds: number; reason: string; blocked: boolean; status: string};
  trace: {role: string; runtime: string; decision: string; evidence: Record<string, unknown>; timestamp: string}[] };

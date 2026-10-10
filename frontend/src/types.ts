export type Exercise = 'squat' | 'jumping_jack';
export type Point = { x: number; y: number; z?: number; visibility?: number };
export type SquatRep = {
  number: number;
  start_seconds: number;
  bottom_seconds: number;
  end_seconds: number;
  descent_seconds: number;
  ascent_seconds: number;
  min_angle_degrees: number;
  rom: 'within_rule' | 'below_rule' | 'unobservable';
};
export type Metrics = {
  reps: number;
  phase: string;
  quality: boolean;
  hint: string;
  angle: number;
  events: number;
  squatReps: SquatRep[];
};
export type Report = {
  session_id: string;
  input_version: number;
  source: string;
  coverage: number;
  completion: number;
  saved: boolean;
  rep_details: SquatRep[];
  energy: { low_kcal: number; high_kcal: number; note: string };
  proposal: {
    target_reps: number;
    rest_seconds: number;
    reason: string;
    blocked: boolean;
    status: string;
  };
  trace: {
    role: string;
    runtime: string;
    decision: string;
    evidence: Record<string, unknown>;
    timestamp: string;
  }[];
};

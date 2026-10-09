import { describe, expect, it } from 'vitest';
import { ExerciseEngine, jointAngle, simulatedPose } from './engine';
describe('exercise engine', () => {
  it('computes joint angle and rejects degenerate geometry', () => {
    expect(jointAngle({x:0,y:0}, {x:0,y:1}, {x:1,y:1})).toBeCloseTo(90);
    expect(jointAngle({x:0,y:0}, {x:0,y:0}, {x:1,y:1})).toBeNaN();
  });
  it.each(['squat', 'jumping_jack'] as const)('counts complete %s cycles', exercise => {
    const engine = new ExerciseEngine(exercise);
    let result;
    for (let t = 0; t < 12000; t += 50) result = engine.update(simulatedPose(t, exercise), t);
    expect(result!.reps).toBeGreaterThan(3);
    expect(result!.reps).toBeLessThan(8);
  });
  it('does not count invisible poses', () => {
    const engine = new ExerciseEngine('squat');
    let result;
    for (let t=0;t<12000;t+=50) result = engine.update(simulatedPose(t,'squat').map(p=>({...p,visibility:0})),t);
    expect(result!.reps).toBe(0);
    expect(result!.quality).toBe(false);
  });
  it('does not bridge a long tracking gap into a repetition', () => {
    const engine = new ExerciseEngine('squat');
    for(let t=700;t<1400;t+=50) engine.update(simulatedPose(1100,'squat'),t);
    engine.update([],1500); engine.update([],2200);
    let result;
    for(let t=2250;t<3000;t+=50) result=engine.update(simulatedPose(0,'squat'),t);
    expect(result!.reps).toBe(0);
  });
});

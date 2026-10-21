import { describe, it, expect } from 'vitest';
import { ActivityTracker } from './activity';
import { simulatedPose } from './engine';
describe('causal movement segments', () => {
  it('stationary visible points are not exercise', () => {
    const tracker = new ActivityTracker(),
      p = simulatedPose(0, 'squat');
    expect(tracker.update(p, 0, true)).toBe('unknown');
    expect(tracker.update(p, 100, true)).toBe('rest');
  });
  it('counts movement and clears the movement latch after occlusion', () => {
    const tracker = new ActivityTracker();
    tracker.update(simulatedPose(0, 'squat'), 0, true);
    expect(tracker.update(simulatedPose(800, 'squat'), 100, true)).toBe('work');
    expect(tracker.update([], 200, false)).toBe('unknown');
    expect(tracker.update(simulatedPose(800, 'squat'), 300, true)).toBe('unknown');
    expect(tracker.update(simulatedPose(800, 'squat'), 400, true)).toBe('rest');
  });
  it('missing frames and non-increasing time cannot imply activity', () => {
    const tracker = new ActivityTracker(),
      p = simulatedPose(0, 'squat');
    tracker.update(p, 0, true);
    expect(tracker.update(p, 2000, true)).toBe('unknown');
    expect(tracker.update(p, 2000, true)).toBe('unknown');
    expect(tracker.update([], 2100, true)).toBe('unknown');
  });
});

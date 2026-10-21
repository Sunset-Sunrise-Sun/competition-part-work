import { describe, expect, it } from 'vitest';
import {
  POSE_CDN_MODEL,
  POSE_CDN_WASM,
  needsMainThreadPose,
  poseAssetBases,
  poseFromLandmarks,
} from './pose';

describe('pose assets', () => {
  it('prefers same-origin wasm then the public CDN', () => {
    expect(poseAssetBases('https://yky666.github.io/ai_health_assistant/', false)).toEqual([
      {
        wasm: 'https://yky666.github.io/ai_health_assistant/wasm',
        model: 'https://yky666.github.io/ai_health_assistant/models/pose_landmarker_lite.task',
      },
      { wasm: POSE_CDN_WASM, model: POSE_CDN_MODEL },
    ]);
  });
  it('strict mode never offers an external model or wasm fallback', () => {
    expect(poseAssetBases('http://127.0.0.1:8000', true)).toEqual([
      {
        wasm: 'http://127.0.0.1:8000/wasm',
        model: 'http://127.0.0.1:8000/models/pose_landmarker_lite.task',
      },
    ]);
  });

  it('maps landmarks and recognizes the module-worker loader failure', () => {
    expect(poseFromLandmarks([{ x: 0.2, y: 0.4, visibility: 0.9 }])).toEqual([
      { x: 0.2, y: 0.4, z: undefined, visibility: 0.9 },
    ]);
    expect(needsMainThreadPose('TypeError: self.importScripts is not a function')).toBe(true);
    expect(needsMainThreadPose('Model not ready')).toBe(false);
  });
});

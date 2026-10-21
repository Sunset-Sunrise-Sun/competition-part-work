import { FilesetResolver, PoseLandmarker } from '@mediapipe/tasks-vision';
import type { Point } from './types';
import { strictOffline } from './runtime';

export const POSE_CDN_WASM = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.32/wasm';
export const POSE_CDN_MODEL =
  'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task';

export type PoseModel = PoseLandmarker;

export function poseAssetBases(origin: string, strict = strictOffline) {
  const base = String(origin || '').replace(/\/$/, '');
  const local = [{ wasm: `${base}/wasm`, model: `${base}/models/pose_landmarker_lite.task` }];
  return strict ? local : [...local, { wasm: POSE_CDN_WASM, model: POSE_CDN_MODEL }];
}

async function createLandmarker(wasmBase: string, modelPath: string) {
  const vision = await FilesetResolver.forVisionTasks(wasmBase);
  return PoseLandmarker.createFromOptions(vision, {
    baseOptions: { modelAssetPath: modelPath, delegate: 'CPU' },
    runningMode: 'VIDEO',
    numPoses: 1,
  });
}

export async function createPoseLandmarker(
  origin: string,
  onFallback?: (message: string) => void,
  strict = strictOffline,
): Promise<PoseLandmarker> {
  const attempts = poseAssetBases(origin, strict);
  let lastError: unknown;
  for (let i = 0; i < attempts.length; i += 1) {
    try {
      return await createLandmarker(attempts[i].wasm, attempts[i].model);
    } catch (error) {
      lastError = error;
      if (i + 1 < attempts.length)
        onFallback?.('本地模型未就绪，已按在线资源模式改用公共资源。' + String(error));
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

export function poseFromLandmarks(
  landmarks: Array<{ x: number; y: number; z?: number; visibility?: number }> | undefined,
): Point[] {
  return (landmarks ?? []).map((point) => ({
    x: point.x,
    y: point.y,
    z: point.z,
    visibility: point.visibility,
  }));
}

export function needsMainThreadPose(message: string) {
  return /importScripts|document is not|not a function|Failed to construct 'Worker'/i.test(message);
}

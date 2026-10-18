import { FilesetResolver, PoseLandmarker } from '@mediapipe/tasks-vision';

let model: PoseLandmarker | null = null;
let chain = Promise.resolve();

async function createLandmarker(wasmBase: string, modelPath: string) {
  const vision = await FilesetResolver.forVisionTasks(wasmBase);
  return PoseLandmarker.createFromOptions(vision, {
    baseOptions: { modelAssetPath: modelPath, delegate: 'CPU' },
    runningMode: 'VIDEO',
    numPoses: 1,
  });
}

self.onmessage = (event: MessageEvent) => {
  const data = event.data;
  chain = chain.then(async () => {
    try {
      if (data.type === 'init') {
        const base = String(data.origin || '').replace(/\/$/, '');
        const localWasm = base + '/wasm';
        const localModel = base + '/models/pose_landmarker_lite.task';
        const cdnWasm = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.32/wasm';
        const cdnModel =
          'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task';
        try {
          model = await createLandmarker(localWasm, localModel);
        } catch (localError) {
          self.postMessage({ type: 'progress', message: '本地模型未就绪，改用公共资源。' + String(localError) });
          model = await createLandmarker(cdnWasm, cdnModel);
        }
        self.postMessage({ type: 'ready' });
      } else if (data.type === 'frame') {
        try {
          if (!model) throw new Error('Model not ready');
          const result = model.detectForVideo(data.bitmap, data.timestamp);
          self.postMessage({
            type: 'pose',
            points: result.landmarks[0] ?? [],
            worldPoints: result.worldLandmarks[0] ?? [],
            timestamp: data.timestamp,
            activeElapsedMs: data.activeElapsedMs,
            aspectRatio: data.bitmap.width / data.bitmap.height,
          });
        } finally {
          data.bitmap.close();
        }
      }
    } catch (error) {
      self.postMessage({ type: 'error', message: String(error) });
    }
  });
};

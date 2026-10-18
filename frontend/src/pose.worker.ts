import { FilesetResolver, PoseLandmarker } from '@mediapipe/tasks-vision';
let model: PoseLandmarker | null = null;
let chain = Promise.resolve();
self.onmessage = (event: MessageEvent) => {
  const data = event.data;
  chain = chain.then(async () => {
    try {
      if (data.type === 'init') {
        const base = String(data.origin || '').replace(/\/$/, '');
        const vision = await FilesetResolver.forVisionTasks(base + '/wasm');
        model = await PoseLandmarker.createFromOptions(vision, {
          baseOptions: {
            modelAssetPath: base + '/models/pose_landmarker_lite.task',
            delegate: 'CPU',
          },
          runningMode: 'VIDEO',
          numPoses: 1,
        });
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

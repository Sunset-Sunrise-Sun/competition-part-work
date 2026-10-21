import { createPoseLandmarker, poseFromLandmarks } from './pose';

let model: Awaited<ReturnType<typeof createPoseLandmarker>> | null = null;
let chain = Promise.resolve();

self.onmessage = (event: MessageEvent) => {
  const data = event.data;
  chain = chain.then(async () => {
    try {
      if (data.type === 'init') {
        model = await createPoseLandmarker(
          String(data.origin || ''),
          (message) => {
            self.postMessage({ type: 'progress', message });
          },
          data.strictOffline !== false,
        );
        self.postMessage({ type: 'ready' });
      } else if (data.type === 'frame') {
        try {
          if (!model) throw new Error('Model not ready');
          const result = model.detectForVideo(data.bitmap, data.timestamp);
          self.postMessage({
            type: 'pose',
            points: poseFromLandmarks(result.landmarks[0]),
            worldPoints: poseFromLandmarks(result.worldLandmarks[0]),
            timestamp: data.timestamp,
            activeElapsedMs: data.activeElapsedMs,
            generation: data.generation,
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

import { mkdir, writeFile, copyFile, readdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root = fileURLToPath(new URL('../', import.meta.url));
const url = 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task';
await mkdir(path.join(root, 'public/models'), { recursive: true });
await mkdir(path.join(root, 'public/wasm'), { recursive: true });
const response = await fetch(url, { signal: AbortSignal.timeout(120000) });
if (!response.ok) throw new Error(`Model download failed: ${response.status}`);
const bytes = Buffer.from(await response.arrayBuffer());
if (bytes.length < 100000) throw new Error('Model asset unexpectedly small');
await writeFile(path.join(root, 'public/models/pose_landmarker_lite.task'), bytes);
const assets = [];
for (const file of await readdir(path.join(root, 'node_modules/@mediapipe/tasks-vision/wasm'))) {
  if (/\.(js|wasm)$/.test(file)) {
    await copyFile(path.join(root, 'node_modules/@mediapipe/tasks-vision/wasm', file), path.join(root, 'public/wasm', file));
    assets.push(file);
  }
}
await writeFile(path.join(root, 'public/models/manifest.json'), JSON.stringify({ source: url,
  sha256: createHash('sha256').update(bytes).digest('hex'), bytes: bytes.length,
  prepared_at: new Date().toISOString(), wasm_assets: assets,
  note: 'Recorded download digest, not an independently trusted upstream signature. Review model license before redistribution.' }, null, 2));
console.log(`Prepared local model (${bytes.length} bytes) and ${assets.length} WASM assets.`);

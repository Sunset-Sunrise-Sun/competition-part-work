// Runs the same TypeScript used in the app; no alternate Python pose implementation.
import { build } from 'vite';
import { readFile, writeFile, mkdir, mkdtemp, rm } from 'node:fs/promises';
import { resolve, dirname, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const [mode, input, output] = process.argv.slice(2);
if (!['plan', 'replay', 'synthetic'].includes(mode) || !input || !output)
  throw new Error(
    'Usage: node frontend/scripts/evaluate.mjs plan|replay INPUT.json OUTPUT.json (synthetic uses - for input)',
  );
await mkdir(resolve(root, '.localrun'), { recursive: true });
const outDir = await mkdtemp(resolve(root, '.localrun/eval-'));
try {
  await build({
    configFile: false,
    root: resolve(root, 'frontend'),
    logLevel: 'error',
    build: {
      ssr: resolve(root, 'frontend/src/evaluationEntry.ts'),
      outDir,
      rollupOptions: { output: { entryFileNames: 'evaluation.mjs' } },
    },
  });
  const runtime = await import(pathToFileURL(resolve(outDir, 'evaluation.mjs')).href);
  const data =
    mode === 'synthetic'
      ? runtime.syntheticClips()
      : JSON.parse(await readFile(resolve(input), 'utf8'));
  const result =
    mode !== 'plan'
      ? runtime.evaluateDataset(data)
      : data.map((summary) => {
          if (summary.persist) throw new Error('Evaluation forbids persistence.');
          return runtime.analyzeLocal(summary);
        });
  if (mode !== 'plan') {
    result.input_sha256 = createHash('sha256').update(JSON.stringify(data)).digest('hex');
    const digest = createHash('sha256');
    for (const path of [
      'frontend/src/engine.ts',
      'frontend/src/activity.ts',
      'frontend/src/replay.ts',
      'shared/contract.json',
    ])
      digest.update((await readFile(resolve(root, path), 'utf8')).replace(/\r\n/g, '\n'));
    result.implementation_sha256 = digest.digest('hex');
  }
  await mkdir(dirname(resolve(output)), { recursive: true });
  await writeFile(resolve(output), JSON.stringify(result, null, 2) + '\n', 'utf8');
  console.log(`Wrote ${mode} evaluation: ${resolve(output)}`);
} finally {
  if (!resolve(outDir).startsWith(resolve(root, '.localrun') + sep))
    throw new Error('Temporary output escaped workspace.');
  await rm(outDir, { recursive: true, force: true });
}

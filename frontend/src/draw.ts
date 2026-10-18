import type { Point } from './types';
import { RAW_CONNECTIONS, type RetargetResult } from './smpl';

export type FitRect = { x: number; y: number; w: number; h: number };

export function syncCanvas(canvas: HTMLCanvasElement): { width: number; height: number } {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const width = Math.max(1, canvas.clientWidth);
  const height = Math.max(1, canvas.clientHeight);
  const nextW = Math.round(width * dpr);
  const nextH = Math.round(height * dpr);
  if (canvas.width !== nextW || canvas.height !== nextH) {
    canvas.width = nextW;
    canvas.height = nextH;
  }
  const ctx = canvas.getContext('2d');
  if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { width, height };
}

export function containRect(srcW: number, srcH: number, dstW: number, dstH: number): FitRect {
  const scale = Math.min(dstW / Math.max(srcW, 1), dstH / Math.max(srcH, 1));
  const w = srcW * scale;
  const h = srcH * scale;
  return { x: (dstW - w) / 2, y: (dstH - h) / 2, w, h };
}

function mapPoint(rect: FitRect, x: number, y: number) {
  return { x: rect.x + x * rect.w, y: rect.y + y * rect.h };
}

function capsule(
  ctx: CanvasRenderingContext2D,
  ax: number,
  ay: number,
  bx: number,
  by: number,
  radius: number,
  color: string,
) {
  const dx = bx - ax;
  const dy = by - ay;
  const len = Math.hypot(dx, dy);
  if (len < 1e-3) return;
  const px = (-dy / len) * radius;
  const py = (dx / len) * radius;
  ctx.beginPath();
  ctx.moveTo(ax + px, ay + py);
  ctx.lineTo(bx + px, by + py);
  ctx.arc(bx, by, radius, Math.atan2(py, px), Math.atan2(-py, -px));
  ctx.lineTo(ax - px, ay - py);
  ctx.arc(ax, ay, radius, Math.atan2(-py, -px), Math.atan2(py, px));
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
}

export function drawVideoFrame(
  ctx: CanvasRenderingContext2D,
  video: HTMLVideoElement | null,
  width: number,
  height: number,
): FitRect {
  ctx.clearRect(0, 0, width, height);
  const vw = video?.videoWidth || 640;
  const vh = video?.videoHeight || 480;
  const rect = containRect(vw, vh, width, height);
  ctx.fillStyle = '#1b2b25';
  ctx.fillRect(0, 0, width, height);
  if (video && video.readyState >= 2) {
    ctx.drawImage(video, rect.x, rect.y, rect.w, rect.h);
  }
  return rect;
}

export function drawRawPose(ctx: CanvasRenderingContext2D, points: Point[], rect: FitRect) {
  ctx.lineWidth = 2;
  ctx.strokeStyle = 'rgba(186, 204, 168, 0.35)';
  for (const [a, b] of RAW_CONNECTIONS) {
    if ((points[a]?.visibility ?? 0) < 0.5 || (points[b]?.visibility ?? 0) < 0.5) continue;
    const pa = mapPoint(rect, points[a].x, points[a].y);
    const pb = mapPoint(rect, points[b].x, points[b].y);
    ctx.beginPath();
    ctx.moveTo(pa.x, pa.y);
    ctx.lineTo(pb.x, pb.y);
    ctx.stroke();
  }
}

export function drawRetargetedOverlay(
  ctx: CanvasRenderingContext2D,
  result: RetargetResult,
  rect: FitRect,
) {
  for (const [a, b] of result.bones) {
    const ja = result.joints[a];
    const jb = result.joints[b];
    if (!ja || !jb || ja.visibility < 0.35 || jb.visibility < 0.35) continue;
    const pa = mapPoint(rect, ja.u, ja.v);
    const pb = mapPoint(rect, jb.u, jb.v);
    const radius = ((result.radii[a] + result.radii[b]) / 2) * Math.min(rect.w, rect.h) * 0.42;
    capsule(ctx, pa.x, pa.y, pb.x, pb.y, Math.max(2.5, Math.min(14, radius)), 'rgba(201, 244, 131, 0.28)');
    ctx.beginPath();
    ctx.moveTo(pa.x, pa.y);
    ctx.lineTo(pb.x, pb.y);
    ctx.lineWidth = 3.5;
    ctx.strokeStyle = '#c9f483';
    ctx.stroke();
  }
  for (const joint of result.joints) {
    if (joint.visibility < 0.35) continue;
    const p = mapPoint(rect, joint.u, joint.v);
    ctx.beginPath();
    ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
    ctx.fillStyle = '#f4f7ea';
    ctx.fill();
  }
}

export function drawAvatar(
  ctx: CanvasRenderingContext2D,
  result: RetargetResult,
  width: number,
  height: number,
  yaw = 0.35,
) {
  ctx.clearRect(0, 0, width, height);
  const bg = ctx.createLinearGradient(0, 0, 0, height);
  bg.addColorStop(0, '#1a2d26');
  bg.addColorStop(1, '#101c18');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, width, height);

  const c = Math.cos(yaw);
  const s = Math.sin(yaw);
  const pelvis = result.joints[0];
  const rotated = result.joints.map((j) => {
    const x = j.x - (pelvis?.x ?? 0);
    const y = j.y - (pelvis?.y ?? 0);
    const z = j.z - (pelvis?.z ?? 0);
    return { x: x * c + z * s, y, z: -x * s + z * c };
  });
  const xs = rotated.map((j) => j.x);
  const ys = rotated.map((j) => j.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const scale = 0.78 * Math.min(width / Math.max(maxX - minX, 0.2), height / Math.max(maxY - minY, 0.2));
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  const projected = rotated.map((j) => ({
    x: width / 2 + (j.x - cx) * scale,
    y: height / 2 - (j.y - cy) * scale,
    z: j.z,
  }));

  ctx.fillStyle = 'rgba(0,0,0,0.22)';
  ctx.beginPath();
  ctx.ellipse(width / 2, height * 0.86, width * 0.2, 8, 0, 0, Math.PI * 2);
  ctx.fill();

  const order = result.bones
    .map(([a, b]) => ({ a, b, z: ((projected[a]?.z ?? 0) + (projected[b]?.z ?? 0)) / 2 }))
    .sort((p, q) => p.z - q.z);

  for (const { a, b, z } of order) {
    const pa = projected[a];
    const pb = projected[b];
    if (!pa || !pb) continue;
    const depth = 0.62 + z * 0.25;
    const radius = Math.max(3.2, Math.min(13, ((result.radii[a] + result.radii[b]) / 2) * height * 0.48));
    capsule(
      ctx,
      pa.x,
      pa.y,
      pb.x,
      pb.y,
      radius,
      `rgba(${150 + depth * 50}, ${190 + depth * 30}, ${130}, 0.92)`,
    );
  }
  for (const point of projected) {
    ctx.beginPath();
    ctx.arc(point.x, point.y, 3.2, 0, Math.PI * 2);
    ctx.fillStyle = '#f6f8ee';
    ctx.fill();
  }
}

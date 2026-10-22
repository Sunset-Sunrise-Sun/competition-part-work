import { useEffect, useRef, useState } from 'react';
import {
  Activity,
  ArrowRight,
  Camera,
  Check,
  ClipboardList,
  Download,
  Flame,
  Leaf,
  LockKeyhole,
  Pause,
  Play,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
  Users,
} from 'lucide-react';
import { EXERCISE_GROUPS, EXERCISE_IDS, EXERCISES, exerciseLabel, isExercise } from './catalog';
import { ExerciseEngine, simulatedPose } from './engine';
import { acceptReport, decideReport, request } from './api';
import { ActivityTracker, type ActivityState } from './activity';
import { LandmarkRecorder, type ReplayClip } from './replay';
import { runtimeMode, strictOffline } from './runtime';
import { drawAvatar, drawRawPose, drawRetargetedOverlay, drawVideoFrame, syncCanvas } from './draw';
import { dailyRequirement, sessionEnergy, type ActivityLevel, type Sex } from './energy';
import { estimateFoods, searchFoods } from './foods';
import { defaultProfile, retargetPose } from './smpl';
import type { BodyModel } from './smpl';
import type { Exercise, Metrics, Point, Report, SourceMode } from './types';
const roleNames: Record<string, string> = {
  training_analyst: '训练分析',
  plan_adapter: '计划调整',
  safety_gate: '规则检查',
  reporter: '报告生成',
};
const emptyMetrics: Metrics = {
  reps: 0,
  phase: 'ready',
  quality: false,
  hint: '选择动作，开始一组训练。',
  angle: 180,
  events: 0,
  squatReps: [],
};

export default function App() {
  const [tab, setTab] = useState('training');
  const [exercise, setExercise] = useState<Exercise>('squat');
  const [showExperimental, setShowExperimental] = useState(false);
  const [sourceMode, setSourceMode] = useState<SourceMode>('simulation');
  const [modelReady, setModelReady] = useState(false);
  const [running, setRunning] = useState(false);
  const [metrics, setMetrics] = useState<Metrics>(emptyMetrics);
  const [elapsed, setElapsed] = useState(0);
  const [weight, setWeight] = useState(65);
  const [height, setHeight] = useState(170);
  const [age, setAge] = useState(22);
  const [sex, setSex] = useState<Sex>('unspecified');
  const [activity, setActivity] = useState<ActivityLevel>('light');
  const [muscleUpper, setMuscleUpper] = useState(0.45);
  const [muscleCore, setMuscleCore] = useState(0.4);
  const [muscleLower, setMuscleLower] = useState(0.45);
  const [bodyModel, setBodyModel] = useState<BodyModel>('smpl');
  const [showRaw, setShowRaw] = useState(true);
  const [target, setTarget] = useState(12);
  const [threshold, setThreshold] = useState(105);
  const [fatigue, setFatigue] = useState(4);
  const [discomfort, setDiscomfort] = useState(false);
  const [persist, setPersist] = useState(false);
  const [captureLandmarks, setCaptureLandmarks] = useState(false);
  const recorder = useRef(new LandmarkRecorder());
  const [report, setReport] = useState<Report | null>(null);
  const [history, setHistory] = useState<Report[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [apiReady, setApiReady] = useState(false);
  const [exerciseQuery, setExerciseQuery] = useState('');
  const [foodQuery, setFoodQuery] = useState('');
  const [grams, setGrams] = useState(150);
  const [customKcal, setCustomKcal] = useState('');
  const [showFoodSuggest, setShowFoodSuggest] = useState(false);
  const [foodBusy, setFoodBusy] = useState(false);
  const [foodError, setFoodError] = useState('');
  const [foodResult, setFoodResult] = useState<{
    total_kcal: number;
    note: string;
    items?: { name: string; grams: number; total_kcal: number; matched: boolean }[];
  } | null>(null);
  const [meal, setMeal] = useState<{ name: string; grams: number; total_kcal: number }[]>([]);
  const [mealConfirmed, setMealConfirmed] = useState(false);
  const [explanation, setExplanation] = useState('');
  const [videoName, setVideoName] = useState('');
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const avatar = useRef<HTMLCanvasElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const videoUrl = useRef('');
  const worker = useRef<Worker | null>(null);
  const poseMain = useRef<{
    detectForVideo: (
      image: HTMLVideoElement | ImageBitmap,
      timestamp: number,
    ) => {
      landmarks: Point[][];
      worldLandmarks: Point[][];
    };
    close?: () => void;
  } | null>(null);
  const ingestPose = useRef<
    (data: {
      points: Point[];
      worldPoints?: Point[];
      activeElapsedMs: number;
      aspectRatio?: number;
      generation: number;
    }) => void
  >(() => {});
  const points = useRef<Point[]>([]);
  const worldPoints = useRef<Point[]>([]);
  const engine = useRef(new ExerciseEngine('squat'));
  const activityTracker = useRef(new ActivityTracker());
  const generation = useRef(0);
  const live = useRef({
    running: false,
    source: 'simulation' as SourceMode,
    ready: false,
    elapsed: 0,
    observable: 0,
    work: 0,
    rest: 0,
    activityState: 'unknown' as ActivityState,
    quality: false,
    lastPose: 0,
    frameBusy: false,
  });
  const metricRef = useRef(emptyMetrics);
  const profileRef = useRef(defaultProfile());
  const showRawRef = useRef(true);

  useEffect(() => {
    request('/health')
      .then(() => setApiReady(true))
      .catch(() => setApiReady(false));
  }, []);
  useEffect(() => {
    live.current.running = running;
  }, [running]);
  useEffect(() => {
    profileRef.current = defaultProfile({
      heightCm: height,
      weightKg: weight,
      muscleUpper,
      muscleCore,
      muscleLower,
      model: bodyModel,
    });
  }, [height, weight, muscleUpper, muscleCore, muscleLower, bodyModel]);
  useEffect(() => {
    showRawRef.current = showRaw;
  }, [showRaw]);
  useEffect(() => {
    engine.current = new ExerciseEngine(exercise, threshold);
    recorder.current = new LandmarkRecorder();
    generation.current++;
    live.current.elapsed = 0;
    live.current.observable = 0;
    live.current.work = 0;
    live.current.rest = 0;
    live.current.activityState = 'unknown';
    activityTracker.current = new ActivityTracker();
    live.current.quality = false;
    metricRef.current = emptyMetrics;
    setMetrics(emptyMetrics);
    setElapsed(0);
    setReport(null);
    setExplanation('');
  }, [exercise, threshold, sourceMode]);

  ingestPose.current = (data) => {
    live.current.frameBusy = false;
    if (data.generation !== generation.current) return;
    points.current = data.points;
    worldPoints.current = data.worldPoints ?? [];
    if (live.current.running && live.current.source !== 'simulation') {
      if (captureLandmarks)
        recorder.current.add(data.points, data.activeElapsedMs, data.aspectRatio ?? 1);
      const result = engine.current.update(data.points, data.activeElapsedMs, data.aspectRatio);
      metricRef.current = result;
      live.current.quality = result.quality;
      live.current.activityState = activityTracker.current.update(
        data.points,
        data.activeElapsedMs,
        result.quality,
        data.aspectRatio,
      );
      live.current.lastPose = performance.now();
      setMetrics(result);
    }
  };

  useEffect(() => {
    let cancelled = false;
    let fallbackStarted = false;
    let poseWorker: Worker | null = null;
    const assetBase = new URL(import.meta.env.BASE_URL, location.href).href.replace(/\/$/, '');
    const origin = assetBase || location.origin;

    const markReady = () => {
      if (cancelled) return;
      live.current.ready = true;
      setModelReady(true);
      setError((prev) => (prev.startsWith('姿态模型') ? '' : prev));
    };
    const startMainThread = async () => {
      try {
        const { createPoseLandmarker } = await import('./pose');
        const model = await createPoseLandmarker(origin, () => {
          if (!cancelled) setError('');
        });
        if (cancelled) {
          model.close();
          return;
        }
        poseMain.current = model;
        markReady();
      } catch (error) {
        if (cancelled) return;
        live.current.frameBusy = false;
        live.current.ready = false;
        setModelReady(false);
        setError('姿态模型未就绪：' + String(error));
      }
    };
    const abandonWorker = () => {
      poseWorker?.terminate();
      poseWorker = null;
      worker.current = null;
    };
    const startMainThreadOnce = () => {
      if (fallbackStarted || cancelled || live.current.ready) return;
      fallbackStarted = true;
      abandonWorker();
      setError('姿态模型改在页面内加载…');
      void startMainThread();
    };

    try {
      // Classic IIFE worker: MediaPipe's WASM loader calls importScripts, which
      // does not exist in `{ type: 'module' }` workers.
      poseWorker = new Worker(new URL('./pose.worker.ts', import.meta.url));
      worker.current = poseWorker;
      poseWorker.onmessage = (event: MessageEvent) => {
        if (cancelled) return;
        if (event.data.type === 'progress') setError('');
        if (event.data.type === 'ready') markReady();
        if (event.data.type === 'error') {
          live.current.frameBusy = false;
          if (!live.current.ready) {
            startMainThreadOnce();
            return;
          }
          setError('姿态识别中断：' + event.data.message);
        }
        if (event.data.type === 'pose') ingestPose.current(event.data);
      };
      poseWorker.onerror = () => {
        startMainThreadOnce();
      };
      poseWorker.postMessage({ type: 'init', origin, strictOffline });
    } catch {
      startMainThreadOnce();
    }

    return () => {
      cancelled = true;
      poseWorker?.terminate();
      worker.current = null;
      poseMain.current?.close?.();
      poseMain.current = null;
    };
  }, []);

  useEffect(() => {
    live.current.source = sourceMode;
    if (sourceMode === 'simulation') {
      stream.current?.getTracks().forEach((track) => track.stop());
      stream.current = null;
      if (video.current) {
        video.current.srcObject = null;
      }
      return;
    }
    points.current = [];
    worldPoints.current = [];
    if (sourceMode === 'camera') {
      let cancelled = false;
      navigator.mediaDevices
        .getUserMedia({ video: { facingMode: 'user', width: 1280, height: 720 }, audio: false })
        .then((s) => {
          if (cancelled) {
            s.getTracks().forEach((t) => t.stop());
            return;
          }
          stream.current = s;
          if (video.current) {
            video.current.srcObject = s;
            video.current.play().catch(() => setError('请允许浏览器播放摄像头画面。'));
          }
        })
        .catch((e) => {
          if (!cancelled) setError('无法打开摄像头：' + String(e));
        });
      return () => {
        cancelled = true;
      };
    }
    attachVideo();
  }, [sourceMode]);

  useEffect(() => {
    const node = video.current;
    if (!node || sourceMode !== 'video') return;
    if (running) node.play().catch(() => setError('无法播放所选视频，请换一个常见编码的文件。'));
    else node.pause();
  }, [running, sourceMode]);

  useEffect(() => {
    let frame = 0,
      last = performance.now(),
      lastDraw = 0;
    const loop = (now: number) => {
      const dt = Math.max(0, (now - last) / 1000);
      last = now;
      if (live.current.running) {
        live.current.elapsed += dt;
        if (live.current.source === 'simulation') {
          points.current = simulatedPose(live.current.elapsed * 1000, exercise);
          worldPoints.current = [];
          const result = engine.current.update(points.current, live.current.elapsed * 1000);
          metricRef.current = result;
          live.current.quality = result.quality;
          live.current.activityState = activityTracker.current.update(
            points.current,
            live.current.elapsed * 1000,
            result.quality,
          );
          live.current.lastPose = now;
        }
        if (dt <= 0.5 && live.current.quality && now - live.current.lastPose < 500) {
          live.current.observable += dt;
          if (live.current.activityState === 'work') live.current.work += dt;
          if (live.current.activityState === 'rest') live.current.rest += dt;
        }
      } else if (live.current.source === 'simulation') {
        points.current = simulatedPose(live.current.elapsed * 1000, exercise);
        worldPoints.current = [];
      }
      if (now - lastDraw > 80) {
        lastDraw = now;
        setElapsed(live.current.elapsed);
        if (live.current.source === 'simulation') setMetrics(metricRef.current);
        const v = video.current,
          currentWorker = worker.current,
          mainModel = poseMain.current;
        if (
          live.current.running &&
          live.current.source !== 'simulation' &&
          live.current.ready &&
          v &&
          v.readyState >= 2 &&
          !live.current.frameBusy &&
          (currentWorker || mainModel)
        ) {
          live.current.frameBusy = true;
          if (mainModel && !currentWorker) {
            try {
              const result = mainModel.detectForVideo(v, now);
              ingestPose.current({
                points: result.landmarks[0] ?? [],
                worldPoints: result.worldLandmarks[0] ?? [],
                activeElapsedMs: live.current.elapsed * 1000,
                generation: generation.current,
                aspectRatio: v.videoWidth / Math.max(v.videoHeight, 1),
              });
            } catch {
              live.current.frameBusy = false;
            }
          } else if (currentWorker) {
            const frameGeneration = generation.current;
            const frameElapsed = live.current.elapsed * 1000;
            createImageBitmap(v)
              .then((bitmap) => {
                if (
                  worker.current !== currentWorker ||
                  !live.current.running ||
                  frameGeneration !== generation.current
                ) {
                  bitmap.close();
                  live.current.frameBusy = false;
                  return;
                }
                currentWorker.postMessage(
                  {
                    type: 'frame',
                    bitmap,
                    timestamp: now,
                    activeElapsedMs: frameElapsed,
                    generation: frameGeneration,
                  },
                  [bitmap],
                );
              })
              .catch(() => {
                live.current.frameBusy = false;
              });
          } else {
            live.current.frameBusy = false;
          }
        }
        const p = points.current;
        const aspect = v && v.videoWidth && v.videoHeight ? v.videoWidth / v.videoHeight : 4 / 3;
        const retargeted = p.length
          ? retargetPose(p, worldPoints.current, aspect, profileRef.current)
          : null;
        const overlay = canvas.current;
        if (overlay) {
          const { width, height } = syncCanvas(overlay);
          const ctx = overlay.getContext('2d');
          if (ctx) {
            const rect = drawVideoFrame(
              ctx,
              live.current.source === 'simulation' ? null : v,
              width,
              height,
            );
            if (showRawRef.current && p.length) drawRawPose(ctx, p, rect);
            if (retargeted) drawRetargetedOverlay(ctx, retargeted, rect);
          }
        }
        const body = avatar.current;
        if (body && retargeted) {
          const { width, height } = syncCanvas(body);
          const ctx = body.getContext('2d');
          if (ctx) drawAvatar(ctx, retargeted, width, height, 0.32 + Math.sin(now / 1800) * 0.18);
        }
      }
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, [exercise]);

  function reset() {
    recorder.current = new LandmarkRecorder();
    generation.current++;
    live.current.running = false;
    setRunning(false);
    engine.current = new ExerciseEngine(exercise, threshold);
    live.current.elapsed = 0;
    live.current.observable = 0;
    live.current.work = 0;
    live.current.rest = 0;
    live.current.activityState = 'unknown';
    activityTracker.current = new ActivityTracker();
    live.current.quality = false;
    metricRef.current = emptyMetrics;
    setMetrics(emptyMetrics);
    setElapsed(0);
    setReport(null);
    setExplanation('');
    setError('');
    if (video.current && sourceMode === 'video') {
      video.current.currentTime = 0;
      video.current.pause();
    }
  }
  function attachVideo() {
    const node = video.current;
    if (!node || !videoUrl.current) return;
    node.srcObject = null;
    if (node.getAttribute('src') !== videoUrl.current) {
      node.src = videoUrl.current;
      node.load();
    }
  }
  function chooseSource(next: SourceMode) {
    live.current.running = false;
    setRunning(false);
    setSourceMode(next);
    setError('');
  }
  function onVideoFile(file?: File) {
    if (!file) return;
    reset();
    if (videoUrl.current) URL.revokeObjectURL(videoUrl.current);
    videoUrl.current = URL.createObjectURL(file);
    setVideoName(file.name);
    setError('');
    if (sourceMode === 'video') attachVideo();
    else chooseSource('video');
    requestAnimationFrame(attachVideo);
  }
  async function toggleRunning() {
    if (!validSettings()) return;
    if (discomfort) {
      setError('已报告不适，训练保持暂停。请结束本组查看报告。');
      return;
    }
    if (sourceMode === 'video' && !videoUrl.current) {
      setError('请先上传一段包含全身的训练视频。');
      return;
    }
    if (sourceMode === 'camera' && !stream.current) {
      try {
        const s = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'user', width: 1280, height: 720 },
          audio: false,
        });
        stream.current = s;
        if (video.current) {
          video.current.srcObject = s;
          await video.current.play();
        }
      } catch (e) {
        setError('无法打开摄像头：' + String(e));
        return;
      }
    }
    if (sourceMode === 'video') {
      attachVideo();
      try {
        await video.current?.play();
      } catch {
        setError('无法播放所选视频，请换一个常见编码的文件。');
        return;
      }
    }
    live.current.running = !live.current.running;
    engine.current.interrupt();
    recorder.current.boundary();
    generation.current++;
    live.current.activityState = 'unknown';
    activityTracker.current = new ActivityTracker();
    setRunning(live.current.running);
    setError('');
  }
  function exportLandmarks() {
    if (exercise !== 'squat' && exercise !== 'jumping_jack') return;
    const clip: ReplayClip = {
      format: 'localfit.landmarks.v1',
      clip_id: `clip-${crypto.randomUUID()}`,
      participant_id: 'TO_LABEL',
      exercise,
      source: sourceMode,
      evidence_kind: sourceMode === 'simulation' ? 'synthetic' : 'recorded_landmarks',
      scenario: 'TO_LABEL',
      reference_reps: null,
      count_eligible: null,
      exclusion_reason: '',
      down_threshold: threshold,
      truncated: recorder.current.truncated,
      frames: recorder.current.frames,
    };
    const url = URL.createObjectURL(
      new Blob([JSON.stringify([clip])], { type: 'application/json' }),
    );
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${clip.clip_id}.json`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function confirmFood(query = foodQuery, amount = grams) {
    if (!query.trim() && !customKcal) {
      setFoodError('请先输入食物名称，或填写自定义热量。');
      return;
    }
    setFoodBusy(true);
    setFoodError('');
    setShowFoodSuggest(false);
    try {
      const result = await request<{
        total_kcal: number;
        note: string;
        items?: {
          name: string;
          grams: number;
          total_kcal?: number;
          kcal?: number;
          matched: boolean;
        }[];
      }>('/nutrition/estimate', {
        method: 'POST',
        body: JSON.stringify([
          {
            query,
            grams: amount,
            kcal_per_100g: customKcal ? Number(customKcal) : undefined,
          },
        ]),
      });
      const items = (result.items ?? []).map((item) => ({
        name: item.name,
        grams: item.grams,
        total_kcal: item.total_kcal ?? item.kcal ?? 0,
        matched: item.matched,
      }));
      setFoodResult({ ...result, items });
      if (items[0] && (items[0].total_kcal > 0 || items[0].matched)) {
        setMeal((prev) => [
          ...prev,
          { name: items[0].name, grams: items[0].grams, total_kcal: items[0].total_kcal },
        ]);
        setMealConfirmed(false);
      } else {
        setFoodError(
          items[0]?.name
            ? '已匹配名称，但热量是 0。请改克数或填写自定义热量。'
            : '没有匹配到食物，请换个名称或填写自定义热量。',
        );
      }
    } catch (e) {
      setFoodError(String(e));
    } finally {
      setFoodBusy(false);
    }
  }
  async function finish() {
    generation.current++;
    live.current.running = false;
    setRunning(false);
    if (!validSettings()) return;
    setBusy(true);
    setError('');
    try {
      const result = await request<Report>('/sessions/analyze', {
        method: 'POST',
        body: JSON.stringify({
          session_id: crypto.randomUUID(),
          input_version: 1,
          exercise,
          source: sourceMode,
          reps: metricRef.current.reps,
          active_seconds: live.current.elapsed,
          observable_seconds: Math.min(live.current.observable, live.current.elapsed),
          work_seconds: live.current.work,
          rest_seconds: live.current.rest,
          form_events: metricRef.current.events,
          rep_details: exercise === 'squat' ? metricRef.current.squatReps : [],
          fatigue,
          discomfort,
          target_reps: target,
          persist,
          profile: {
            weight_kg: weight,
            height_cm: height,
            age_years: age,
            sex,
            activity,
            muscle_upper: muscleUpper,
            muscle_core: muscleCore,
            muscle_lower: muscleLower,
            body_model: bodyModel,
            experience: 'beginner',
            goal: 'habit',
          },
        }),
      });
      setReport(result);
      setTab('report');
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function accept() {
    if (!report) return;
    setBusy(true);
    try {
      const next = await acceptReport(report);
      setReport(next);
      setTarget(next.proposal.target_reps);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  function validSettings() {
    if (
      !Number.isFinite(weight) ||
      weight < 30 ||
      weight > 250 ||
      !Number.isFinite(height) ||
      height < 120 ||
      height > 220 ||
      !Number.isFinite(age) ||
      age < 14 ||
      age > 80 ||
      !Number.isInteger(target) ||
      target < 1 ||
      target > 100
    ) {
      setError('请填写有效设置：体重 30–250kg、身高 120–220cm、年龄 14–80 岁、目标 1–100 次。');
      return false;
    }
    return true;
  }
  function exportReport() {
    if (!report) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }),
    );
    const a = document.createElement('a');
    a.href = url;
    a.download = `localfit-${report.session_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }
  const nav = [
    ['training', '训练空间', Activity],
    ['report', '训练复盘', ClipboardList],
    ['nutrition', '饮食记录', Leaf],
    ['team', '项目协作', Users],
  ] as const;
  const progress = Math.min(100, (metrics.reps / target) * 100);
  const daily = dailyRequirement({
    weightKg: weight,
    heightCm: height,
    ageYears: age,
    sex,
    activity,
    goal: 'habit',
  });
  const liveBurn =
    Number.isFinite(weight) && weight >= 30 && weight <= 250
      ? sessionEnergy({
          exercise,
          weightKg: weight,
          activeSeconds: live.current.elapsed,
          observableSeconds: live.current.observable,
          workSeconds: live.current.work,
          restSeconds: live.current.rest,
          reps: metrics.reps,
          repDetails: metrics.squatReps,
        })
      : {
          available: false,
          low_kcal: 0,
          high_kcal: 0,
          note: '请填写有效体重后估算；不会用默认体重替代无效输入。',
        };
  const sourceLabel =
    sourceMode === 'camera'
      ? '摄像头 · 本地姿态识别'
      : sourceMode === 'video'
        ? '上传视频 · 骨骼重定向'
        : '模拟动作回放 · 非真实测量';
  const canStart =
    sourceMode === 'simulation' ||
    (sourceMode === 'video' && Boolean(videoUrl.current || videoName)) ||
    sourceMode === 'camera';

  return (
    <div className="layout">
      <aside className="sidebar">
        <a className="brand" href="#">
          <span className="brand-icon">
            <Activity size={26} />
          </span>
          <span>
            LocalFit<small>本地健身教练</small>
          </span>
        </a>
        <div className="workspace-label">YOUR WELLNESS SPACE</div>
        <nav>
          {nav.map(([key, label, Icon]) => (
            <button
              key={key}
              className={tab === key ? 'nav active' : 'nav'}
              onClick={() => setTab(key)}
            >
              <Icon size={19} />
              {label}
              {tab === key && <span className="nav-dot" />}
            </button>
          ))}
        </nav>
        <div className="side-bottom">
          <div className="privacy-card">
            <ShieldCheck size={24} />
            <strong>你的训练，留在本地</strong>
            <p>原始音视频不上传。保存摘要由你决定。</p>
            <span className="tiny-pill">LOCAL FIRST</span>
          </div>
          <div className="version">开源原型 · v0.1.0</div>
        </div>
      </aside>
      <main>
        <header>
          <div>
            <span className="eyebrow">MOVE WITH CONFIDENCE</span>
            <h1>
              {tab === 'training'
                ? '让每一次训练，都有反馈。'
                : tab === 'report'
                  ? '看见进步，也理解调整。'
                  : tab === 'nutrition'
                    ? '记录饮食，从确认份量开始。'
                    : '把想法，变成共同的进度。'}
            </h1>
            <p>居家运动 · 原创演示骨架 · 可解释的规则协作</p>
          </div>
          <span className={'status ' + (apiReady ? 'online' : 'browser')}>
            <i />
            {runtimeMode === 'browser'
              ? '浏览器规则模式'
              : apiReady
                ? '本地后端已连接'
                : '后端不可用 · 不自动降级'}
          </span>
        </header>
        {error && (
          <div role="alert" className="alert">
            {error}
          </div>
        )}
        <div className="panel" style={{ marginBottom: 20 }}>
          <strong>
            {runtimeMode === 'browser'
              ? '浏览器计算与标签页内历史'
              : '本地后端计算与授权后的 SQLite 历史'}{' '}
            · {strictOffline ? '仅本机/同源模型资源' : '允许公共资源加载'}
          </strong>
          <p>
            模式在本页会话期间固定，请求失败不会自动切换。切换链接会重载页面并结束当前训练；浏览器摘要关闭标签页后不保留。完全断网需提前下载资源并启动本地服务，公网演示不代表离线安装。
          </p>
          <div className="inline-actions">
            <a className="secondary" href="?runtime=browser">
              浏览器规则 · 仅同源资源
            </a>
            {!location.hostname.endsWith('github.io') && (
              <a className="secondary" href="?runtime=backend">
                本地后端 · 仅同源资源
              </a>
            )}
            <a className="secondary" href={`?runtime=${runtimeMode}&assets=online`}>
              在线资源模式（允许 CDN）
            </a>
          </div>
        </div>
        <div style={{ display: tab === 'training' ? 'block' : 'none' }}>
          <div className="section-top">
            <div>
              <h2>今日训练空间</h2>
              <p>
                优先验收深蹲和开合跳；其余动作保留实验入口。骨架用于展示，不测量体型或推断肌肉。
              </p>
            </div>
            <div className="segmented">
              <button
                disabled={running || busy}
                className={sourceMode === 'simulation' ? 'selected' : ''}
                onClick={() => chooseSource('simulation')}
              >
                模拟演示
              </button>
              <button
                disabled={running || busy}
                className={sourceMode === 'camera' ? 'selected' : ''}
                onClick={() => chooseSource('camera')}
              >
                真实摄像头
              </button>
              <button
                disabled={running || busy}
                className={sourceMode === 'video' ? 'selected' : ''}
                onClick={() => fileInput.current?.click()}
              >
                上传视频
              </button>
            </div>
            <input
              ref={fileInput}
              type="file"
              accept="video/*"
              hidden
              onChange={(e) => onVideoFile(e.target.files?.[0])}
            />
          </div>
          <div className="training-grid">
            <div className="stage-stack">
              <section className="camera-card">
                <div className="camera-heading">
                  <span>
                    <Camera size={16} />
                    {sourceLabel}
                    {sourceMode === 'video' && videoName ? ` · ${videoName}` : ''}
                  </span>
                  <span className="camera-chip">
                    {sourceMode === 'simulation'
                      ? 'DEMO'
                      : modelReady
                        ? bodyModel.toUpperCase()
                        : '模型加载中，仍可先开始'}
                  </span>
                </div>
                <div className="dual-view">
                  <div className="viewport">
                    <video ref={video} muted playsInline loop />
                    <canvas ref={canvas} />
                    {sourceMode === 'simulation' && (
                      <div className="demo-watermark">SIMULATION</div>
                    )}
                    <div className="view-tag">
                      <span className={metrics.quality ? 'dot-good' : 'dot-wait'} />
                      {metrics.quality ? '骨骼已对齐人体' : '等待有效动作'}
                    </div>
                  </div>
                  <div className="avatar-pane">
                    <canvas ref={avatar} />
                    <div className="avatar-label">
                      原创演示骨架 · {bodyModel === 'smplx' ? '扩展关节' : '身体关节'}
                    </div>
                  </div>
                </div>
                <div className="camera-footer">
                  <LockKeyhole size={15} />
                  <span>画面只在当前设备处理 · 亮色为重定向骨骼</span>
                  <span>
                    {Math.floor(elapsed / 60)
                      .toString()
                      .padStart(2, '0')}
                    :
                    {Math.floor(elapsed % 60)
                      .toString()
                      .padStart(2, '0')}
                  </span>
                </div>
              </section>
            </div>
            <section className="coach-card">
              <div className="card-kicker">YOUR TRAINING</div>
              <label className="field-label" htmlFor="exercise-search">
                当前动作
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  disabled={running || busy}
                  checked={showExperimental}
                  onChange={(e) => {
                    setShowExperimental(e.target.checked);
                    if (!e.target.checked && exercise !== 'squat' && exercise !== 'jumping_jack')
                      setExercise('squat');
                  }}
                />
                显示其他实验动作（未完成真实验收）
              </label>
              <input
                id="exercise-search"
                placeholder="搜索动作，如 深蹲 / 俯卧撑 / 波比"
                disabled={running || busy}
                value={exerciseQuery}
                onChange={(e) => setExerciseQuery(e.target.value)}
              />
              <select
                id="exercise"
                disabled={running || busy}
                value={exercise}
                onChange={(e) => {
                  if (isExercise(e.target.value)) setExercise(e.target.value);
                }}
              >
                {EXERCISE_GROUPS.map((group) => {
                  const q = exerciseQuery.trim().toLowerCase();
                  const items = EXERCISE_IDS.filter((id) => {
                    const item = EXERCISES[id];
                    if (item.group !== group) return false;
                    if (!showExperimental && id !== 'squat' && id !== 'jumping_jack') return false;
                    if (!q) return true;
                    return (
                      item.name.includes(exerciseQuery) ||
                      id.includes(q) ||
                      exerciseLabel(id).includes(exerciseQuery)
                    );
                  });
                  if (!items.length) return null;
                  return (
                    <optgroup key={group} label={group}>
                      {items.map((id) => (
                        <option key={id} value={id}>
                          {exerciseLabel(id)}
                          {id === 'squat' || id === 'jumping_jack' ? ' · 核心待实测' : ' · 实验性'}
                        </option>
                      ))}
                    </optgroup>
                  );
                })}
              </select>
              <div className="rep-number">
                {metrics.reps}
                <span>/ {target} 次</span>
              </div>
              <div className="progress">
                <div style={{ width: progress + '%' }} />
              </div>
              <div className="rep-meta">
                <span>本组完成度</span>
                <strong>{Math.round(progress)}%</strong>
              </div>
              {exercise === 'squat' && (
                <p className="muted">
                  达到实验幅度 {metrics.squatReps.filter((r) => r.rom === 'within_rule').length} 次
                  · 幅度不足 {metrics.squatReps.filter((r) => r.rom === 'below_rule').length} 次 ·
                  不可评价 {metrics.squatReps.filter((r) => r.rom === 'unobservable').length} 次
                  <br />
                  次数与幅度分开记录，不代表动作正确或安全。
                </p>
              )}
              <div className="coach-tip">
                <Sparkles size={19} />
                <div>
                  <strong>当前教练提示</strong>
                  <p>
                    {metrics.hint}
                    {!metrics.quality && metrics.unknown_reason
                      ? `（${metrics.unknown_reason}）`
                      : ''}
                  </p>
                </div>
              </div>
              <div className="controls">
                <button
                  className="primary"
                  disabled={busy || !canStart}
                  onClick={() => void toggleRunning()}
                >
                  {running ? <Pause size={17} /> : <Play size={17} />}{' '}
                  {running ? '暂停' : '开始 / 继续'}
                </button>
                <button
                  className="icon-button"
                  aria-label="重置本组"
                  disabled={busy}
                  onClick={reset}
                >
                  <RotateCcw size={18} />
                </button>
                <button
                  className="icon-button"
                  aria-label="上传视频"
                  disabled={busy || running}
                  onClick={() => fileInput.current?.click()}
                >
                  <Upload size={18} />
                </button>
              </div>
              <button className="finish-button" disabled={busy} onClick={finish}>
                {busy ? '生成报告中…' : '结束本组并复盘'}
                <ArrowRight size={17} />
              </button>
              {(exercise === 'squat' || exercise === 'jumping_jack') &&
                sourceMode !== 'simulation' && (
                  <details>
                    <summary>算法评测采集</summary>
                    <label>
                      <input
                        type="checkbox"
                        checked={captureLandmarks}
                        disabled={!captureLandmarks && (running || elapsed > 0)}
                        onChange={(event) => {
                          setCaptureLandmarks(event.target.checked);
                          recorder.current = new LandmarkRecorder();
                        }}
                      />
                      我同意在本页内存记录关键点，用于本次算法评测
                    </label>
                    <p className="muted">
                      仅含坐标与训练时间，不含影像；手动导出后交标注人员。重置本组或关闭页面会清空，最多
                      20,000 帧。
                    </p>
                    {recorder.current.truncated && (
                      <p role="alert">
                        记录已达到上限，请重录较短片段；截断记录不能用于完整组评测。
                      </p>
                    )}
                    <button
                      disabled={running || recorder.current.frames.length === 0}
                      onClick={exportLandmarks}
                    >
                      导出关键点评测 JSON（{recorder.current.frames.length} 帧）
                    </button>
                  </details>
                )}
            </section>
          </div>
          <div className="bottom-grid body-grid">
            <section className="panel">
              <h3>演示骨架与用户输入参数</h3>
              <div className="fields">
                <label>
                  身高 cm
                  <input
                    type="number"
                    min="120"
                    max="220"
                    disabled={running || busy}
                    value={height}
                    onChange={(e) => setHeight(Number(e.target.value))}
                  />
                </label>
                <label>
                  体重 kg
                  <input
                    type="number"
                    min="30"
                    max="250"
                    disabled={running || busy}
                    value={weight}
                    onChange={(e) => setWeight(Number(e.target.value))}
                  />
                </label>
                <label>
                  年龄
                  <input
                    type="number"
                    min="14"
                    max="80"
                    disabled={running || busy}
                    value={age}
                    onChange={(e) => setAge(Number(e.target.value))}
                  />
                </label>
              </div>
              <div className="fields">
                <label>
                  性别
                  <select
                    disabled={running || busy}
                    value={sex}
                    onChange={(e) => setSex(e.target.value as Sex)}
                  >
                    <option value="unspecified">不指定</option>
                    <option value="female">女</option>
                    <option value="male">男</option>
                  </select>
                </label>
                <label>
                  日常活动
                  <select
                    disabled={running || busy}
                    value={activity}
                    onChange={(e) => setActivity(e.target.value as ActivityLevel)}
                  >
                    <option value="sedentary">久坐</option>
                    <option value="light">轻度</option>
                    <option value="moderate">中等</option>
                    <option value="active">活跃</option>
                  </select>
                </label>
              </div>
              <div className="calorie-need">
                <span>每日热量需求（维持）</span>
                <strong>
                  {daily.need_kcal}
                  <small> kcal</small>
                </strong>
                <p>
                  BMR {daily.bmr_kcal} · TDEE {daily.tdee_kcal}
                  。这是每日需求情景，不是本组消耗。{daily.note}
                </p>
              </div>
              <div className="calorie-need session-burn">
                <span>本组消耗估算</span>
                <strong>
                  {liveBurn.available ? `${liveBurn.low_kcal}–${liveBurn.high_kcal}` : '待有效片段'}
                  <small> kcal</small>
                </strong>
                <p>{liveBurn.note}</p>
              </div>
              <label className="field-label" htmlFor="body-model">
                人体模型
              </label>
              <select
                id="body-model"
                disabled={running || busy}
                value={bodyModel}
                onChange={(e) => setBodyModel(e.target.value as BodyModel)}
              >
                <option value="smpl">原创骨架 · 身体关节</option>
                <option value="smplx">原创骨架 · 扩展关节（含推定部分）</option>
              </select>
              <label className="slider-label">
                上肢肌肉 <strong>{Math.round(muscleUpper * 100)}%</strong>
                <input
                  type="range"
                  min="0"
                  max="100"
                  disabled={running || busy}
                  value={Math.round(muscleUpper * 100)}
                  onChange={(e) => setMuscleUpper(Number(e.target.value) / 100)}
                />
              </label>
              <label className="slider-label">
                核心肌肉 <strong>{Math.round(muscleCore * 100)}%</strong>
                <input
                  type="range"
                  min="0"
                  max="100"
                  disabled={running || busy}
                  value={Math.round(muscleCore * 100)}
                  onChange={(e) => setMuscleCore(Number(e.target.value) / 100)}
                />
              </label>
              <label className="slider-label">
                下肢肌肉 <strong>{Math.round(muscleLower * 100)}%</strong>
                <input
                  type="range"
                  min="0"
                  max="100"
                  disabled={running || busy}
                  value={Math.round(muscleLower * 100)}
                  onChange={(e) => setMuscleLower(Number(e.target.value) / 100)}
                />
              </label>
              <p className="muted">
                原创示意骨架按用户输入调整外观，不使用官方 SMPL/SMPL-X 权重或派生参数。
                骨长和粗细是展示假设，不是摄像头测量值；未观测到的手指等关节只作示意。
              </p>
            </section>
            <section className="panel">
              <h3>训练设置</h3>
              <div className="fields">
                <label>
                  本组目标次数
                  <input
                    type="number"
                    min="1"
                    max="100"
                    disabled={running || busy}
                    value={target}
                    onChange={(e) => setTarget(Number(e.target.value))}
                  />
                </label>
              </div>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={showRaw}
                  onChange={(e) => setShowRaw(e.target.checked)}
                />
                同时显示原始 MediaPipe 细线
              </label>
              <details>
                <summary>实验参数与机位要求</summary>
                <p>
                  {EXERCISES[exercise].hint} 当前共 {EXERCISE_IDS.length} 个动作。平板和靠墙静蹲按每
                  8 秒计 1 次。
                </p>
                <label>
                  深蹲下降角度阈值（待验证）
                  <input
                    type="range"
                    min="85"
                    max="125"
                    disabled={running || busy}
                    value={threshold}
                    onChange={(e) => setThreshold(Number(e.target.value))}
                  />
                  {threshold}°
                </label>
              </details>
            </section>
            <section className="panel">
              <h3>你现在的感受</h3>
              <label className="slider-label">
                主观疲劳 <strong>{fatigue} / 10</strong>
                <input
                  type="range"
                  min="0"
                  max="10"
                  value={fatigue}
                  onChange={(e) => setFatigue(Number(e.target.value))}
                />
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={discomfort}
                  onChange={(e) => {
                    setDiscomfort(e.target.checked);
                    if (e.target.checked) {
                      live.current.running = false;
                      setRunning(false);
                    }
                  }}
                />
                我有不适，需要停止
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={persist}
                  onChange={(e) => setPersist(e.target.checked)}
                />
                同意在本机保存本次摘要
              </label>
            </section>
          </div>
        </div>
        {tab === 'report' && (
          <div>
            <div className="section-top">
              <div>
                <h2>训练复盘</h2>
                <p>每条调整都能查看依据，计划由你确认。</p>
              </div>
              <button className="secondary" disabled={!report} onClick={exportReport}>
                <Download size={16} />
                导出 JSON
              </button>
            </div>
            {report ? (
              <>
                <div className="stats-grid">
                  <div className="stat">
                    <span>观察覆盖率</span>
                    <strong>
                      {Math.round(report.coverage * 100)}
                      <small>%</small>
                    </strong>
                  </div>
                  <div className="stat">
                    <span>本组完成度</span>
                    <strong>
                      {Math.round(report.completion * 100)}
                      <small>%</small>
                    </strong>
                  </div>
                  <div className="stat">
                    <span>
                      <Flame size={14} />
                      总消耗情景估算
                    </span>
                    <strong>
                      {report.energy.available === false
                        ? '无法估算'
                        : `${report.energy.low_kcal}–${report.energy.high_kcal}`}
                      <small>kcal</small>
                    </strong>
                  </div>
                </div>
                <p className="muted">
                  {report.source === 'simulation'
                    ? '本次为模拟记录。'
                    : report.source === 'video'
                      ? '本次来自上传视频重定向。'
                      : '本次来自摄像头记录。'}
                  {report.energy.note}{' '}
                  {report.energy.daily
                    ? `每日维持需求约 ${report.energy.daily.need_kcal} kcal，和本组消耗不是同一个数。 `
                    : ''}
                  {report.energy.net_low_kcal != null
                    ? `本组净消耗 ${report.energy.net_low_kcal}–${report.energy.net_high_kcal} kcal。 `
                    : ''}
                  {report.saved ? '摘要已保存至本机。' : '摘要仅暂存在当前会话。'}
                </p>
                {!!report.rep_details?.length && (
                  <section className="panel">
                    <h3>深蹲单次幅度与节奏（最近 100 次）</h3>
                    <p className="muted">
                      下降从角度进入实验区间开始计时；平滑与机位会影响结果。未知不等于动作错误。
                    </p>
                    <div style={{ overflowX: 'auto' }}>
                      <table className="rep-table">
                        <thead>
                          <tr>
                            <th>次数</th>
                            <th>最低膝角</th>
                            <th>下降 / 起身</th>
                            <th>幅度记录</th>
                          </tr>
                        </thead>
                        <tbody>
                          {report.rep_details.map((r) => (
                            <tr key={r.number}>
                              <td>{r.number}</td>
                              <td>{r.min_angle_degrees.toFixed(1)}°</td>
                              <td>
                                {r.descent_seconds.toFixed(2)}s / {r.ascent_seconds.toFixed(2)}s
                              </td>
                              <td>
                                {r.rom === 'within_rule'
                                  ? '达到实验阈值'
                                  : r.rom === 'below_rule'
                                    ? '未达到实验阈值'
                                    : '不可评价'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </section>
                )}
                <div className="report-grid">
                  <section className="panel">
                    <div className="card-kicker">NEXT SET</div>
                    <h3>{report.proposal.blocked ? '训练已暂停' : '下一组建议'}</h3>
                    <div className="plan-values">
                      <span>
                        <b>{report.proposal.target_reps}</b> 目标次数
                      </span>
                      <span>
                        <b>{report.proposal.rest_seconds}</b> 休息秒数
                      </span>
                    </div>
                    <p>{report.proposal.reason}</p>
                    <button
                      className="primary"
                      disabled={
                        busy || report.proposal.blocked || report.proposal.status !== 'pending'
                      }
                      onClick={accept}
                    >
                      <Check size={16} />
                      {report.proposal.status === 'accepted'
                        ? '已确认并更新目标'
                        : report.proposal.status === 'rejected'
                          ? '已拒绝，保留原计划'
                          : '确认下一组计划'}
                    </button>
                    <button
                      className="secondary"
                      disabled={
                        busy || report.proposal.blocked || report.proposal.status !== 'pending'
                      }
                      onClick={async () => {
                        if (!report) return;
                        setBusy(true);
                        try {
                          setReport(await decideReport(report, 'reject'));
                        } catch (e) {
                          setError(String(e));
                        } finally {
                          setBusy(false);
                        }
                      }}
                    >
                      拒绝调整，保持原计划
                    </button>
                    <button
                      className="finish-button"
                      onClick={async () => {
                        try {
                          const r = await request<{ text: string; runtime: string }>(
                            `/sessions/${report.session_id}/explanation`,
                            { method: 'POST' },
                          );
                          setExplanation(r.text + '（' + r.runtime + '）');
                        } catch (e) {
                          setError(String(e));
                        }
                      }}
                    >
                      查看解释
                      <ArrowRight size={16} />
                    </button>
                    {explanation && <p>{explanation}</p>}
                  </section>
                  <section className="panel">
                    <h3>教练协作记录</h3>
                    <p className="muted">结构化结果与依据 · 规则节点执行</p>
                    <div className="trace">
                      {report.trace.map((step, i) => (
                        <details key={step.role}>
                          <summary>
                            <span className="step-number">{i + 1}</span>
                            <strong>{roleNames[step.role]}</strong>
                            <span className="trace-state">完成</span>
                          </summary>
                          <p>{step.decision}</p>
                          <pre>{JSON.stringify(step.evidence, null, 2)}</pre>
                        </details>
                      ))}
                    </div>
                  </section>
                </div>
              </>
            ) : (
              <section className="empty">
                <ClipboardList size={35} />
                <h3>完成第一组训练后，复盘会出现在这里。</h3>
                <button className="primary" onClick={() => setTab('training')}>
                  进入训练空间
                </button>
              </section>
            )}
            <section className="panel history">
              <h3>本机历史摘要</h3>
              <div className="inline-actions">
                <button
                  className="secondary"
                  onClick={async () => {
                    try {
                      setHistory(await request<Report[]>('/history'));
                    } catch (e) {
                      setError(String(e));
                    }
                  }}
                >
                  读取已保存记录
                </button>
                <button
                  className="secondary danger"
                  onClick={async () => {
                    try {
                      await request('/history', { method: 'DELETE' });
                      recorder.current = new LandmarkRecorder();
                      setCaptureLandmarks(false);
                      setHistory([]);
                      setReport(null);
                      setExplanation('');
                    } catch (e) {
                      setError(String(e));
                    }
                  }}
                >
                  <Trash2 size={15} />
                  删除全部本机摘要
                </button>
              </div>
              {history.map((r) => (
                <div className="history-row" key={r.session_id}>
                  <span>
                    {r.source === 'simulation' ? '模拟' : r.source === 'video' ? '视频' : '摄像头'}{' '}
                    · {r.session_id.slice(0, 8)}
                  </span>
                  <span>
                    完成度 {Math.round(r.completion * 100)}% · {r.proposal.reason}
                  </span>
                </div>
              ))}
            </section>
          </div>
        )}
        {tab === 'nutrition' && (
          <div>
            <div className="section-top">
              <div>
                <h2>一份食物，一次确认</h2>
                <p>直接输入名称或别名，例如「米饭150克」「两个鸡蛋」「宫保鸡丁」。</p>
              </div>
              <span className="badge">示例食品库 · 可搜索匹配</span>
            </div>
            <div className="report-grid">
              <section className="panel">
                <Leaf className="leaf-icon" size={30} />
                <h3>添加食物</h3>
                {foodError && (
                  <p role="alert" className="alert">
                    {foodError}
                  </p>
                )}
                <label className="field-label food-search">
                  食物名称
                  <input
                    value={foodQuery}
                    placeholder="米饭、鸡蛋、宫保鸡丁、香蕉…"
                    onFocus={() => setShowFoodSuggest(true)}
                    onChange={(e) => {
                      const value = e.target.value;
                      setFoodQuery(value);
                      setShowFoodSuggest(true);
                      const local = estimateFoods([{ query: value, grams }]);
                      const hit = local.items[0];
                      if (hit.matched) setGrams(hit.grams);
                    }}
                  />
                  {showFoodSuggest && foodQuery.trim() && (
                    <div className="food-suggest" role="listbox">
                      {searchFoods(foodQuery, 8).map(({ food, score }) => (
                        <button
                          key={food.id}
                          type="button"
                          onMouseDown={(e) => e.preventDefault()}
                          onClick={() => {
                            setFoodQuery(food.name);
                            setGrams(food.unit_g);
                            setShowFoodSuggest(false);
                            void confirmFood(food.name, food.unit_g);
                          }}
                        >
                          <strong>{food.name}</strong>
                          <span>
                            {food.kcal} kcal/100g · {food.group} · 匹配 {score}
                          </span>
                        </button>
                      ))}
                      {searchFoods(foodQuery, 1).length === 0 && (
                        <p>没有直接匹配。可填写下方每 100 克热量后估算。</p>
                      )}
                    </div>
                  )}
                </label>
                <label className="field-label">
                  份量（克）
                  <input
                    type="number"
                    min="1"
                    max="3000"
                    value={grams}
                    onChange={(e) => setGrams(Number(e.target.value))}
                  />
                </label>
                <label className="field-label">
                  自定义热量（kcal / 100g，可选）
                  <input
                    type="number"
                    min="0"
                    max="900"
                    placeholder="未匹配时使用"
                    value={customKcal}
                    onChange={(e) => setCustomKcal(e.target.value)}
                  />
                </label>
                <button className="primary" disabled={foodBusy} onClick={() => void confirmFood()}>
                  {foodBusy ? '正在确认…' : '确认计入'}
                  <ArrowRight size={16} />
                </button>
              </section>
              <section className="panel tinted">
                <h3>记录结果</h3>
                {foodResult || meal.length ? (
                  <>
                    <div className="rep-number">
                      {Math.round(meal.reduce((sum, item) => sum + item.total_kcal, 0) * 10) / 10}
                      <span> kcal</span>
                    </div>
                    <p>{foodResult?.note || '已按示例食物库估算。'}</p>
                  </>
                ) : (
                  <p>输入食物后点「确认计入」，或直接点下拉匹配项。</p>
                )}
                {meal.length > 0 && (
                  <ul className="meal-list">
                    {meal.map((item, index) => (
                      <li key={`${item.name}-${index}`}>
                        <span>
                          {item.name} · {item.grams}g
                        </span>
                        <strong>{item.total_kcal} kcal</strong>
                        <button
                          type="button"
                          className="text-button"
                          onClick={() => setMeal((prev) => prev.filter((_, i) => i !== index))}
                        >
                          移除
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {meal.length > 0 && (
                  <button
                    className="secondary"
                    onClick={() => {
                      setMealConfirmed(true);
                      setShowFoodSuggest(false);
                    }}
                  >
                    {mealConfirmed ? '本餐已确认' : '确认本餐记录'}
                    <Check size={16} />
                  </button>
                )}
                <p>
                  示例库覆盖主食、蛋白、乳制品、蔬菜、水果、饮品、零食和常见菜肴，按名称与别名匹配。不是营养处方。
                </p>
              </section>
            </div>
          </div>
        )}
        {tab === 'team' && (
          <div>
            <div className="section-top">
              <div>
                <h2>项目协作入口</h2>
                <p>文档、任务与验收标准集中维护。</p>
              </div>
              <a
                className="secondary"
                href="https://github.com/yky666/ai_health_assistant"
                target="_blank"
                rel="noreferrer"
              >
                打开代码仓库
                <ArrowRight size={16} />
              </a>
            </div>
            <div className="bottom-grid">
              {[
                ['产品与分析', 'docs/方案分析.md', '比赛要求、可行性、范围与创新点。'],
                ['架构与接口', 'docs/ARCHITECTURE.md', '模块边界、Agent 流、状态与数据合同。'],
                ['分工与进度', 'docs/TASKS.md', '角色负责人、里程碑与完成定义。'],
              ].map(([title, path, desc]) => (
                <section className="panel" key={title}>
                  <h3>{title}</h3>
                  <p>{desc}</p>
                  <a
                    className="text-link"
                    href={'https://github.com/yky666/ai_health_assistant/blob/main/' + path}
                    target="_blank"
                    rel="noreferrer"
                  >
                    查看文档 →
                  </a>
                </section>
              ))}
            </div>
            <section className="panel history">
              <h3>当前交付边界</h3>
              <p>
                已提供：可运行前后端、模拟动作、真实姿态推理接线、原创演示骨架、视频对齐、实验计数、
                会话提案与接受/拒绝、活动/静止/未知分段情景估算，以及仅同源资源模式。
              </p>
              <p>
                待验证：真实动作准确率、活动分段、实际设备性能和断网重启；自动机位与个体校准仍待实现。
                两核心动作优先验收，其余为实验入口。食品数据仍是未完成来源核验的示例。
              </p>
            </section>
          </div>
        )}
        <footer>
          <span>
            <LockKeyhole size={13} /> 默认不保存音视频 · 无云端推理依赖
          </span>
          <span>LocalFit / Open source, personal progress.</span>
        </footer>
      </main>
    </div>
  );
}

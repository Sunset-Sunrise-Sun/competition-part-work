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
import { acceptReport, request } from './api';
import { drawAvatar, drawRawPose, drawRetargetedOverlay, drawVideoFrame, syncCanvas } from './draw';
import { dailyRequirement, type ActivityLevel, type Sex } from './energy';
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
  const [report, setReport] = useState<Report | null>(null);
  const [history, setHistory] = useState<Report[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [apiReady, setApiReady] = useState(false);
  const [exerciseQuery, setExerciseQuery] = useState('');
  const [foodQuery, setFoodQuery] = useState('');
  const [grams, setGrams] = useState(150);
  const [customKcal, setCustomKcal] = useState('');
  const [foodResult, setFoodResult] = useState<{
    total_kcal: number;
    note: string;
    items?: { name: string; grams: number; total_kcal: number; matched: boolean }[];
  } | null>(null);
  const [meal, setMeal] = useState<{ name: string; grams: number; total_kcal: number }[]>([]);
  const [explanation, setExplanation] = useState('');
  const [videoName, setVideoName] = useState('');
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const avatar = useRef<HTMLCanvasElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const videoUrl = useRef('');
  const worker = useRef<Worker | null>(null);
  const points = useRef<Point[]>([]);
  const worldPoints = useRef<Point[]>([]);
  const engine = useRef(new ExerciseEngine('squat'));
  const live = useRef({
    running: false,
    source: 'simulation' as SourceMode,
    ready: false,
    elapsed: 0,
    observable: 0,
    quality: false,
    lastPose: 0,
    frameBusy: false,
  });
  const metricRef = useRef(emptyMetrics);
  const profileRef = useRef(defaultProfile());
  const showRawRef = useRef(true);

  useEffect(() => {
    fetch('/api/health', { signal: AbortSignal.timeout(4000) })
      .then((r) => setApiReady(r.ok))
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
    live.current.elapsed = 0;
    live.current.observable = 0;
    live.current.quality = false;
    metricRef.current = emptyMetrics;
    setMetrics(emptyMetrics);
    setElapsed(0);
    setReport(null);
    setExplanation('');
  }, [exercise, threshold, sourceMode]);

  useEffect(() => {
    live.current.source = sourceMode;
    live.current.ready = false;
    setModelReady(false);
    if (sourceMode === 'simulation') return;
    let cancelled = false;
    const poseWorker = new Worker(new URL('./pose.worker.ts', import.meta.url), { type: 'module' });
    worker.current = poseWorker;
    poseWorker.onmessage = (event: MessageEvent) => {
      if (cancelled) return;
      if (event.data.type === 'ready') {
        live.current.ready = true;
        setModelReady(true);
      }
      if (event.data.type === 'error') {
        live.current.frameBusy = false;
        live.current.ready = false;
        setModelReady(false);
        live.current.running = false;
        setRunning(false);
        setError(
          '姿态模型未就绪。本地请先运行 npm run prepare:models；GitHub Pages 部署时应已打包模型。' +
            event.data.message,
        );
      }
      if (event.data.type === 'pose') {
        live.current.frameBusy = false;
        points.current = event.data.points;
        worldPoints.current = event.data.worldPoints ?? [];
        if (live.current.running) {
          const result = engine.current.update(
            event.data.points,
            event.data.activeElapsedMs,
            event.data.aspectRatio,
          );
          metricRef.current = result;
          live.current.quality = result.quality;
          live.current.lastPose = performance.now();
          setMetrics(result);
        }
      }
    };
    const assetBase = new URL(import.meta.env.BASE_URL, location.href).href.replace(/\/$/, '');
    poseWorker.postMessage({ type: 'init', origin: assetBase || location.origin });
    if (sourceMode === 'camera') {
      navigator.mediaDevices
        .getUserMedia({ video: { width: 1280, height: 720 }, audio: false })
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
          if (!cancelled) {
            setError('无法打开摄像头：' + String(e));
            setSourceMode('simulation');
          }
        });
    } else if (video.current && videoUrl.current) {
      video.current.srcObject = null;
      video.current.src = videoUrl.current;
      video.current.load();
    }
    return () => {
      cancelled = true;
      poseWorker.terminate();
      worker.current = null;
      stream.current?.getTracks().forEach((t) => t.stop());
      stream.current = null;
      live.current.frameBusy = false;
    };
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
      const dt = Math.min((now - last) / 1000, 0.2);
      last = now;
      if (live.current.running) {
        live.current.elapsed += dt;
        if (live.current.source === 'simulation') {
          points.current = simulatedPose(live.current.elapsed * 1000, exercise);
          worldPoints.current = [];
          const result = engine.current.update(points.current, live.current.elapsed * 1000);
          metricRef.current = result;
          live.current.quality = result.quality;
          live.current.lastPose = now;
        }
        if (live.current.quality && now - live.current.lastPose < 500)
          live.current.observable += dt;
      } else if (live.current.source === 'simulation') {
        points.current = simulatedPose(live.current.elapsed * 1000, exercise);
        worldPoints.current = [];
      }
      if (now - lastDraw > 80) {
        lastDraw = now;
        setElapsed(live.current.elapsed);
        if (live.current.source === 'simulation') setMetrics(metricRef.current);
        const v = video.current,
          currentWorker = worker.current;
        if (
          live.current.running &&
          live.current.source !== 'simulation' &&
          live.current.ready &&
          v &&
          v.readyState >= 2 &&
          !live.current.frameBusy &&
          currentWorker
        ) {
          live.current.frameBusy = true;
          createImageBitmap(v)
            .then((bitmap) => {
              if (worker.current !== currentWorker || !live.current.running) {
                bitmap.close();
                live.current.frameBusy = false;
                return;
              }
              currentWorker.postMessage(
                {
                  type: 'frame',
                  bitmap,
                  timestamp: now,
                  activeElapsedMs: live.current.elapsed * 1000,
                },
                [bitmap],
              );
            })
            .catch(() => {
              live.current.frameBusy = false;
            });
        }
        const p = points.current;
        const aspect =
          v && v.videoWidth && v.videoHeight ? v.videoWidth / v.videoHeight : 4 / 3;
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
    live.current.running = false;
    setRunning(false);
    engine.current = new ExerciseEngine(exercise, threshold);
    live.current.elapsed = 0;
    live.current.observable = 0;
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
  function chooseSource(next: SourceMode) {
    live.current.running = false;
    setRunning(false);
    setSourceMode(next);
    setError('');
  }
  function onVideoFile(file?: File) {
    if (!file) return;
    if (videoUrl.current) URL.revokeObjectURL(videoUrl.current);
    videoUrl.current = URL.createObjectURL(file);
    setVideoName(file.name);
    chooseSource('video');
  }
  function toggleRunning() {
    if (sourceMode !== 'simulation' && (!modelReady || (sourceMode === 'camera' && !stream.current))) {
      setError('请等待摄像头 / 视频与本地模型准备完成。');
      return;
    }
    if (sourceMode === 'video' && !videoUrl.current) {
      setError('请先上传一段包含全身的训练视频。');
      return;
    }
    if (discomfort) {
      setError('已报告不适，训练保持暂停。请结束本组查看报告。');
      return;
    }
    live.current.running = !live.current.running;
    setRunning(live.current.running);
    setError('');
  }
  async function finish() {
    live.current.running = false;
    setRunning(false);
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
          form_events: metricRef.current.events,
          rep_details: metricRef.current.squatReps,
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
    try {
      const next = await acceptReport(report);
      setReport(next);
      setTarget(next.proposal.target_reps);
    } catch (e) {
      setError(String(e));
    }
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
  const sourceLabel =
    sourceMode === 'camera' ? '摄像头 · 本地姿态识别' : sourceMode === 'video' ? '上传视频 · 骨骼重定向' : '模拟动作回放 · 非真实测量';

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
            <p>居家运动 · SMPL 骨骼重定向 · 可解释的教练协作</p>
          </div>
          <span className={'status ' + (apiReady ? 'online' : 'browser')}>
            <i />
            {apiReady ? '本地服务已连接' : '浏览器本地模式'}
          </span>
        </header>
        {error && (
          <div role="alert" className="alert">
            {error}
          </div>
        )}
        <div style={{ display: tab === 'training' ? 'block' : 'none' }}>
          <div className="section-top">
            <div>
              <h2>今日训练空间</h2>
              <p>视频中的动作会重定向到可定制的 SMPL / SMPL-X 人体。</p>
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
                        : '模型准备中'}
                  </span>
                </div>
                <div className="dual-view">
                  <div className="viewport">
                    <video ref={video} muted playsInline loop />
                    <canvas ref={canvas} />
                    {sourceMode === 'simulation' && <div className="demo-watermark">SIMULATION</div>}
                    <div className="view-tag">
                      <span className={metrics.quality ? 'dot-good' : 'dot-wait'} />
                      {metrics.quality ? '骨骼已对齐人体' : '等待有效动作'}
                    </div>
                  </div>
                  <div className="avatar-pane">
                    <canvas ref={avatar} />
                    <div className="avatar-label">
                      {bodyModel === 'smplx' ? 'SMPL-X' : 'SMPL'} · 个性化标准人体
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
                    if (!q) return true;
                    return item.name.includes(exerciseQuery) || id.includes(q) || exerciseLabel(id).includes(exerciseQuery);
                  });
                  if (!items.length) return null;
                  return (
                    <optgroup key={group} label={group}>
                      {items.map((id) => (
                        <option key={id} value={id}>
                          {exerciseLabel(id)}
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
                  <p>{metrics.hint}</p>
                </div>
              </div>
              <div className="controls">
                <button className="primary" disabled={busy} onClick={toggleRunning}>
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
            </section>
          </div>
          <div className="bottom-grid body-grid">
            <section className="panel">
              <h3>标准人体与体型</h3>
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
                <span>每日热量需求</span>
                <strong>
                  {daily.need_kcal}
                  <small> kcal</small>
                </strong>
                <p>
                  BMR {daily.bmr_kcal} · TDEE {daily.tdee_kcal} · {daily.formula}
                </p>
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
                <option value="smpl">SMPL · 24 关节身体</option>
                <option value="smplx">SMPL-X · 身体 + 脸手</option>
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
                视频动作按 SMPL 拓扑重定向；身高决定骨长，体重与肌肉分布改变围度。这是浏览器内的标准人体近似，非正式 MPI
                官方网格权重。
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
                  {EXERCISES[exercise].hint} 当前共 {EXERCISE_IDS.length} 个动作。平板和靠墙静蹲按每 8
                  秒计 1 次。
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
                      {report.energy.low_kcal}–{report.energy.high_kcal}
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
                    ? `每日需求约 ${report.energy.daily.need_kcal} kcal（BMR ${report.energy.daily.bmr_kcal}）。 `
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
                      disabled={report.proposal.blocked || report.proposal.status === 'accepted'}
                      onClick={accept}
                    >
                      <Check size={16} />
                      {report.proposal.status === 'accepted'
                        ? '已确认并更新目标'
                        : '确认下一组计划'}
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
                    {r.source === 'simulation' ? '模拟' : r.source === 'video' ? '视频' : '摄像头'} ·{' '}
                    {r.session_id.slice(0, 8)}
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
                <label className="field-label food-search">
                  食物名称
                  <input
                    value={foodQuery}
                    placeholder="米饭、鸡蛋、宫保鸡丁、香蕉…"
                    onChange={(e) => {
                      const value = e.target.value;
                      setFoodQuery(value);
                      const local = estimateFoods([{ query: value, grams }]);
                      const hit = local.items[0];
                      if (hit.matched) setGrams(hit.grams);
                    }}
                  />
                  {foodQuery.trim() && (
                    <div className="food-suggest" role="listbox">
                      {searchFoods(foodQuery, 8).map(({ food, score }) => (
                        <button
                          key={food.id}
                          type="button"
                          onClick={() => {
                            setFoodQuery(food.name);
                            setGrams(food.unit_g);
                          }}
                        >
                          <strong>{food.name}</strong>
                          <span>
                            {food.kcal} kcal/100g · {food.group} · {score}
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
                <button
                  className="primary"
                  onClick={async () => {
                    try {
                      const payload = [
                        {
                          query: foodQuery,
                          grams,
                          kcal_per_100g: customKcal ? Number(customKcal) : undefined,
                        },
                      ];
                      const result = await request<{
                        total_kcal: number;
                        note: string;
                        items?: { name: string; grams: number; total_kcal?: number; kcal?: number; matched: boolean }[];
                      }>('/nutrition/estimate', {
                        method: 'POST',
                        body: JSON.stringify(payload),
                      });
                      const items = (result.items ?? []).map((item) => ({
                        name: item.name,
                        grams: item.grams,
                        total_kcal: item.total_kcal ?? item.kcal ?? 0,
                        matched: item.matched,
                      }));
                      setFoodResult({ ...result, items });
                      if (items[0]?.total_kcal) {
                        setMeal((prev) => [...prev, { name: items[0].name, grams: items[0].grams, total_kcal: items[0].total_kcal }]);
                      }
                    } catch (e) {
                      setError(String(e));
                    }
                  }}
                >
                  匹配并计入
                  <ArrowRight size={16} />
                </button>
              </section>
              <section className="panel tinted">
                <h3>记录结果</h3>
                {foodResult ? (
                  <>
                    <div className="rep-number">
                      {Math.round((meal.reduce((sum, item) => sum + item.total_kcal, 0) || foodResult.total_kcal) * 10) / 10}
                      <span> kcal</span>
                    </div>
                    <p>{foodResult.note}</p>
                    {foodResult.items?.[0] && !foodResult.items[0].matched && (
                      <p>未匹配到条目。改写名称，或填写自定义热量后再试。</p>
                    )}
                  </>
                ) : (
                  <p>输入食物名称后显示匹配与估算。</p>
                )}
                {meal.length > 0 && (
                  <ul className="meal-list">
                    {meal.map((item, index) => (
                      <li key={`${item.name}-${index}`}>
                        <span>
                          {item.name} · {item.grams}g
                        </span>
                        <strong>{item.total_kcal} kcal</strong>
                      </li>
                    ))}
                  </ul>
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
                已提供：可运行前后端、模拟动作、真实姿态推理接线、SMPL/SMPL-X
                骨骼重定向与体型定制、视频对齐可视化、计数规则、摘要与计划确认、GitHub Pages
                静态部署路径。
              </p>
              <p>
                待验证：真实动作准确率、自动机位判断、个体校准、实际设备性能。官方 SMPL
                网格权重需单独申请，不随仓库分发。
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

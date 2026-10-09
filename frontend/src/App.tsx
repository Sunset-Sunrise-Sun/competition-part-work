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
  Users,
} from 'lucide-react';
import { ExerciseEngine, simulatedPose } from './engine';
import { acceptReport, request } from './api';
import type { Exercise, Metrics, Point, Report } from './types';

const exerciseNames = { squat: '深蹲 · 侧面机位', jumping_jack: '开合跳 · 正面机位' };
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
};
const connections = [
  [11, 12],
  [11, 13],
  [13, 15],
  [12, 14],
  [14, 16],
  [11, 23],
  [12, 24],
  [23, 24],
  [23, 25],
  [25, 27],
  [24, 26],
  [26, 28],
];

export default function App() {
  const [tab, setTab] = useState('training');
  const [exercise, setExercise] = useState<Exercise>('squat');
  const [camera, setCamera] = useState(false);
  const [modelReady, setModelReady] = useState(false);
  const [running, setRunning] = useState(false);
  const [metrics, setMetrics] = useState<Metrics>(emptyMetrics);
  const [elapsed, setElapsed] = useState(0);
  const [weight, setWeight] = useState(65);
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
  const [food, setFood] = useState('rice');
  const [grams, setGrams] = useState(150);
  const [foodResult, setFoodResult] = useState<{ total_kcal: number; note: string } | null>(null);
  const [explanation, setExplanation] = useState('');
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const worker = useRef<Worker | null>(null);
  const points = useRef<Point[]>([]);
  const engine = useRef(new ExerciseEngine('squat'));
  const live = useRef({
    running: false,
    camera: false,
    ready: false,
    elapsed: 0,
    observable: 0,
    quality: false,
    lastPose: 0,
    frameBusy: false,
  });
  const metricRef = useRef(emptyMetrics);

  useEffect(() => {
    request('/health')
      .then(() => setApiReady(true))
      .catch(() => setApiReady(false));
  }, []);
  useEffect(() => {
    live.current.running = running;
  }, [running]);
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
  }, [exercise, threshold, camera]);

  useEffect(() => {
    live.current.camera = camera;
    live.current.ready = false;
    setModelReady(false);
    if (!camera) return;
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
          '摄像头模型未就绪。请先运行 npm run prepare:models，并查看浏览器控制台。' +
            event.data.message,
        );
      }
      if (event.data.type === 'pose') {
        live.current.frameBusy = false;
        points.current = event.data.points;
        if (live.current.running) {
          const result = engine.current.update(event.data.points, event.data.timestamp);
          metricRef.current = result;
          live.current.quality = result.quality;
          live.current.lastPose = performance.now();
          setMetrics(result);
        }
      }
    };
    poseWorker.postMessage({ type: 'init', origin: location.origin });
    navigator.mediaDevices
      .getUserMedia({ video: { width: 640, height: 480 }, audio: false })
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
          setCamera(false);
        }
      });
    return () => {
      cancelled = true;
      poseWorker.terminate();
      worker.current = null;
      stream.current?.getTracks().forEach((t) => t.stop());
      stream.current = null;
      live.current.frameBusy = false;
    };
  }, [camera]);

  useEffect(() => {
    let frame = 0,
      last = performance.now(),
      lastDraw = 0;
    const loop = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.2);
      last = now;
      if (live.current.running) {
        live.current.elapsed += dt;
        if (!live.current.camera) {
          points.current = simulatedPose(live.current.elapsed * 1000, exercise);
          const result = engine.current.update(points.current, live.current.elapsed * 1000);
          metricRef.current = result;
          live.current.quality = result.quality;
          live.current.lastPose = now;
        }
        if (live.current.quality && now - live.current.lastPose < 500)
          live.current.observable += dt;
      } else if (!live.current.camera) {
        points.current = simulatedPose(live.current.elapsed * 1000, exercise);
      }
      if (now - lastDraw > 80) {
        lastDraw = now;
        setElapsed(live.current.elapsed);
        if (!live.current.camera) setMetrics(metricRef.current);
        const v = video.current,
          currentWorker = worker.current;
        if (
          live.current.running &&
          live.current.camera &&
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
              currentWorker.postMessage({ type: 'frame', bitmap, timestamp: now }, [bitmap]);
            })
            .catch(() => {
              live.current.frameBusy = false;
            });
        }
        const c = canvas.current,
          ctx = c?.getContext('2d');
        if (c && ctx) {
          ctx.clearRect(0, 0, c.width, c.height);
          const p = points.current;
          ctx.lineWidth = 5;
          ctx.strokeStyle = live.current.camera ? '#c9f483' : '#badd8b';
          for (const [a, b] of connections) {
            if (p[a] && p[b] && (p[a].visibility ?? 0) > 0.5 && (p[b].visibility ?? 0) > 0.5) {
              ctx.beginPath();
              ctx.moveTo(p[a].x * c.width, p[a].y * c.height);
              ctx.lineTo(p[b].x * c.width, p[b].y * c.height);
              ctx.stroke();
            }
          }
          for (const i of new Set(connections.flat())) {
            if (p[i] && (p[i].visibility ?? 0) > 0.5) {
              ctx.beginPath();
              ctx.arc(p[i].x * c.width, p[i].y * c.height, 6, 0, Math.PI * 2);
              ctx.fillStyle = '#f4f7ea';
              ctx.fill();
            }
          }
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
  }
  function toggleRunning() {
    if (camera && (!modelReady || !stream.current)) {
      setError('请等待摄像头与本地模型准备完成。');
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
          source: camera ? 'camera' : 'simulation',
          reps: metricRef.current.reps,
          active_seconds: live.current.elapsed,
          observable_seconds: Math.min(live.current.observable, live.current.elapsed),
          form_events: metricRef.current.events,
          fatigue,
          discomfort,
          target_reps: target,
          persist,
          profile: { weight_kg: weight, experience: 'beginner', goal: 'habit' },
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
            <p>居家运动 · 实时反馈 · 可解释的教练协作</p>
          </div>
          <span className={'status ' + (apiReady ? 'online' : '')}>
            <i />
            {apiReady ? '本地服务已连接' : '本地服务待启动'}
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
              <p>先设置动作与机位，再开始一组。</p>
            </div>
            <div className="segmented">
              <button
                disabled={running || busy}
                className={!camera ? 'selected' : ''}
                onClick={() => {
                  setRunning(false);
                  setCamera(false);
                }}
              >
                模拟演示
              </button>
              <button
                disabled={running || busy}
                className={camera ? 'selected' : ''}
                onClick={() => {
                  setRunning(false);
                  setCamera(true);
                  setError('');
                }}
              >
                真实摄像头
              </button>
            </div>
          </div>
          <div className="training-grid">
            <section className="camera-card">
              <div className="camera-heading">
                <span>
                  <Camera size={16} />
                  {camera ? '摄像头 · 本地姿态识别' : '模拟动作回放 · 非真实测量'}
                </span>
                <span className="camera-chip">
                  {camera ? (modelReady ? '模型已就绪' : '模型准备中') : 'DEMO'}
                </span>
              </div>
              <div className="viewport">
                <video
                  ref={video}
                  muted
                  playsInline
                  style={{ display: camera ? 'block' : 'none' }}
                />
                <canvas ref={canvas} width={640} height={480} />
                {!camera && <div className="demo-watermark">SIMULATION</div>}
                <div className="view-tag">
                  <span className={metrics.quality ? 'dot-good' : 'dot-wait'} />
                  {metrics.quality ? '关键点可见' : '等待有效动作'}
                </div>
              </div>
              <div className="camera-footer">
                <LockKeyhole size={15} />
                <span>画面只在当前设备处理</span>
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
            <section className="coach-card">
              <div className="card-kicker">YOUR TRAINING</div>
              <label className="field-label" htmlFor="exercise">
                当前动作
              </label>
              <select
                id="exercise"
                disabled={running || busy}
                value={exercise}
                onChange={(e) => setExercise(e.target.value as Exercise)}
              >
                {Object.entries(exerciseNames).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
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
              </div>
              <button className="finish-button" disabled={busy} onClick={finish}>
                {busy ? '生成报告中…' : '结束本组并复盘'}
                <ArrowRight size={17} />
              </button>
            </section>
          </div>
          <div className="bottom-grid">
            <section className="panel">
              <h3>训练设置</h3>
              <div className="fields">
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
              <details>
                <summary>实验参数与机位要求</summary>
                <p>
                  深蹲采用侧面、左侧髋膝踝可见；开合跳采用正面、全身入画。尚未完成自动机位判断与个体校准。
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
            <section className="panel tinted">
              <ShieldCheck size={24} />
              <h3>了解当前能力</h3>
              <p>
                计数与纠错采用待验证规则。Agent 协作默认是确定性基线；本地语言模型为可选解释层。
              </p>
              <span className="text-link">真实数据验证进行前，不宣称准确率</span>
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
                  {report.source === 'simulation' ? '本次为模拟记录。' : '本次来自摄像头记录。'}
                  {report.energy.note}{' '}
                  {report.saved ? '摘要已保存至本机。' : '摘要仅暂存在当前会话。'}
                </p>
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
                    {r.source === 'simulation' ? '模拟' : '摄像头'} · {r.session_id.slice(0, 8)}
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
                <p>先实现可核对的记录，不从照片猜份量。</p>
              </div>
              <span className="badge">示例食品数据 · 未核验</span>
            </div>
            <div className="report-grid">
              <section className="panel">
                <Leaf className="leaf-icon" size={30} />
                <h3>添加食物</h3>
                <label className="field-label">
                  食物
                  <select value={food} onChange={(e) => setFood(e.target.value)}>
                    <option value="rice">熟米饭</option>
                    <option value="egg">鸡蛋</option>
                    <option value="milk">全脂牛奶</option>
                    <option value="broccoli">西兰花</option>
                  </select>
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
                <button
                  className="primary"
                  onClick={async () => {
                    try {
                      setFoodResult(
                        await request('/nutrition/estimate', {
                          method: 'POST',
                          body: JSON.stringify([{ food_id: food, grams }]),
                        }),
                      );
                    } catch (e) {
                      setError(String(e));
                    }
                  }}
                >
                  计算示例能量
                  <ArrowRight size={16} />
                </button>
              </section>
              <section className="panel tinted">
                <h3>记录结果</h3>
                {foodResult ? (
                  <>
                    <div className="rep-number">
                      {foodResult.total_kcal}
                      <span> kcal</span>
                    </div>
                    <p>{foodResult.note}</p>
                  </>
                ) : (
                  <p>选择食物并确认份量后显示计算结果。</p>
                )}
                <p>
                  正式数据层需记录食品 ID、来源、每 100g
                  数值、烹饪方式和许可。本原型尚未提供完整营养处方或饮食规划。
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
                已提供：可运行前后端、模拟动作、真实姿态推理接线、计数规则、摘要与计划确认、规则协作记录、示例饮食计算、可选本地模型解释接口。
              </p>
              <p>
                待验证：真实动作准确率、自动机位判断、个体校准、实际设备性能、完整离线验收。待实现：语音、经核验食品库、学习型时序模型、LangGraph
                接入。
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

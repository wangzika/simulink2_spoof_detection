#include "flight_sim/visualizer.hpp"

#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>

namespace flight_sim {

namespace {

std::string escapeJson(const std::string& text) {
    std::string out;
    out.reserve(text.size());
    for (char c : text) {
        if (c == '"' || c == '\\') {
            out.push_back('\\');
        }
        out.push_back(c);
    }
    return out;
}

} // namespace

void HtmlVisualizer::addSample(
    double t_s,
    const DroneState& truth,
    const NavEstimate& nav,
    const SensorSample& sensor,
    const TrajectorySetpoint& ref,
    const DetectionState& detection,
    const ModeDecision& mode) {
    samples_.push_back(Sample{
        t_s,
        truth.position_m,
        nav.position_m,
        sensor.gps_position_m,
        sensor.uwb_position_m,
        ref.position_m,
        sensor.gps_attacked,
        detection.gps_spoof_detected,
        mode.gps_trusted,
        sensor.uwb_valid,
        sensor.optical_flow_valid,
        sensor.magnetometer_valid,
        detection.pseudorange_residual_rms_m,
        detection.pseudorange_residual_max_abs_m,
        detection.glrt_statistic,
        detection.glrt_threshold,
        detection.glrt_detected,
        mode.mode_name,
    });
}

bool HtmlVisualizer::writeHtml(const std::string& path, const SimulationConfig& config) const {
    std::ofstream out(path);
    if (!out) {
        std::cerr << "Failed to open dashboard HTML: " << path << "\n";
        return false;
    }

    out << R"HTML(<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>F7 Pseudorange GLRT Simulation Dashboard</title>
<style>
:root { color-scheme: light; --bg:#f3f5f7; --panel:#ffffff; --ink:#18202a; --muted:#667085; --blue:#2563eb; --red:#dc2626; --green:#16a34a; --amber:#d97706; --line:#d8dee8; }
* { box-sizing: border-box; }
body { margin:0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:var(--bg); color:var(--ink); }
header { height:64px; display:flex; align-items:center; justify-content:space-between; padding:0 22px; background:#111827; color:white; }
header h1 { font-size:20px; margin:0; font-weight:700; }
header .meta { color:#cbd5e1; font-size:13px; }
main { padding:16px; display:grid; grid-template-columns: 1.35fr .65fr; grid-template-rows:auto auto 260px; gap:14px; min-height:calc(100vh - 64px); }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; box-shadow:0 1px 2px rgba(15,23,42,.06); }
.status { grid-column:1 / 3; display:grid; grid-template-columns:1.2fr repeat(6, 1fr); gap:12px; padding:12px; }
.badge { border-radius:8px; padding:14px; background:#e5e7eb; display:flex; flex-direction:column; justify-content:center; min-height:72px; }
.badge strong { font-size:13px; color:var(--muted); margin-bottom:6px; }
.badge span { font-size:22px; font-weight:800; }
#stateBadge { color:white; align-items:center; text-align:center; }
#stateBadge span { font-size:26px; }
.ok { background:var(--green); } .bad { background:var(--red); } .warn { background:var(--amber); }
.canvasPanel { padding:12px; display:flex; flex-direction:column; gap:8px; min-height:420px; }
.canvasPanel h2 { margin:0; font-size:16px; }
canvas { width:100%; height:100%; border:1px solid var(--line); border-radius:6px; background:white; }
#trajCanvas { min-height:470px; }
.side { padding:12px; display:grid; grid-template-rows:auto 1fr; gap:10px; }
.metrics { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.metric { border:1px solid var(--line); border-radius:7px; padding:10px; background:#fbfcff; }
.metric .label { color:var(--muted); font-size:12px; margin-bottom:6px; }
.metric .value { font-size:20px; font-weight:800; }
.controls { grid-column:1 / 3; padding:12px; display:grid; grid-template-columns:90px 90px 90px 1fr 160px; align-items:center; gap:10px; }
button { height:36px; border:1px solid var(--line); background:#fff; border-radius:6px; font-weight:700; cursor:pointer; }
button:hover { background:#f8fafc; }
input[type=range] { width:100%; }
.plotPanel { grid-column:1 / 3; padding:12px; display:grid; grid-template-columns:1fr; gap:8px; }
#errorCanvas { height:210px; }
.legend { display:flex; gap:16px; color:var(--muted); font-size:13px; align-items:center; flex-wrap:wrap; }
.dot { display:inline-block; width:10px; height:10px; border-radius:999px; margin-right:5px; }
.blue { background:var(--blue); } .red { background:var(--red); } .green { background:var(--green); } .gray { background:#9ca3af; } .teal { background:#0f766e; }
@media (max-width: 1000px) { main { grid-template-columns:1fr; grid-template-rows:auto auto auto auto; } .status, .controls, .plotPanel { grid-column:1; } .status { grid-template-columns:1fr 1fr; } }
</style>
</head>
<body>
<header>
  <h1>F7 伪距 GLRT 攻击检测 C++ 仿真驾驶舱</h1>
  <div class="meta">CSV 与 HTML 均由 C++ 仿真器生成</div>
</header>
<main>
  <section class="status panel">
    <div id="stateBadge" class="badge ok"><strong>当前状态</strong><span>正常飞行</span></div>
    <div class="badge"><strong>当前时间</strong><span id="timeNow">0.00 s</span></div>
    <div class="badge"><strong>伪距残差</strong><span id="residualNow">0.000 m</span></div>
    <div class="badge"><strong>GLRT统计量</strong><span id="glrtNow">0.00</span></div>
    <div class="badge"><strong>阈值</strong><span id="thresholdNow">0.00</span></div>
    <div class="badge"><strong>检测结果</strong><span id="detectNow">正常</span></div>
    <div class="badge"><strong>GPS 融合</strong><span id="trustNow">-</span></div>
  </section>
  <section class="canvasPanel panel">
    <h2>俯视轨迹回放</h2>
    <canvas id="trajCanvas"></canvas>
    <div class="legend"><span><i class="dot blue"></i>真实轨迹</span><span><i class="dot red"></i>GPS攻击段</span><span><i class="dot green"></i>当前位置</span><span><i class="dot gray"></i>参考轨迹</span><span><i class="dot teal"></i>UWB辅助点</span></div>
  </section>
  <aside class="side panel">
    <h2>关键指标</h2>
    <div class="metrics">
      <div class="metric"><div class="label">飞行时长</div><div class="value" id="durationMetric">-</div></div>
      <div class="metric"><div class="label">最大伪距残差</div><div class="value" id="maxResidualMetric">-</div></div>
      <div class="metric"><div class="label">攻击占比</div><div class="value" id="attackRatioMetric">-</div></div>
      <div class="metric"><div class="label">GLRT告警占比</div><div class="value" id="detectRatioMetric">-</div></div>
      <div class="metric"><div class="label">GPS拒绝样本</div><div class="value" id="rejectMetric">-</div></div>
      <div class="metric"><div class="label">最大GLRT</div><div class="value" id="maxGlrtMetric">-</div></div>
      <div class="metric"><div class="label">UWB更新</div><div class="value" id="uwbMetric">-</div></div>
      <div class="metric"><div class="label">光流更新</div><div class="value" id="flowMetric">-</div></div>
      <div class="metric"><div class="label">磁力计更新</div><div class="value" id="magMetric">-</div></div>
    </div>
  </aside>
  <section class="plotPanel panel">
    <h2>伪距残差、GLRT统计量与阈值</h2>
    <canvas id="errorCanvas"></canvas>
  </section>
  <section class="controls panel">
    <button id="playBtn">播放</button>
    <button id="pauseBtn">暂停</button>
    <button id="resetBtn">重置</button>
    <input id="timeSlider" type="range" min="0" max="1" value="0" step="1">
    <select id="speedSelect">
      <option value="0.5">0.5x</option>
      <option value="1" selected>1x</option>
      <option value="2">2x</option>
      <option value="4">4x</option>
    </select>
  </section>
</main>
<script>
const DATA = [
)HTML";

    out << std::fixed << std::setprecision(6);
    for (std::size_t i = 0; i < samples_.size(); ++i) {
        const auto& s = samples_[i];
        out << "{"
            << "\"t\":" << s.t_s << ","
            << "\"x\":" << s.truth.x << ",\"y\":" << s.truth.y << ",\"z\":" << s.truth.z << ","
            << "\"ex\":" << s.estimate.x << ",\"ey\":" << s.estimate.y << ",\"ez\":" << s.estimate.z << ","
            << "\"gx\":" << s.gps.x << ",\"gy\":" << s.gps.y << ",\"gz\":" << s.gps.z << ","
            << "\"ux\":" << s.uwb.x << ",\"uy\":" << s.uwb.y << ",\"uz\":" << s.uwb.z << ","
            << "\"rx\":" << s.ref.x << ",\"ry\":" << s.ref.y << ",\"rz\":" << s.ref.z << ","
            << "\"attack\":" << (s.attack ? 1 : 0) << ","
            << "\"detected\":" << (s.detected ? 1 : 0) << ","
            << "\"trusted\":" << (s.gps_trusted ? 1 : 0) << ","
            << "\"uwbValid\":" << (s.uwb_valid ? 1 : 0) << ","
            << "\"flowValid\":" << (s.optical_flow_valid ? 1 : 0) << ","
            << "\"magValid\":" << (s.magnetometer_valid ? 1 : 0) << ","
            << "\"residual\":" << s.pseudorange_residual_rms << ","
            << "\"residualMax\":" << s.pseudorange_residual_max_abs << ","
            << "\"glrt\":" << s.glrt_statistic << ","
            << "\"threshold\":" << s.glrt_threshold << ","
            << "\"glrtDetected\":" << (s.glrt_detected ? 1 : 0) << ","
            << "\"mode\":\"" << escapeJson(s.mode) << "\""
            << "}";
        if (i + 1 < samples_.size()) {
            out << ",";
        }
        out << "\n";
    }

    out << R"HTML(];
const CONFIG = { duration: )HTML" << config.duration_s << R"HTML( };

const traj = document.getElementById('trajCanvas');
const err = document.getElementById('errorCanvas');
const slider = document.getElementById('timeSlider');
const playBtn = document.getElementById('playBtn');
const pauseBtn = document.getElementById('pauseBtn');
const resetBtn = document.getElementById('resetBtn');
const speedSelect = document.getElementById('speedSelect');
let idx = 0;
let playing = false;
let lastFrame = performance.now();

slider.max = Math.max(0, DATA.length - 1);

function resizeCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  canvas.height = Math.max(1, Math.floor(rect.height * ratio));
  const ctx = canvas.getContext('2d');
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
}

function bounds() {
  const xs = DATA.flatMap(d => [d.x, d.rx, d.gx, d.ux]);
  const ys = DATA.flatMap(d => [d.y, d.ry, d.gy, d.uy]);
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
}
const B = bounds();
function mapPoint(d, canvas) {
  const rect = canvas.getBoundingClientRect();
  const pad = 28;
  const sx = (rect.width - 2*pad) / Math.max(1e-6, B.maxX - B.minX);
  const sy = (rect.height - 2*pad) / Math.max(1e-6, B.maxY - B.minY);
  const s = Math.min(sx, sy);
  return { x: pad + (d.x - B.minX) * s, y: rect.height - pad - (d.y - B.minY) * s };
}
function mapRef(d, canvas) {
  return mapPoint({x:d.rx, y:d.ry}, canvas);
}
function mapGps(d, canvas) {
  return mapPoint({x:d.gx, y:d.gy}, canvas);
}
function mapUwb(d, canvas) {
  return mapPoint({x:d.ux, y:d.uy}, canvas);
}

function line(ctx, points, color, width=2) {
  if (points.length < 2) return;
  ctx.strokeStyle = color; ctx.lineWidth = width; ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (const p of points.slice(1)) ctx.lineTo(p.x, p.y);
  ctx.stroke();
}
function drawTrajectory() {
  resizeCanvas(traj);
  const ctx = traj.getContext('2d');
  const rect = traj.getBoundingClientRect();
  ctx.clearRect(0,0,rect.width,rect.height);
  ctx.fillStyle = '#fff'; ctx.fillRect(0,0,rect.width,rect.height);
  const refPts = DATA.map(d => mapRef(d, traj));
  const truePts = DATA.map(d => mapPoint(d, traj));
  line(ctx, refPts, '#9ca3af', 1.5);
  line(ctx, truePts, '#2563eb', 2);
  const attackPts = DATA.filter(d => d.attack).map(d => mapPoint(d, traj));
  line(ctx, attackPts, '#dc2626', 3);
  const gpsPts = DATA.filter((_, i) => i % 8 === 0).map(d => mapGps(d, traj));
  line(ctx, gpsPts, '#f97316', 1);
  ctx.fillStyle = '#0f766e';
  DATA.forEach((d, i) => {
    if (!d.uwbValid || i % 5 !== 0) return;
    const u = mapUwb(d, traj);
    ctx.beginPath(); ctx.arc(u.x, u.y, 2.5, 0, Math.PI*2); ctx.fill();
  });
  const p = mapPoint(DATA[idx], traj);
  ctx.fillStyle = '#16a34a'; ctx.strokeStyle = '#111827'; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.arc(p.x, p.y, 7, 0, Math.PI*2); ctx.fill(); ctx.stroke();
}

function drawError() {
  resizeCanvas(err);
  const ctx = err.getContext('2d');
  const rect = err.getBoundingClientRect();
  ctx.clearRect(0,0,rect.width,rect.height);
  ctx.fillStyle = '#fff'; ctx.fillRect(0,0,rect.width,rect.height);
  const padL=48, padR=44, padT=16, padB=28;
  const maxT = DATA[DATA.length-1].t;
  const maxR = Math.max(...DATA.map(d=>d.residualMax || d.residual), 1);
  const maxG = Math.max(...DATA.map(d=>Math.max(d.glrt, d.threshold)), 1);
  function px(t){ return padL + t/maxT*(rect.width-padL-padR); }
  function pyResidual(v){ return rect.height-padB - v/maxR*(rect.height-padT-padB); }
  function pyGlrt(v){ return rect.height-padB - v/maxG*(rect.height-padT-padB); }
  for (let i=0;i<DATA.length;i++) {
    if (DATA[i].attack) {
      ctx.fillStyle = 'rgba(220,38,38,.16)';
      const x0 = px(DATA[i].t);
      let j=i; while(j<DATA.length && DATA[j].attack) j++;
      const x1 = px(DATA[Math.min(j,DATA.length-1)].t);
      ctx.fillRect(x0,padT,x1-x0,rect.height-padT-padB);
      i=j;
    }
  }
  ctx.strokeStyle='#d1d5db'; ctx.lineWidth=1; ctx.beginPath();
  ctx.moveTo(padL,padT); ctx.lineTo(padL,rect.height-padB); ctx.lineTo(rect.width-padR,rect.height-padB); ctx.stroke();
  ctx.strokeStyle='#2563eb'; ctx.lineWidth=2; ctx.beginPath();
  DATA.forEach((d,i)=>{ const x=px(d.t), y=pyResidual(d.residual); if(i===0)ctx.moveTo(x,y); else ctx.lineTo(x,y); });
  ctx.stroke();
  ctx.strokeStyle='#d97706'; ctx.lineWidth=2; ctx.beginPath();
  DATA.forEach((d,i)=>{ const x=px(d.t), y=pyGlrt(d.glrt); if(i===0)ctx.moveTo(x,y); else ctx.lineTo(x,y); });
  ctx.stroke();
  ctx.save();
  ctx.setLineDash([6,4]);
  ctx.strokeStyle='#dc2626'; ctx.lineWidth=2; ctx.beginPath();
  DATA.forEach((d,i)=>{ const x=px(d.t), y=pyGlrt(d.threshold); if(i===0)ctx.moveTo(x,y); else ctx.lineTo(x,y); });
  ctx.stroke();
  ctx.restore();
  ctx.fillStyle='rgba(220,38,38,.85)';
  DATA.forEach(d=>{ if(!d.glrtDetected) return; const x=px(d.t); ctx.fillRect(x-1, rect.height-padB-8, 2, 8); });
  const cx = px(DATA[idx].t);
  ctx.strokeStyle='#111827'; ctx.lineWidth=1.5; ctx.beginPath(); ctx.moveTo(cx,padT); ctx.lineTo(cx,rect.height-padB); ctx.stroke();
  ctx.fillStyle='#667085'; ctx.font='12px sans-serif';
  ctx.fillText('pseudorange residual (m)', padL, 12);
  ctx.fillText('GLRT', rect.width-padR+6, 12);
}

function updateStats() {
  const d = DATA[idx];
  document.getElementById('timeNow').textContent = d.t.toFixed(2) + ' s';
  document.getElementById('residualNow').textContent = d.residual.toFixed(3) + ' m';
  document.getElementById('glrtNow').textContent = d.glrt.toFixed(2);
  document.getElementById('thresholdNow').textContent = d.threshold.toFixed(2);
  document.getElementById('detectNow').textContent = d.glrtDetected ? '告警' : '正常';
  document.getElementById('trustNow').textContent = d.trusted ? '融合中' : '已拒绝';
  const stateBadge = document.getElementById('stateBadge');
  stateBadge.className = 'badge ' + (d.glrtDetected ? 'bad' : (d.attack ? 'warn' : 'ok'));
  stateBadge.querySelector('span').textContent = d.glrtDetected ? 'GLRT告警' : (d.attack ? '攻击注入' : '正常飞行');
}
function initMetrics() {
  const duration = DATA[DATA.length-1].t;
  const maxResidual = Math.max(...DATA.map(d=>d.residualMax || d.residual));
  const maxGlrt = Math.max(...DATA.map(d=>d.glrt));
  const attackRatio = DATA.filter(d=>d.attack).length / DATA.length * 100;
  const detectRatio = DATA.filter(d=>d.glrtDetected).length / DATA.length * 100;
  const rejected = DATA.filter(d=>!d.trusted).length;
  const uwbUpdates = DATA.filter(d=>d.uwbValid).length;
  const flowUpdates = DATA.filter(d=>d.flowValid).length;
  const magUpdates = DATA.filter(d=>d.magValid).length;
  document.getElementById('durationMetric').textContent = duration.toFixed(1)+' s';
  document.getElementById('maxResidualMetric').textContent = maxResidual.toFixed(3)+' m';
  document.getElementById('attackRatioMetric').textContent = attackRatio.toFixed(1)+'%';
  document.getElementById('detectRatioMetric').textContent = detectRatio.toFixed(1)+'%';
  document.getElementById('rejectMetric').textContent = String(rejected);
  document.getElementById('maxGlrtMetric').textContent = maxGlrt.toFixed(1);
  document.getElementById('uwbMetric').textContent = String(uwbUpdates);
  document.getElementById('flowMetric').textContent = String(flowUpdates);
  document.getElementById('magMetric').textContent = String(magUpdates);
}
function render() { drawTrajectory(); drawError(); updateStats(); slider.value = idx; }
function step(now) {
  if (playing) {
    const speed = Number(speedSelect.value);
    const advance = Math.max(1, Math.floor((now-lastFrame)/35*speed));
    idx = Math.min(DATA.length-1, idx + advance);
    if (idx >= DATA.length-1) playing = false;
    render();
  }
  lastFrame = now;
  requestAnimationFrame(step);
}
playBtn.onclick = () => { playing = true; };
pauseBtn.onclick = () => { playing = false; };
resetBtn.onclick = () => { playing = false; idx = 0; render(); };
slider.oninput = () => { playing = false; idx = Number(slider.value); render(); };
window.onresize = render;
initMetrics();
render();
requestAnimationFrame(step);
</script>
</body>
</html>
)HTML";

    return true;
}

} // namespace flight_sim

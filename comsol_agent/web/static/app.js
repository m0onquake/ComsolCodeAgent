const state = { mode: "demo", sessionId: null, code: "", running: false, loads: [] };
const el = (id) => document.getElementById(id);
const requirement = el("requirement");
const runBtn = el("runBtn");
const timeline = el("timeline");
const codeView = el("codeView");
const copyBtn = el("copyBtn");

function setHealth(ok, message) {
  el("healthDot").className = `status-dot ${ok ? "ok" : "bad"}`;
  el("healthText").textContent = message;
}

async function bootstrap() {
  try {
    const [healthResp, demoResp] = await Promise.all([fetch("/api/health"), fetch("/api/demo")]);
    const health = await healthResp.json();
    const demo = await demoResp.json();
    setHealth(health.status === "ok", health.demo_available ? "系统就绪 · 演示产物已加载" : "系统就绪 · 演示产物缺失");
    requirement.value = demo.requirement || "";
  } catch (error) {
    setHealth(false, "后端连接失败");
  }
}

document.querySelectorAll(".mode-btn").forEach((button) => {
  button.addEventListener("click", () => {
    if (state.running) return;
    state.mode = button.dataset.mode;
    document.querySelectorAll(".mode-btn").forEach((item) => item.classList.toggle("active", item === button));
    el("modeNote").textContent = state.mode === "demo"
      ? "使用仓库内真实 COMSOL 结果，约 5 秒完成稳定回放。"
      : "调用当前 AgentLoop 与本机 COMSOL；耗时取决于模型复杂度。";
    runBtn.querySelector("span").textContent = state.mode === "demo" ? "启动演示" : "开始实时运行";
  });
});

function resetRun(preserveSession = false) {
  if (!preserveSession) state.sessionId = null;
  timeline.className = "timeline";
  timeline.innerHTML = "";
  if (!preserveSession) {
    state.code = "";
    state.loads = [];
    codeView.textContent = "// Agent 正在准备生成路径...";
    copyBtn.disabled = true;
    el("gallery").className = "gallery empty-gallery";
    el("gallery").innerHTML = "<p>正在等待 COMSOL 结果...</p>";
    el("fileList").innerHTML = "";
    el("artifactCount").textContent = "0 FILES";
    el("metricGrid").innerHTML = new Array(4).fill('<div class="metric-card skeleton"></div>').join("");
    drawLoads([]);
  }
  el("agentResponse").textContent = "Agent 正在执行，请关注左侧时间线。";
}

function traceKey(event) {
  if (event.type === "stage" || event.type === "stage_result") return `stage-${event.stage}`;
  return `${event.type}-${event.name || event.timestamp}-${Math.random()}`;
}

function addTrace(event) {
  if (event.type === "session") {
    state.sessionId = event.session_id;
    el("sessionBadge").textContent = `${event.mode.toUpperCase()} · ${event.session_id.slice(0, 8)}`;
    return;
  }
  if (event.type === "stage_result") {
    const existing = document.querySelector(`[data-trace="stage-${event.stage}"]`);
    if (existing) existing.className = `trace-item ${event.status}`;
    return;
  }
  if (!["stage", "tool_call", "tool_result", "error"].includes(event.type)) return;
  const item = document.createElement("div");
  item.dataset.trace = traceKey(event);
  const failed = event.failed || event.type === "error";
  item.className = `trace-item ${failed ? "failed" : "running"}`;
  const title = event.title || (event.type === "tool_call" ? `调用 ${event.name}` : event.type === "tool_result" ? `${event.name} 返回` : "运行错误");
  const detail = event.detail || event.message || (event.type === "stage" ? "处理中" : "");
  const time = (event.timestamp || "").slice(11, 19);
  item.innerHTML = '<span class="trace-dot"></span>';
  const body = document.createElement("div");
  const titleRow = document.createElement("div");
  titleRow.className = "trace-title";
  const titleText = document.createElement("span"); titleText.textContent = title;
  const timeText = document.createElement("span"); timeText.className = "trace-time"; timeText.textContent = time;
  titleRow.append(titleText, timeText);
  const detailText = document.createElement("p"); detailText.className = "trace-detail"; detailText.textContent = detail;
  body.append(titleRow, detailText); item.append(body); timeline.append(item);
  if (event.type === "tool_result" && !failed) item.className = "trace-item passed";
  timeline.scrollTop = timeline.scrollHeight;
}

function handleEvent(event) {
  addTrace(event);
  if (event.type === "code") {
    state.code = event.code || "";
    codeView.textContent = state.code.slice(0, 60000);
    copyBtn.disabled = !state.code;
  }
  if (event.type === "artifacts") renderArtifacts(event.items || [], event.metrics || [], event.roller_loads || []);
  if (event.type === "response") el("agentResponse").textContent = event.text || "运行完成。";
  if (event.type === "complete") {
    const snapshot = event.session || {};
    if (snapshot.code && !state.code) { state.code = snapshot.code; codeView.textContent = state.code.slice(0, 60000); copyBtn.disabled = false; }
    renderArtifacts(snapshot.artifacts || [], snapshot.metrics || [], snapshot.roller_loads || []);
    el("sessionBadge").textContent = `${state.mode.toUpperCase()} · COMPLETE`;
  }
  if (event.type === "error") el("agentResponse").textContent = `运行失败：${event.message}`;
}

async function run() {
  if (state.running || !requirement.value.trim()) return;
  state.running = true;
  resetRun(state.mode === "live" && Boolean(state.sessionId));
  runBtn.disabled = true;
  runBtn.querySelector("span").textContent = "运行中";
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ requirement: requirement.value.trim(), mode: state.mode, session_id: state.sessionId }),
    });
    if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() || "";
      blocks.forEach((block) => {
        const dataLine = block.split("\n").find((line) => line.startsWith("data: "));
        if (dataLine) handleEvent(JSON.parse(dataLine.slice(6)));
      });
    }
  } catch (error) {
    handleEvent({ type: "error", message: error.message, timestamp: new Date().toISOString() });
  } finally {
    state.running = false;
    runBtn.disabled = false;
    runBtn.querySelector("span").textContent = state.mode === "demo" ? "再次回放" : "继续对话";
  }
}

function renderArtifacts(items, metrics, loads) {
  renderMetrics(metrics);
  state.loads = loads;
  drawLoads(loads);
  const images = items.filter((item) => item.kind === "image");
  const files = items.filter((item) => item.kind !== "image");
  el("artifactCount").textContent = `${items.length} FILES`;
  const gallery = el("gallery");
  gallery.innerHTML = "";
  const fileList = el("fileList");
  fileList.innerHTML = "";
  files.forEach((item) => {
    const link = document.createElement("a");
    link.className = "file-chip"; link.href = item.url; link.target = "_blank"; link.rel = "noreferrer";
    link.textContent = `${item.kind.toUpperCase()} · ${item.name}`;
    fileList.append(link);
  });
  gallery.className = images.length ? "gallery" : "gallery empty-gallery";
  if (!images.length) { gallery.innerHTML = "<p>本次运行尚未导出图像</p>"; return; }
  images.forEach((item) => {
    const card = document.createElement("a");
    card.className = `artifact-card artifact-link ${item.id === "stress" ? "featured" : ""}`;
    card.href = item.url; card.target = "_blank"; card.rel = "noreferrer";
    const image = document.createElement("img"); image.src = item.url; image.alt = item.name; image.loading = "lazy";
    const caption = document.createElement("span"); caption.className = "artifact-caption"; caption.textContent = item.name;
    card.append(image, caption); gallery.append(card);
  });
}

function renderMetrics(metrics) {
  const grid = el("metricGrid");
  if (!metrics.length) return;
  grid.innerHTML = "";
  metrics.forEach((metric) => {
    const card = document.createElement("div"); card.className = `metric-card ${metric.tone || "blue"}`;
    const label = document.createElement("span"); label.className = "metric-label"; label.textContent = metric.label;
    const value = document.createElement("strong"); value.className = "metric-value"; value.textContent = metric.value;
    card.append(label, value); grid.append(card);
  });
}

function numericLoad(row) {
  const keys = ["outer_magnitude_n", "outer_contact_force_magnitude_n", "force_magnitude_n", "magnitude_n", "load_n", "value"];
  for (const key of keys) if (row[key] !== undefined && Number.isFinite(Number(row[key]))) return Number(row[key]);
  const values = Object.values(row).map(Number).filter(Number.isFinite);
  return values.length ? values[values.length - 1] : 0;
}

function drawLoads(rows) {
  const canvas = el("loadChart");
  const box = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(400, box.width * ratio); canvas.height = 390 * ratio;
  const ctx = canvas.getContext("2d"); ctx.scale(ratio, ratio);
  const width = canvas.width / ratio, height = canvas.height / ratio;
  ctx.clearRect(0, 0, width, height);
  const values = rows.slice(0, 12).map(numericLoad);
  if (!values.length) {
    ctx.fillStyle = "#6f829c"; ctx.font = "12px sans-serif"; ctx.textAlign = "center"; ctx.fillText("等待载荷数据", width / 2, height / 2); return;
  }
  const pad = { left: 36, right: 12, top: 28, bottom: 44 }, chartW = width - pad.left - pad.right, chartH = height - pad.top - pad.bottom;
  const max = Math.max(...values, 1) * 1.12;
  ctx.strokeStyle = "rgba(130,160,200,.14)"; ctx.fillStyle = "#6f829c"; ctx.font = "9px monospace";
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + chartH * i / 4; ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
    ctx.textAlign = "right"; ctx.fillText((max * (4 - i) / 4).toFixed(1), pad.left - 7, y + 3);
  }
  const slot = chartW / values.length, barW = Math.max(8, slot * .56);
  values.forEach((value, index) => {
    const barH = value / max * chartH, x = pad.left + slot * index + (slot - barW) / 2, y = pad.top + chartH - barH;
    ctx.fillStyle = value > .05 ? "#438cff" : "#26364b"; ctx.fillRect(x, y, barW, barH);
    ctx.fillStyle = "#7f92ab"; ctx.textAlign = "center"; ctx.fillText(`R${index + 1}`, x + barW / 2, pad.top + chartH + 19);
  });
}

runBtn.addEventListener("click", run);
copyBtn.addEventListener("click", async () => { if (state.code) await navigator.clipboard.writeText(state.code); });
window.addEventListener("resize", () => drawLoads(state.loads));
bootstrap();

/**
 * Bilibili Video Downloader - Frontend Logic
 *
 * Handles URL parsing, video info display, download initiation,
 * SSE progress updates, and downloads list management.
 */

// ── State ────────────────────────────────────────────────────────────────────

const state = {
  videoInfo: null,       // Parsed video metadata
  activeTasks: {},       // task_id -> { element, stage, progress }
};

// ── DOM Elements ─────────────────────────────────────────────────────────────

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const urlInput = $("#urlInput");
const cookieInput = $("#cookieInput");
const parseBtn = $("#parseBtn");
const cookieToggle = $("#cookieToggle");
const cookiePanel = $("#cookiePanel");
const loadingCard = $("#loadingCard");
const errorCard = $("#errorCard");
const errorText = $("#errorText");
const videoCard = $("#videoCard");
const videoCover = $("#videoCover");
const videoTitle = $("#videoTitle");
const videoOwner = $("#videoOwner");
const videoDuration = $("#videoDuration");
const videoViews = $("#videoViews");
const videoDanmaku = $("#videoDanmaku");
const partSelector = $("#partSelector");
const partSelect = $("#partSelect");
const qualitySelect = $("#qualitySelect");
const downloadBtn = $("#downloadBtn");
const progressSection = $("#progressSection");
const progressCards = $("#progressCards");
const downloadsList = $("#downloadsList");

// ── Event Listeners ──────────────────────────────────────────────────────────

parseBtn.addEventListener("click", handleParse);
cookieToggle.addEventListener("click", toggleCookiePanel);
downloadBtn.addEventListener("click", handleDownload);
urlInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") handleParse();
});

// ── Cookie Panel ─────────────────────────────────────────────────────────────

function toggleCookiePanel() {
  const isOpen = !cookiePanel.classList.contains("hidden");
  if (isOpen) {
    cookiePanel.classList.add("hidden");
    cookieToggle.classList.remove("active");
  } else {
    cookiePanel.classList.remove("hidden");
    cookieToggle.classList.add("active");
  }
}

// Also auto-open if Enter is pressed in the panel
cookiePanel.querySelector(".cookie-input")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.stopPropagation();
  }
});

// ── Parse URL ────────────────────────────────────────────────────────────────

async function handleParse() {
  const url = urlInput.value.trim();
  if (!url) {
    showError("请输入 Bilibili 视频链接");
    return;
  }

  const cookie = cookieInput.value.trim();

  // Show loading
  hideError();
  hideVideoCard();
  loadingCard.classList.remove("hidden");
  parseBtn.disabled = true;

  try {
    const resp = await fetch("/api/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, cookie }),
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData.detail || `请求失败 (${resp.status})`);
    }

    const data = await resp.json();
    state.videoInfo = data;
    renderVideoCard(data);
  } catch (err) {
    showError(err.message);
  } finally {
    loadingCard.classList.add("hidden");
    parseBtn.disabled = false;
  }
}

// ── Render Video Card ────────────────────────────────────────────────────────

function renderVideoCard(data) {
  videoCover.src = data.cover || "";
  videoTitle.textContent = data.title || "未知标题";
  videoOwner.textContent = data.owner_name || "未知";
  videoDuration.textContent = formatDuration(data.duration || 0);
  videoViews.textContent = formatNumber(data.stat?.view || 0);
  videoDanmaku.textContent = formatNumber(data.stat?.danmaku || 0);

  // Part selector
  if (data.pages && data.pages.length > 1) {
    partSelector.classList.remove("hidden");
    partSelect.innerHTML = data.pages
      .map((p, i) => `<option value="${i}" data-cid="${p.cid}">P${p.page}: ${p.title || `选集 ${p.page}`}</option>`)
      .join("");
  } else {
    partSelector.classList.add("hidden");
  }

  // Quality selector
  qualitySelect.innerHTML = data.qualities
    .map((q) => {
      const disabled = !q.available ? "disabled" : "";
      const extra = q.requires_vip ? " (VIP)" : q.requires_login ? " (需登录)" : "";
      return `<option value="${q.qn}" ${disabled}>${q.label}${extra}</option>`;
    })
    .join("");

  // Auto-select first available quality
  const firstAvailable = data.qualities.find((q) => q.available);
  if (firstAvailable) {
    qualitySelect.value = firstAvailable.qn;
  }

  videoCard.classList.remove("hidden");
}

function hideVideoCard() {
  videoCard.classList.add("hidden");
}

// ── Download ─────────────────────────────────────────────────────────────────

async function handleDownload() {
  if (!state.videoInfo) return;

  const data = state.videoInfo;
  const cookie = cookieInput.value.trim();
  const quality = parseInt(qualitySelect.value);

  // Determine which page (part) to download
  let cid, partTitle, pageNum;
  if (data.pages && data.pages.length > 1) {
    const idx = parseInt(partSelect.value);
    cid = data.pages[idx].cid;
    partTitle = data.pages[idx].title || `P${data.pages[idx].page}`;
    pageNum = data.pages[idx].page;
  } else {
    cid = data.pages[0]?.cid || data.cid;
    partTitle = data.pages[0]?.title || "";
    pageNum = 1;
  }

  downloadBtn.disabled = true;
  downloadBtn.textContent = "创建下载任务...";

  try {
    const resp = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        bvid: data.bvid,
        cid: cid,
        title: data.title,
        part_title: partTitle,
        cookie: cookie,
        quality: quality,
      }),
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData.detail || `创建下载失败 (${resp.status})`);
    }

    const result = await resp.json();
    const taskId = result.task_id;

    // Create progress card
    createProgressCard(taskId, `${data.title}${partTitle ? " - " + partTitle : ""}`);
    progressSection.classList.remove("hidden");

    // Connect SSE for real-time progress
    connectSSE(taskId);

    downloadBtn.textContent = "⬇ 开始下载";
  } catch (err) {
    showError(err.message);
  } finally {
    downloadBtn.disabled = false;
  }
}

// ── Progress UI ──────────────────────────────────────────────────────────────

function createProgressCard(taskId, title) {
  const card = document.createElement("div");
  card.className = "progress-card";
  card.id = `progress-${taskId}`;
  card.innerHTML = `
    <div class="progress-header">
      <span class="progress-title" title="${escapeHtml(title)}">${escapeHtml(title)}</span>
      <span class="progress-stage">等待开始...</span>
    </div>
    <div class="progress-bar-track">
      <div class="progress-bar-fill" style="width: 0%"></div>
    </div>
    <div class="progress-result"></div>
  `;
  progressCards.appendChild(card);

  state.activeTasks[taskId] = { element: card, stage: "", progress: 0 };
}

function updateProgressCard(taskId, stage, progress, stageText) {
  const task = state.activeTasks[taskId];
  if (!task) return;

  const card = task.element;
  const fill = card.querySelector(".progress-bar-fill");
  const stageEl = card.querySelector(".progress-stage");
  const resultEl = card.querySelector(".progress-result");

  fill.style.width = `${progress}%`;
  if (stageText) {
    stageEl.textContent = `${stageText} (${progress.toFixed(1)}%)`;
  }

  if (stage === "complete") {
    card.classList.add("complete");
    stageEl.textContent = "✅ 完成";
    fill.style.width = "100%";
  } else if (stage === "error") {
    card.classList.add("error");
    stageEl.textContent = "❌ 失败";
  }
}

function updateProgressComplete(taskId, outputFile, danmakuFile, danmakuCount) {
  const task = state.activeTasks[taskId];
  if (!task) return;

  const card = task.element;
  card.classList.add("complete");
  const fill = card.querySelector(".progress-bar-fill");
  const stageEl = card.querySelector(".progress-stage");
  const resultEl = card.querySelector(".progress-result");

  fill.style.width = "100%";
  stageEl.textContent = "✅ 完成";

  resultEl.innerHTML = `
    视频: ${escapeHtml(outputFile)} |
    弹幕: ${danmakuCount} 条
  `;

  // Refresh downloads list
  refreshDownloads();
}

function updateProgressError(taskId, message) {
  const task = state.activeTasks[taskId];
  if (!task) return;

  const card = task.element;
  card.classList.add("error");
  const fill = card.querySelector(".progress-bar-fill");
  const stageEl = card.querySelector(".progress-stage");
  const resultEl = card.querySelector(".progress-result");

  fill.style.width = "100%";
  stageEl.textContent = "❌ 失败";
  resultEl.textContent = message;

  downloadBtn.disabled = false;
  downloadBtn.textContent = "⬇ 重试下载";
}

// ── SSE Connection ───────────────────────────────────────────────────────────

function connectSSE(taskId) {
  const evtSource = new EventSource(`/api/progress/${taskId}`);

  evtSource.addEventListener("progress", (e) => {
    const data = JSON.parse(e.data);
    updateProgressCard(taskId, data.stage, data.progress, data.stage_text);
  });

  evtSource.addEventListener("complete", (e) => {
    const data = JSON.parse(e.data);
    updateProgressComplete(taskId, data.output_file, data.danmaku_file, data.danmaku_count);
    evtSource.close();
  });

  evtSource.addEventListener("error", (e) => {
    let message = "下载失败";
    try {
      const data = JSON.parse(e.data);
      message = data.message || message;
    } catch (_) {}
    updateProgressError(taskId, message);
    evtSource.close();
  });

  evtSource.addEventListener("ping", () => {
    // Keep-alive, no action needed
  });

  // Native EventSource reconnect on connection error
  evtSource.onerror = () => {
    // Will auto-reconnect; if persistent, show in UI
    const task = state.activeTasks[taskId];
    if (task && task.element) {
      const stageEl = task.element.querySelector(".progress-stage");
      if (stageEl && !task.element.classList.contains("complete") &&
          !task.element.classList.contains("error")) {
        stageEl.textContent = "重连中...";
      }
    }
  };
}

// ── Downloads List ───────────────────────────────────────────────────────────

async function refreshDownloads() {
  try {
    const resp = await fetch("/api/downloads");
    const data = await resp.json();

    if (data.files.length === 0) {
      downloadsList.innerHTML = '<p class="empty-hint">暂无下载记录</p>';
      return;
    }

    downloadsList.innerHTML = data.files
      .map((f) => `
        <div class="download-item">
          <span class="file-name" title="${escapeHtml(f.name)}">${escapeHtml(f.name)}</span>
          <span class="file-size">${formatSize(f.size)}</span>
        </div>
      `)
      .join("");
  } catch (_) {
    // Silently fail — downloads list is non-critical
  }
}

// ── Error Handling ───────────────────────────────────────────────────────────

function showError(msg) {
  errorText.textContent = msg;
  errorCard.classList.remove("hidden");
}

function hideError() {
  errorCard.classList.add("hidden");
}

function dismissError() {
  errorCard.classList.add("hidden");
}

// ── Utility Functions ────────────────────────────────────────────────────────

function formatDuration(seconds) {
  if (!seconds || seconds <= 0) return "未知";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatNumber(n) {
  if (n >= 10000) return (n / 10000).toFixed(1) + "万";
  if (n >= 1000) return (n / 1000).toFixed(1) + "k";
  return String(n);
}

function formatSize(bytes) {
  if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + " GB";
  if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + " MB";
  if (bytes >= 1024) return (bytes / 1024).toFixed(1) + " KB";
  return bytes + " B";
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ── Init ─────────────────────────────────────────────────────────────────────

// Load saved cookie on page load
async function loadSavedCookie() {
  try {
    const resp = await fetch("/api/cookie");
    const data = await resp.json();
    if (data.cookie) {
      cookieInput.value = data.cookie;
      // Show the panel so user knows there's a saved cookie
      cookiePanel.classList.remove("hidden");
      cookieToggle.classList.add("active");
      // Truncate for display in placeholder
      const short = data.cookie.length > 50
        ? data.cookie.substring(0, 50) + "..."
        : data.cookie;
      cookieToggle.title = "Cookie: " + short;
    }
  } catch (_) {
    // Non-critical — just leave input empty
  }
}

// Load existing downloads on page load
refreshDownloads();
loadSavedCookie();

// Auto-parse if URL hash contains a BV ID
if (window.location.hash) {
  const hash = window.location.hash.slice(1);
  if (/^BV[a-zA-Z0-9]{10}$/.test(hash)) {
    urlInput.value = `https://www.bilibili.com/video/${hash}`;
  }
}

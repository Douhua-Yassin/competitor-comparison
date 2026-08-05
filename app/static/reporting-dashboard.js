const state = {
  dashboard: null,
  dirtyNotes: new Map(),
  syncTimer: null,
};

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const data = await response.json();
      message = data.detail || message;
    } catch (_) {}
    throw new Error(message);
  }
  const type = response.headers.get("content-type") || "";
  return type.includes("application/json") ? response.json() : response;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatNumber(value, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return "缺失";
  return Number(value).toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatCount(value) {
  if (value == null || Number.isNaN(Number(value))) return "缺失";
  return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

function formatRatio(value) {
  if (value == null || Number.isNaN(Number(value))) return "缺失";
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function formatChange(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return { text: "无法比较", className: "change-neutral" };
  }
  const number = Number(value);
  return {
    text: `${number > 0 ? "+" : ""}${(number * 100).toFixed(1)}%`,
    className: number > 0 ? "change-up" : number < 0 ? "change-down" : "change-neutral",
  };
}

function metricCard(label, code, value, formatter, comparisons) {
  const change = formatChange(comparisons?.[code]);
  return `
    <article class="metric-card">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(formatter(value))}</strong>
      <em class="${change.className}">环比 ${escapeHtml(change.text)}</em>
    </article>`;
}

function linePath(values, width, height, padding) {
  const valid = values
    .map((value, index) => ({ value: value == null ? null : Number(value), index }))
    .filter((item) => item.value != null && Number.isFinite(item.value));
  if (!valid.length) return "";
  const max = Math.max(...valid.map((item) => item.value));
  const min = Math.min(...valid.map((item) => item.value));
  const range = max - min || 1;
  const count = Math.max(values.length - 1, 1);
  return valid
    .map((item, order) => {
      const x = padding + (item.index / count) * (width - padding * 2);
      const y = height - padding - ((item.value - min) / range) * (height - padding * 2);
      return `${order === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

function renderChart(series) {
  const width = 760;
  const height = 180;
  const padding = 18;
  const salesPath = linePath(series.sales_amount || [], width, height, padding);
  const adPath = linePath(series.ad_spend || [], width, height, padding);
  if (!salesPath && !adPath) {
    return '<div class="chart-wrap"><div class="empty-state">该周期暂无可绘制的逐日数据</div></div>';
  }
  const firstDate = series.dates?.[0] || "";
  const lastDate = series.dates?.[series.dates.length - 1] || "";
  return `
    <div class="chart-wrap">
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="销售额和广告花费趋势图">
        <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" stroke="#dfe5ee"/>
        ${salesPath ? `<path d="${salesPath}" fill="none" stroke="#1f5eff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>` : ""}
        ${adPath ? `<path d="${adPath}" fill="none" stroke="#d66b00" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>` : ""}
        <text x="${padding}" y="${height - 2}" font-size="11" fill="#68758b">${escapeHtml(firstDate)}</text>
        <text x="${width - padding}" y="${height - 2}" text-anchor="end" font-size="11" fill="#68758b">${escapeHtml(lastDate)}</text>
      </svg>
      <div class="chart-legend">
        <span class="legend-sales"><i class="legend-line"></i>销售额</span>
        <span class="legend-ad"><i class="legend-line"></i>广告花费</span>
      </div>
    </div>`;
}

function windowHtml(line, windowData) {
  const summary = windowData.summary || {};
  const comparisons = windowData.comparisons || {};
  const note = windowData.note || { content: "", updated_at: null };
  const warnings = (windowData.warnings || [])
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
  const key = `${line}::${windowData.code}::${windowData.period_key}`;
  return `
    <section class="window-row">
      <div class="data-pane">
        <div class="window-title">
          <div>
            <h3>${escapeHtml(windowData.label)}</h3>
            <small>${escapeHtml(windowData.start)} 至 ${escapeHtml(windowData.end)}</small>
          </div>
        </div>
        <div class="metric-grid">
          ${metricCard("销售额", "sales_amount", summary.sales_amount, (v) => formatNumber(v, 2), comparisons)}
          ${metricCard("销量", "units", summary.units, formatCount, comparisons)}
          ${metricCard("广告花费", "ad_spend", summary.ad_spend, (v) => formatNumber(v, 2), comparisons)}
          ${metricCard("广告销售额", "ad_sales", summary.ad_sales, (v) => formatNumber(v, 2), comparisons)}
          ${metricCard("TACOS", "tacos", summary.tacos, formatRatio, comparisons)}
          ${metricCard("CTR", "ctr", summary.ctr, formatRatio, comparisons)}
          ${metricCard("CPC", "cpc", summary.cpc, (v) => formatNumber(v, 2), comparisons)}
          ${metricCard("CVR", "cvr", summary.cvr, formatRatio, comparisons)}
          ${metricCard("退款金额", "refund_amount", summary.refund_amount, (v) => formatNumber(v, 2), comparisons)}
          ${metricCard("FBA可售", "fba_available", summary.fba_available, formatCount, comparisons)}
        </div>
        ${renderChart(windowData.series || {})}
        ${windowData.source_note ? `<p class="source-note">${escapeHtml(windowData.source_note)}</p>` : ""}
        ${warnings ? `<ul class="warning-list">${warnings}</ul>` : ""}
      </div>
      <div class="note-pane">
        <div class="window-title">
          <div>
            <h3>${escapeHtml(windowData.label)}记录</h3>
            <small>操作、原因、判断、计划和需要的支持</small>
          </div>
        </div>
        <textarea
          data-note-key="${escapeHtml(key)}"
          data-line="${escapeHtml(line)}"
          data-window="${escapeHtml(windowData.code)}"
          data-period="${escapeHtml(windowData.period_key)}"
          placeholder="在这里记录本周期发生的事情。内容每60秒自动保存。"
        >${escapeHtml(note.content || "")}</textarea>
        <div class="note-footer">
          <span class="note-status" data-note-status="${escapeHtml(key)}">${note.updated_at ? `已保存：${escapeHtml(note.updated_at)}` : "尚未保存"}</span>
          <button type="button" data-save-note="${escapeHtml(key)}">保存</button>
        </div>
      </div>
    </section>`;
}

function moduleHtml(module) {
  const line = module.product_line;
  const encoded = encodeURIComponent(line);
  return `
    <article class="product-line-module">
      <header class="module-heading">
        <div>
          <h2>${escapeHtml(line)}</h2>
          <p>${module.product_count} 个重点 Listing</p>
        </div>
        <div class="report-actions">
          <a href="/api/reporting/reports/day?product_line=${encoded}">下载日报</a>
          <a href="/api/reporting/reports/week?product_line=${encoded}">下载周报</a>
          <a href="/api/reporting/reports/month?product_line=${encoded}">下载月报</a>
        </div>
      </header>
      ${module.windows.map((item) => windowHtml(line, item)).join("")}
    </article>`;
}

function attachNoteHandlers() {
  document.querySelectorAll("textarea[data-note-key]").forEach((textarea) => {
    textarea.addEventListener("input", () => {
      state.dirtyNotes.set(textarea.dataset.noteKey, textarea);
      const status = document.querySelector(`[data-note-status="${CSS.escape(textarea.dataset.noteKey)}"]`);
      if (status) status.textContent = "有未保存修改";
    });
  });
  document.querySelectorAll("[data-save-note]").forEach((button) => {
    button.addEventListener("click", async () => {
      const textarea = document.querySelector(`textarea[data-note-key="${CSS.escape(button.dataset.saveNote)}"]`);
      if (textarea) await saveNote(textarea);
    });
  });
}

async function saveNote(textarea, keepalive = false) {
  const key = textarea.dataset.noteKey;
  const status = document.querySelector(`[data-note-status="${CSS.escape(key)}"]`);
  if (status) status.textContent = "正在保存……";
  try {
    const response = await fetch("/api/reporting/notes", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        product_line: textarea.dataset.line,
        window_code: textarea.dataset.window,
        period_key: textarea.dataset.period,
        content: textarea.value,
      }),
      keepalive,
    });
    if (!response.ok) throw new Error(`保存失败：${response.status}`);
    const data = await response.json();
    state.dirtyNotes.delete(key);
    if (status) status.textContent = `已保存：${data.updated_at}`;
  } catch (error) {
    if (status) status.textContent = `保存失败：${error.message}`;
  }
}

async function saveAllDirty(keepalive = false) {
  const pending = [...state.dirtyNotes.values()];
  for (const textarea of pending) {
    await saveNote(textarea, keepalive);
  }
}

async function loadDashboard() {
  const root = document.getElementById("dashboard");
  try {
    const data = await api("/api/reporting/dashboard");
    state.dashboard = data;
    const lastSync = data.last_sync;
    document.getElementById("syncSummary").textContent = lastSync?.finished_at
      ? `最近同步：${lastSync.finished_at} · 最近14天滚动更新，两周前数据冻结`
      : "尚未完成领星数据同步";
    if (!data.product_lines.length) {
      root.innerHTML = '<div class="empty-state">尚未设置重点产品。请进入右上角“设置”，从领星 Listing 中标记重点产品并填写产品线。</div>';
      return;
    }
    root.innerHTML = data.product_lines.map(moduleHtml).join("");
    attachNoteHandlers();
  } catch (error) {
    root.innerHTML = `<div class="empty-state">加载失败：${escapeHtml(error.message)}</div>`;
  }
}

async function pollSyncStatus() {
  try {
    const status = await api("/api/reporting/sync-status");
    const strip = document.getElementById("syncStatus");
    strip.textContent = status.message || "";
    document.getElementById("syncButton").disabled = Boolean(status.running);
    if (status.running) {
      state.syncTimer = setTimeout(pollSyncStatus, 1500);
    } else {
      clearTimeout(state.syncTimer);
      await loadDashboard();
    }
  } catch (error) {
    document.getElementById("syncStatus").textContent = `同步状态读取失败：${error.message}`;
  }
}

async function startSync() {
  const button = document.getElementById("syncButton");
  button.disabled = true;
  try {
    await api("/api/reporting/sync", { method: "POST", body: "{}" });
    await pollSyncStatus();
  } catch (error) {
    button.disabled = false;
    showDialog("同步失败", error.message);
  }
}

function showDialog(title, body) {
  document.getElementById("dialogTitle").textContent = title;
  document.getElementById("dialogBody").textContent = body;
  document.getElementById("messageDialog").showModal();
}

document.getElementById("syncButton").addEventListener("click", startSync);
setInterval(() => saveAllDirty(false), 60000);
window.addEventListener("beforeunload", () => {
  for (const textarea of state.dirtyNotes.values()) {
    saveNote(textarea, true);
  }
});

loadDashboard();
pollSyncStatus();

(() => {
  const dashboardRoot = document.getElementById("dashboard");
  if (!dashboardRoot) return;
  let rendering = false;
  let scheduled = null;

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatMetric(value, unit) {
    if (value == null || Number.isNaN(Number(value))) return "缺失";
    const number = Number(value);
    if (unit === "ratio") return `${(number * 100).toFixed(2)}%`;
    if (unit === "count") return number.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
    return number.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function statusText(value) {
    return {
      achieved: "已达到",
      in_progress: "进行中",
      exceeded: "超过上限",
      within_budget: "预算内",
      over_budget: "超预算",
      missing: "实际缺失",
      reference: "参考值",
    }[value] || value || "参考值";
  }

  function targetHtml(targets) {
    if (!targets?.length) return "";
    return `
      <section class="target-progress" data-target-progress>
        <h4>目标完成情况</h4>
        <div class="target-grid">
          ${targets.map((item) => `
            <article class="target-card target-${escapeHtml(item.status)}">
              <span>${escapeHtml(item.label)}</span>
              <strong>${escapeHtml(formatMetric(item.actual, item.unit))} / ${escapeHtml(formatMetric(item.target, item.unit))}</strong>
              <em>${item.completion == null ? "无法计算" : `完成/使用率 ${(Number(item.completion) * 100).toFixed(1)}%`} · ${escapeHtml(statusText(item.status))}</em>
              <small>${escapeHtml(item.scope_note || "")}</small>
            </article>`).join("")}
        </div>
      </section>`;
  }

  async function fetchJson(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  }

  async function enrichDashboard() {
    if (rendering) return;
    rendering = true;
    try {
      const data = await fetchJson("/api/reporting/dashboard");
      const modules = [...dashboardRoot.querySelectorAll(".product-line-module")];
      for (const moduleData of data.product_lines || []) {
        const moduleNode = modules.find((node) => node.querySelector(".module-heading h2")?.textContent.trim() === moduleData.product_line);
        if (!moduleNode) continue;
        const rows = [...moduleNode.querySelectorAll(".window-row")];
        moduleData.windows.forEach((windowData, index) => {
          const row = rows[index];
          if (!row || row.querySelector("[data-target-progress]")) return;
          const metrics = row.querySelector(".metric-grid");
          if (metrics && windowData.targets?.length) {
            metrics.insertAdjacentHTML("afterend", targetHtml(windowData.targets));
          }
        });
        const actions = moduleNode.querySelector(".report-actions");
        if (actions && !actions.querySelector("[data-report-history]")) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "history-button";
          button.dataset.reportHistory = moduleData.product_line;
          button.textContent = "历史报告";
          button.addEventListener("click", () => showHistory(moduleData.product_line));
          actions.appendChild(button);
        }
      }
    } catch (_) {
      // Main dashboard already renders its own visible API errors.
    } finally {
      rendering = false;
    }
  }

  async function showHistory(productLine) {
    const dialog = document.getElementById("messageDialog");
    const title = document.getElementById("dialogTitle");
    const body = document.getElementById("dialogBody");
    if (!dialog || !title || !body) return;
    title.textContent = `${productLine}历史报告`;
    body.textContent = "正在读取……";
    dialog.showModal();
    try {
      const data = await fetchJson(`/api/reporting/reports/history?product_line=${encodeURIComponent(productLine)}&limit=20`);
      body.innerHTML = data.reports?.length
        ? `<span class="history-list">${data.reports.map((item) => `
            <a href="/api/reporting/reports/archive/${item.id}">
              ${escapeHtml(item.created_at)} · ${escapeHtml(item.report_type)} · ${escapeHtml(item.period_start)}至${escapeHtml(item.period_end)} · ${escapeHtml(item.analysis_source)}
            </a>`).join("")}</span>`
        : "尚无归档报告。";
    } catch (error) {
      body.textContent = `读取失败：${error.message}`;
    }
  }

  const observer = new MutationObserver(() => {
    window.clearTimeout(scheduled);
    scheduled = window.setTimeout(enrichDashboard, 80);
  });
  observer.observe(dashboardRoot, { childList: true, subtree: true });
  enrichDashboard();
})();

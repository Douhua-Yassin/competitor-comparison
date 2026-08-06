const acceptanceState = { timer: null, lastRunId: null };

async function acceptanceApi(url) {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const data = await response.json();
      message = data.detail || message;
    } catch (_) {}
    throw new Error(message);
  }
  return response.json();
}

function acceptanceEscape(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function acceptanceNumber(value) {
  return Number.isFinite(Number(value)) ? Number(value).toLocaleString("zh-CN") : "-";
}

function renderAcceptance(payload) {
  const summary = document.getElementById("acceptanceSummary");
  const message = document.getElementById("acceptanceMessage");
  const issues = document.getElementById("acceptanceIssues");
  const endpoints = document.getElementById("acceptanceEndpoints");
  const lines = document.getElementById("acceptanceProductLines");
  const generated = document.getElementById("acceptanceGeneratedAt");

  generated.textContent = payload.generated_at ? `生成于 ${payload.generated_at}` : "";
  message.textContent = payload.message || "";

  const catalog = payload.catalog || {};
  const latest = payload.latest_run || {};
  summary.innerHTML = [
    ["活跃Listing", catalog.active_listings],
    ["当前负责产品", catalog.selected_listings],
    ["重点产品", catalog.key_listings],
    ["普通产品", catalog.normal_listings],
    ["产品线", catalog.product_lines],
    ["最近写入指标", latest.metric_count],
  ].map(([label, value]) => `
    <div class="acceptance-stat">
      <small>${acceptanceEscape(label)}</small>
      <strong>${acceptanceNumber(value)}</strong>
    </div>`).join("");

  const blocking = payload.blocking_issues || [];
  if (blocking.length) {
    issues.hidden = false;
    issues.innerHTML = `<strong>需要处理</strong><ul>${blocking.map((item) => `<li>${acceptanceEscape(item)}</li>`).join("")}</ul>`;
  } else {
    issues.hidden = true;
    issues.innerHTML = "";
  }

  const endpointRows = payload.endpoints || [];
  endpoints.innerHTML = endpointRows.length
    ? endpointRows.map((item) => {
        const ratio = item.coverage_ratio == null
          ? "-"
          : `${(Number(item.coverage_ratio) * 100).toFixed(1)}%`;
        const dateRange = item.first_date ? `${item.first_date} ~ ${item.last_date}` : "-";
        return `
          <article class="acceptance-endpoint">
            <h3>
              ${acceptanceEscape(item.label)}
              <span class="acceptance-badge ${acceptanceEscape(item.status)}">${acceptanceEscape(item.status_label)}</span>
            </h3>
            <dl>
              <dt>有数据产品</dt><dd>${acceptanceNumber(item.listings_with_data)} / ${acceptanceNumber(item.selected_listings)}</dd>
              <dt>覆盖比例</dt><dd>${acceptanceEscape(ratio)}</dd>
              <dt>指标行</dt><dd>${acceptanceNumber(item.metric_rows)}</dd>
              <dt>日期范围</dt><dd>${acceptanceEscape(dateRange)}</dd>
            </dl>
          </article>`;
      }).join("")
    : '<p class="acceptance-muted">尚无可展示的接口验收结果。</p>';

  const productLines = payload.product_lines || [];
  lines.innerHTML = productLines.length
    ? `
      <table>
        <thead>
          <tr>
            <th>产品线</th><th>Listing</th><th>店铺</th><th>销售</th><th>售后</th><th>库存</th><th>SP广告</th>
          </tr>
        </thead>
        <tbody>
          ${productLines.map((item) => `
            <tr>
              <td><strong>${acceptanceEscape(item.product_line)}</strong><br><span class="acceptance-muted">${acceptanceEscape((item.countries || []).join("、"))}</span></td>
              <td>${acceptanceNumber(item.listing_count)}（重点 ${acceptanceNumber(item.key_count)} / 普通 ${acceptanceNumber(item.normal_count)}）</td>
              <td>${acceptanceNumber(item.store_count)}</td>
              <td>${acceptanceNumber(item.endpoints?.orders?.listings_with_data)} 个产品</td>
              <td>${acceptanceNumber(item.endpoints?.after_sales?.listings_with_data)} 个产品</td>
              <td>${acceptanceNumber(item.endpoints?.fba_inventory?.listings_with_data)} 个产品</td>
              <td>${acceptanceNumber(item.endpoints?.sp_product_report?.listings_with_data)} 个产品</td>
            </tr>`).join("")}
        </tbody>
      </table>`
    : '<p class="acceptance-muted">当前没有重点或普通产品线。</p>';

  acceptanceState.lastRunId = payload.latest_run?.id || null;
}

async function loadAcceptance() {
  const refresh = document.getElementById("acceptanceRefreshButton");
  refresh.disabled = true;
  try {
    const payload = await acceptanceApi("/api/reporting/acceptance/latest");
    renderAcceptance(payload);
  } catch (error) {
    document.getElementById("acceptanceMessage").textContent = `验收结果读取失败：${error.message}`;
  } finally {
    refresh.disabled = false;
  }
}

async function watchAcceptance() {
  try {
    const status = await acceptanceApi("/api/reporting/sync-status");
    if (!status.running) {
      const payload = await acceptanceApi("/api/reporting/acceptance/latest");
      const runId = payload.latest_run?.id || null;
      if (runId !== acceptanceState.lastRunId) renderAcceptance(payload);
    }
  } catch (_) {}
  acceptanceState.timer = setTimeout(watchAcceptance, 5000);
}

document.getElementById("acceptanceRefreshButton").addEventListener("click", loadAcceptance);
loadAcceptance();
watchAcceptance();
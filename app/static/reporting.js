const state = {
  overview: null,
  targets: [],
  actions: [],
};

const levelLabels = {
  not_mine: "不归我负责",
  normal: "我负责·普通产品",
  key: "我负责·重点产品",
};

const statusLabels = {
  planned: "计划中",
  in_progress: "执行中",
  completed: "已完成",
  cancelled: "已取消",
};

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `请求失败：${response.status}`);
  }
  return payload;
}

function showDialog(title, payload) {
  document.getElementById("dialogTitle").textContent = title;
  document.getElementById("dialogBody").textContent =
    typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
  document.getElementById("resultDialog").showModal();
}

function setPageStatus(text) {
  document.getElementById("pageStatus").textContent = text;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDateTime(value) {
  if (!value) return "未导入";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("zh-CN");
}

function lineById(id) {
  return state.overview?.product_lines.find((line) => Number(line.id) === Number(id));
}

function renderSummary() {
  const data = state.overview;
  document.getElementById("lastImport").textContent = data.last_import
    ? `${data.last_import.source_run_id} · ${formatDateTime(data.last_import.created_at)}`
    : "未导入";
  document.getElementById("snapshotCount").textContent = data.snapshot_count;
  document.getElementById("metricCount").textContent = data.metric_count;
}

function renderAvailability() {
  const root = document.getElementById("availability");
  const rows = state.overview.availability || [];
  if (!rows.length) {
    root.innerHTML = '<p class="empty">尚未导入领星盘点结果。</p>';
    return;
  }
  root.innerHTML = rows
    .map(
      (row) => `
      <article class="availability-card ${escapeHtml(row.status)}">
        <strong>${escapeHtml(row.label || row.endpoint_key)}</strong>
        <small>${escapeHtml(row.category || "未分类")} · ${escapeHtml(row.status)}</small>
        ${row.message ? `<p>${escapeHtml(row.message.slice(0, 260))}</p>` : ""}
      </article>`,
    )
    .join("");
}

function levelOptions(selected, allowInherit = false) {
  const options = [];
  if (allowInherit) {
    options.push(`<option value="" ${selected == null ? "selected" : ""}>继承产品线</option>`);
  }
  for (const [value, label] of Object.entries(levelLabels)) {
    options.push(`<option value="${value}" ${selected === value ? "selected" : ""}>${label}</option>`);
  }
  return options.join("");
}

function renderProductLines() {
  const root = document.getElementById("productLines");
  const lines = state.overview.product_lines || [];
  if (!lines.length) {
    root.innerHTML = '<p class="empty">尚未从产品输入表同步到产品线。</p>';
    return;
  }
  root.innerHTML = lines
    .map(
      (line) => `
      <article class="product-line">
        <div class="product-line-header">
          <div>
            <h3>${escapeHtml(line.name)}</h3>
            <small>${line.product_count} 个产品 · ${line.target_count} 个有效目标 · ${line.open_action_count} 个待办行动</small>
          </div>
          <select data-scope-line="${line.id}" aria-label="${escapeHtml(line.name)}产品线档位">
            ${levelOptions(line.responsibility_level)}
          </select>
        </div>
        <table class="product-list">
          <thead><tr><th>ASIN</th><th>品牌</th><th>尺寸</th><th>单品覆盖档位</th></tr></thead>
          <tbody>
            ${line.products
              .map(
                (product) => `
                <tr>
                  <td>${escapeHtml(product.asin)}${product.is_self ? " · 我方" : ""}</td>
                  <td>${escapeHtml(product.brand || "-")}</td>
                  <td>${escapeHtml(product.size_normalized || "-")}</td>
                  <td>
                    <select data-scope-product="${line.id}" data-asin="${escapeHtml(product.asin)}">
                      ${levelOptions(product.responsibility_level, true)}
                    </select>
                  </td>
                </tr>`,
              )
              .join("")}
          </tbody>
        </table>
      </article>`,
    )
    .join("");

  root.querySelectorAll("[data-scope-line]").forEach((select) => {
    select.addEventListener("change", async () => {
      await saveScope(Number(select.dataset.scopeLine), null, select.value);
    });
  });
  root.querySelectorAll("[data-scope-product]").forEach((select) => {
    select.addEventListener("change", async () => {
      const line = lineById(select.dataset.scopeProduct);
      const inherited = line?.responsibility_level || "not_mine";
      await saveScope(
        Number(select.dataset.scopeProduct),
        select.dataset.asin,
        select.value || inherited,
      );
      if (!select.value) {
        await reload();
      }
    });
  });
}

async function saveScope(productLineId, asin, responsibilityLevel) {
  try {
    setPageStatus("正在保存档位");
    await api("/api/reporting/scopes", {
      method: "PUT",
      body: JSON.stringify({
        product_line_id: productLineId,
        asin,
        responsibility_level: responsibilityLevel,
      }),
    });
    setPageStatus("档位已保存");
    if (!asin) await reload();
  } catch (error) {
    setPageStatus("保存失败");
    showDialog("档位保存失败", error.message);
  }
}

function populateLineSelects() {
  const lines = state.overview.product_lines || [];
  const html = lines.map((line) => `<option value="${line.id}">${escapeHtml(line.name)}</option>`).join("");
  for (const id of ["targetLine", "actionLine"]) {
    const select = document.getElementById(id);
    const previous = select.value;
    select.innerHTML = html;
    if (lines.some((line) => String(line.id) === previous)) select.value = previous;
  }
  populateAsins("targetLine", "targetAsin");
  populateAsins("actionLine", "actionAsin");
}

function populateAsins(lineSelectId, asinSelectId) {
  const lineId = Number(document.getElementById(lineSelectId).value);
  const line = lineById(lineId);
  const select = document.getElementById(asinSelectId);
  const previous = select.value;
  select.innerHTML = '<option value="">整条产品线</option>' +
    (line?.products || [])
      .map((product) => `<option value="${escapeHtml(product.asin)}">${escapeHtml(product.asin)} · ${escapeHtml(product.brand || "未命名")}</option>`)
      .join("");
  if ([...select.options].some((option) => option.value === previous)) select.value = previous;
}

function renderTargets() {
  const root = document.getElementById("targetList");
  if (!state.targets.length) {
    root.innerHTML = '<p class="empty">尚未设置目标。</p>';
    return;
  }
  root.innerHTML = state.targets
    .slice(0, 20)
    .map(
      (target) => `
      <article class="record">
        <h4>${escapeHtml(target.product_line_name)} · ${escapeHtml(target.metric_code)}</h4>
        <p>${escapeHtml(target.asin || "整条产品线")}：${target.target_value} ${escapeHtml(target.unit || "")}</p>
        <div class="record-meta">
          <span class="tag">${escapeHtml(target.period_type)}</span>
          <span class="tag">${escapeHtml(target.period_start)} 至 ${escapeHtml(target.period_end)}</span>
          <span class="tag">版本 ${target.version}</span>
        </div>
        ${target.note ? `<p>${escapeHtml(target.note)}</p>` : ""}
      </article>`,
    )
    .join("");
}

function renderActions() {
  const root = document.getElementById("actionList");
  if (!state.actions.length) {
    root.innerHTML = '<p class="empty">尚未记录经营行动。</p>';
    return;
  }
  root.innerHTML = state.actions
    .slice(0, 30)
    .map(
      (action) => `
      <article class="record">
        <h4>${escapeHtml(action.title)}</h4>
        <p>${escapeHtml(action.product_line_name)} · ${escapeHtml(action.asin || "整条产品线")}</p>
        <p>${escapeHtml(action.content)}</p>
        ${action.reason ? `<p><strong>原因：</strong>${escapeHtml(action.reason)}</p>` : ""}
        ${action.expected_result ? `<p><strong>预期：</strong>${escapeHtml(action.expected_result)}</p>` : ""}
        ${action.actual_result ? `<p><strong>结果：</strong>${escapeHtml(action.actual_result)}</p>` : ""}
        <div class="record-meta">
          <span class="tag">${escapeHtml(action.action_date)}</span>
          <span class="tag">${escapeHtml(action.action_type)}</span>
          <span class="tag">${statusLabels[action.status] || escapeHtml(action.status)}</span>
          ${action.review_date ? `<span class="tag">复盘 ${escapeHtml(action.review_date)}</span>` : ""}
        </div>
        ${action.status === "planned" ? `<button type="button" data-action-start="${action.id}">开始执行</button>` : ""}
        ${action.status === "in_progress" ? `<button type="button" data-action-complete="${action.id}">标记完成</button>` : ""}
      </article>`,
    )
    .join("");

  root.querySelectorAll("[data-action-start]").forEach((button) => {
    button.addEventListener("click", () => patchAction(button.dataset.actionStart, { status: "in_progress" }));
  });
  root.querySelectorAll("[data-action-complete]").forEach((button) => {
    button.addEventListener("click", async () => {
      const actualResult = window.prompt("填写实际结果（可留空）：") || null;
      await patchAction(button.dataset.actionComplete, { status: "completed", actual_result: actualResult });
    });
  });
}

async function patchAction(id, payload) {
  try {
    await api(`/api/reporting/actions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    await reloadRecords();
    setPageStatus("行动状态已更新");
  } catch (error) {
    showDialog("行动更新失败", error.message);
  }
}

async function reloadRecords() {
  [state.targets, state.actions] = await Promise.all([
    api("/api/reporting/targets"),
    api("/api/reporting/actions"),
  ]);
  renderTargets();
  renderActions();
}

async function reload() {
  setPageStatus("正在加载");
  state.overview = await api("/api/reporting/overview");
  renderSummary();
  renderAvailability();
  renderProductLines();
  populateLineSelects();
  await reloadRecords();
  setPageStatus("已就绪");
}

function setDefaultDates() {
  const today = new Date();
  const yyyy = today.getFullYear();
  const mm = String(today.getMonth() + 1).padStart(2, "0");
  const dd = String(today.getDate()).padStart(2, "0");
  const lastDay = new Date(yyyy, today.getMonth() + 1, 0).getDate();
  document.getElementById("periodStart").value = `${yyyy}-${mm}-01`;
  document.getElementById("periodEnd").value = `${yyyy}-${mm}-${String(lastDay).padStart(2, "0")}`;
  document.getElementById("actionDate").value = `${yyyy}-${mm}-${dd}`;
}

document.getElementById("targetLine").addEventListener("change", () => populateAsins("targetLine", "targetAsin"));
document.getElementById("actionLine").addEventListener("change", () => populateAsins("actionLine", "actionAsin"));

document.getElementById("importAudit").addEventListener("click", async () => {
  try {
    setPageStatus("正在导入领星盘点");
    const result = await api("/api/reporting/import-latest-audit", { method: "POST" });
    showDialog("领星盘点导入结果", result);
    await reload();
  } catch (error) {
    setPageStatus("导入失败");
    showDialog("导入失败", error.message);
  }
});

document.getElementById("targetForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const payload = {
      product_line_id: Number(document.getElementById("targetLine").value),
      asin: document.getElementById("targetAsin").value || null,
      period_type: document.getElementById("periodType").value,
      period_start: document.getElementById("periodStart").value,
      period_end: document.getElementById("periodEnd").value,
      metric_code: document.getElementById("metricCode").value,
      target_value: Number(document.getElementById("targetValue").value),
      unit: document.getElementById("targetUnit").value || null,
      note: document.getElementById("targetNote").value || null,
    };
    await api("/api/reporting/targets", { method: "POST", body: JSON.stringify(payload) });
    event.target.reset();
    setDefaultDates();
    populateLineSelects();
    await reload();
    setPageStatus("目标已保存");
  } catch (error) {
    showDialog("目标保存失败", error.message);
  }
});

document.getElementById("actionForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const payload = {
      product_line_id: Number(document.getElementById("actionLine").value),
      asin: document.getElementById("actionAsin").value || null,
      action_date: document.getElementById("actionDate").value,
      action_type: document.getElementById("actionType").value,
      title: document.getElementById("actionTitle").value,
      content: document.getElementById("actionContent").value,
      reason: document.getElementById("actionReason").value || null,
      expected_result: document.getElementById("actionExpected").value || null,
      review_date: document.getElementById("reviewDate").value || null,
      status: document.getElementById("actionStatus").value,
      source: "user",
      confirmed: true,
    };
    await api("/api/reporting/actions", { method: "POST", body: JSON.stringify(payload) });
    event.target.reset();
    setDefaultDates();
    populateLineSelects();
    await reload();
    setPageStatus("行动已保存");
  } catch (error) {
    showDialog("行动保存失败", error.message);
  }
});

setDefaultDates();
reload().catch((error) => {
  setPageStatus("加载失败");
  showDialog("页面加载失败", error.message);
});

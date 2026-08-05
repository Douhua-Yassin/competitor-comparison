const state = { data: null, syncTimer: null };

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
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fillFilters() {
  const country = document.getElementById("countryFilter");
  const previousCountry = country.value;
  country.innerHTML = '<option value="">全部国家</option>' +
    state.data.countries.map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join("");
  if ([...country.options].some((item) => item.value === previousCountry)) country.value = previousCountry;

  const store = document.getElementById("storeFilter");
  const previousStore = store.value;
  store.innerHTML = '<option value="">全部店铺</option>' +
    state.data.stores.map((item) => `<option value="${item.sid}">${escapeHtml(item.country)} · ${escapeHtml(item.store_name)}</option>`).join("");
  if ([...store.options].some((item) => item.value === previousStore)) store.value = previousStore;
}

function filteredProducts() {
  const country = document.getElementById("countryFilter").value;
  const store = document.getElementById("storeFilter").value;
  const search = document.getElementById("productSearch").value.trim().toLowerCase();
  return state.data.products.filter((item) => {
    if (country && item.display_country !== country) return false;
    if (store && String(item.sid) !== store) return false;
    if (!search) return true;
    const haystack = [item.product_name, item.title, item.asin, item.msku, item.lsku, item.brand]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(search);
  });
}

function productRow(item) {
  const level = item.responsibility_level;
  const image = item.thumbnail_url
    ? `<img src="${escapeHtml(item.thumbnail_url)}" alt="" loading="lazy">`
    : '<div style="width:54px;height:54px;background:#f3f5f8;border-radius:8px"></div>';
  return `
    <tr data-product-id="${item.id}">
      <td>
        <div class="product-identity">
          ${image}
          <div>
            <strong>${escapeHtml(item.product_name || item.title || item.asin || item.msku)}</strong>
            <small>ASIN ${escapeHtml(item.asin || "-")} · MSKU ${escapeHtml(item.msku)}</small>
            <small>LSKU ${escapeHtml(item.lsku || "-")}</small>
          </div>
        </div>
      </td>
      <td>${escapeHtml(item.brand || "-")}</td>
      <td>${escapeHtml(item.currency_code || "-")}</td>
      <td>
        <input class="product-line-input" data-product-line="${item.id}" value="${escapeHtml(item.product_line || "")}" placeholder="例如：足球门">
      </td>
      <td>
        <div class="scope-buttons">
          <button type="button" class="scope-button key ${level === "key" ? "active" : ""}" data-scope="key" data-id="${item.id}">重点</button>
          <button type="button" class="scope-button normal ${level === "normal" ? "active" : ""}" data-scope="normal" data-id="${item.id}">普通</button>
        </div>
      </td>
    </tr>`;
}

function renderProducts() {
  const root = document.getElementById("settingsProducts");
  const rows = filteredProducts();
  if (!rows.length) {
    root.innerHTML = '<div class="empty-state">没有符合当前筛选条件的产品。</div>';
    return;
  }
  const countries = new Map();
  for (const item of rows) {
    if (!countries.has(item.display_country)) countries.set(item.display_country, new Map());
    const stores = countries.get(item.display_country);
    if (!stores.has(item.sid)) stores.set(item.sid, { name: item.store_name, products: [] });
    stores.get(item.sid).products.push(item);
  }
  root.innerHTML = [...countries.entries()].map(([country, stores]) => `
    <section class="country-group">
      <h2 class="country-heading">${escapeHtml(country)}</h2>
      ${[...stores.entries()].map(([sid, store]) => `
        <section class="store-group">
          <h3 class="store-heading">${escapeHtml(store.name)} · SID ${sid}</h3>
          <table class="product-table">
            <thead><tr><th>产品</th><th>品牌</th><th>币种</th><th>产品线</th><th>负责档位</th></tr></thead>
            <tbody>${store.products.map(productRow).join("")}</tbody>
          </table>
        </section>`).join("")}
    </section>`).join("");
  attachHandlers();
}

function attachHandlers() {
  document.querySelectorAll(".scope-button").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = Number(button.dataset.id);
      const current = state.data.products.find((item) => item.id === id);
      if (!current) return;
      const requested = button.dataset.scope;
      const nextLevel = current.responsibility_level === requested ? "not_mine" : requested;
      const input = document.querySelector(`[data-product-line="${id}"]`);
      await saveScope(current, nextLevel, input?.value || "", button);
    });
  });
  document.querySelectorAll(".product-line-input").forEach((input) => {
    input.addEventListener("change", async () => {
      const id = Number(input.dataset.productLine);
      const current = state.data.products.find((item) => item.id === id);
      if (!current || current.responsibility_level === "not_mine") return;
      await saveScope(current, current.responsibility_level, input.value, input);
    });
  });
}

async function saveScope(current, responsibilityLevel, productLine, control) {
  control.classList.add("saving");
  try {
    const updated = await api("/api/reporting/products/scope", {
      method: "PUT",
      body: JSON.stringify({
        listing_id: current.id,
        responsibility_level: responsibilityLevel,
        product_line: productLine,
      }),
    });
    Object.assign(current, updated);
    renderProducts();
    document.getElementById("settingsStatus").textContent =
      responsibilityLevel === "not_mine"
        ? "已取消负责；后续不再同步该产品经营数据"
        : `已保存为${responsibilityLevel === "key" ? "重点" : "普通"}产品`;
  } catch (error) {
    showDialog("保存失败", error.message);
  } finally {
    control.classList.remove("saving");
  }
}

async function loadProducts() {
  try {
    state.data = await api("/api/reporting/products");
    fillFilters();
    renderProducts();
    const selected = state.data.products.filter((item) => item.responsibility_level !== "not_mine").length;
    document.getElementById("settingsStatus").textContent =
      `共 ${state.data.products.length} 个 Listing，已负责 ${selected} 个`;
  } catch (error) {
    document.getElementById("settingsProducts").innerHTML =
      `<div class="empty-state">读取失败：${escapeHtml(error.message)}</div>`;
  }
}

async function pollSyncStatus() {
  try {
    const status = await api("/api/reporting/sync-status");
    document.getElementById("settingsStatus").textContent = status.message || "";
    document.getElementById("syncButton").disabled = Boolean(status.running);
    if (status.running) {
      state.syncTimer = setTimeout(pollSyncStatus, 1500);
    } else {
      clearTimeout(state.syncTimer);
      await loadProducts();
    }
  } catch (error) {
    document.getElementById("settingsStatus").textContent = `状态读取失败：${error.message}`;
  }
}

async function startSync() {
  document.getElementById("syncButton").disabled = true;
  try {
    await api("/api/reporting/sync", { method: "POST", body: "{}" });
    await pollSyncStatus();
  } catch (error) {
    document.getElementById("syncButton").disabled = false;
    showDialog("同步失败", error.message);
  }
}

function showDialog(title, body) {
  document.getElementById("dialogTitle").textContent = title;
  document.getElementById("dialogBody").textContent = body;
  document.getElementById("messageDialog").showModal();
}

for (const id of ["countryFilter", "storeFilter", "productSearch"]) {
  document.getElementById(id).addEventListener(id === "productSearch" ? "input" : "change", renderProducts);
}
document.getElementById("syncButton").addEventListener("click", startSync);

loadProducts();
pollSyncStatus();

(() => {
  const statusNode = document.getElementById("targetImportStatus");
  const importButton = document.getElementById("targetImportButton");
  if (!statusNode || !importButton) return;

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  async function request(url, options = {}) {
    const response = await fetch(url, {
      cache: "no-store",
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

  async function loadStatus() {
    try {
      const data = await request("/api/reporting/targets/status");
      const latest = data.last_import;
      statusNode.innerHTML = `
        <strong>${data.source_exists ? "已找到目标表" : "尚未找到目标表"}</strong>
        <span>${escapeHtml(data.source_path)}</span>
        <span>当前有效目标：${Number(data.active_target_count || 0)} 条</span>
        <span>${latest ? `最近导入：${escapeHtml(latest.imported_at)} · ${escapeHtml(latest.status)} · ${Number(latest.row_count || 0)} 条` : "尚未导入"}</span>`;
    } catch (error) {
      statusNode.textContent = `目标状态读取失败：${error.message}`;
    }
  }

  importButton.addEventListener("click", async () => {
    importButton.disabled = true;
    statusNode.textContent = "正在读取根目录目标表.xlsx……";
    try {
      const result = await request("/api/reporting/targets/import", {
        method: "POST",
        body: "{}",
      });
      statusNode.textContent = result.duplicate
        ? `目标表内容未变化，沿用已导入的 ${result.row_count} 条目标。`
        : `目标导入完成：${result.row_count} 条。`;
      await loadStatus();
    } catch (error) {
      statusNode.textContent = `目标导入失败：${error.message}`;
    } finally {
      importButton.disabled = false;
    }
  });

  loadStatus();
})();

(() => {
  function visibleError(message) {
    const status = document.getElementById("syncStatus");
    const dashboard = document.getElementById("dashboard");
    if (status) status.textContent = `页面运行异常：${message}`;
    if (dashboard) {
      dashboard.innerHTML = `<div class="empty-state">页面没有完成加载。请关闭当前窗口并重新双击“启动报告程序.bat”。<br><small>${String(message || "未知错误")}</small></div>`;
    }
  }

  window.addEventListener("error", (event) => {
    visibleError(event.message || "前端脚本错误");
  });

  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    visibleError(reason?.message || String(reason || "未处理的请求错误"));
  });

  window.setTimeout(async () => {
    const status = document.getElementById("syncStatus");
    if (!status || !status.textContent.includes("正在加载")) return;

    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch("/api/reporting/diagnostics", {
        cache: "no-store",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      const data = await response.json();
      status.textContent = data.database?.readable
        ? "本机服务正常，但主页面脚本没有完成加载。请重新启动报告程序。"
        : `报告数据库不可用：${data.database?.error || "未知错误"}`;
    } catch (error) {
      visibleError(error.name === "AbortError" ? "本机8790接口响应超时" : error.message);
    } finally {
      window.clearTimeout(timer);
    }
  }, 5000);
})();

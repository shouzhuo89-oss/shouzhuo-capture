const stageEl = document.getElementById("stage");
const errorEl = document.getElementById("error");

function render(status) {
  stageEl.textContent = status?.stage || "未知";
  stageEl.className = `value ${status?.stage === "completed" ? "ok" : ""}`;
  errorEl.textContent = status?.lastError || "无";
  errorEl.className = `value ${status?.lastError ? "bad" : ""}`;
}

function refresh() {
  chrome.runtime.sendMessage({ action: "status" }, (status) => {
    if (chrome.runtime.lastError) {
      render({ stage: "扩展后台不可用", lastError: chrome.runtime.lastError.message });
      return;
    }
    render(status);
  });
}

refresh();
setInterval(refresh, 2000);

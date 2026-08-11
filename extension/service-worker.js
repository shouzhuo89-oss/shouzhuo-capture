// 守拙 Capture 桥 — standalone service worker (HTTP handoff)
// Detects a capture task from the yuanbao page URL hash, resolves the
// share link via the Yuanbao API, extracts the video source, and POSTs
// it to the local Python handoff server. No chrome.downloads dependency.

const EXTENSION_VERSION = "2.0.0";
const PLAYABLE_PAGE_TIMEOUT_MS = 90000;
const INSPECT_PLAYABLE_TIMEOUT_MS = 120000;
const HANDOFF_TIMEOUT_MS = 15000;
const YUANBAO_PREFIX = "https://yuanbao.tencent.com/";

let busy = false;
let publicStatus = {
  extensionVersion: EXTENSION_VERSION,
  busy: false,
  stage: "idle",
  lastError: "",
  updatedAt: new Date().toISOString(),
};

function setStatus(patch) {
  publicStatus = { ...publicStatus, ...patch, updatedAt: new Date().toISOString() };
  chrome.storage.local.set({ bridgeStatus: publicStatus });
}

function sanitizedError(error) {
  return String(error?.message || error || "未知错误")
    .replace(/https?:\/\/\S+/g, "[已隐藏地址]")
    .slice(0, 500);
}

function parseHashJob(tabUrl) {
  try {
    const url = new URL(tabUrl);
    const hash = url.hash.replace(/^#/, "");
    const params = new URLSearchParams(hash);
    const port = params.get("cap_port");
    const captureUrl = params.get("cap_url");
    if (port && captureUrl) {
      return { port: parseInt(port, 10), captureUrl };
    }
  } catch {}
  return null;
}

function waitForTab(tabId, timeoutMs = PLAYABLE_PAGE_TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const check = async () => {
      try {
        const tab = await chrome.tabs.get(tabId);
        if (tab.status === "complete") { resolve(tab); return; }
      } catch (error) { reject(error); return; }
      if (Date.now() - started > timeoutMs) { reject(new Error("页面加载超时")); return; }
      setTimeout(check, 1000);
    };
    check();
  });
}

function officialPlayableUrl(value) {
  const url = new URL(value);
  const host = url.hostname.toLowerCase();
  const allowed =
    host === "weixin.qq.com" ||
    host === "channels.weixin.qq.com" ||
    host.endsWith(".weixin.qq.com") ||
    host.endsWith(".qq.com");
  if (url.protocol !== "https:" || !allowed) throw new Error("元宝返回了非腾讯官方播放页");
  return url.href;
}

function officialMediaUrl(value) {
  const url = new URL(value);
  const host = url.hostname.toLowerCase();
  const allowed =
    host.endsWith(".qq.com") ||
    host.endsWith(".qpic.cn") ||
    host.endsWith(".gtimg.com") ||
    host.endsWith(".weixin.qq.com");
  if (!["https:", "blob:"].includes(url.protocol) || !allowed) {
    throw new Error("视频媒体地址不属于允许的腾讯域名");
  }
  return url.href;
}

async function parseWithYuanbao(tabId, shareUrl) {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    func: async (url) => {
      const response = await fetch("/api/weixin/get_parse_result", {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ type: "video_channel_url", url, scene: 1 }),
      });
      if (response.status === 401 || response.status === 403) {
        return { ok: false, stage: "auth", error: "腾讯元宝登录已失效" };
      }
      if (!response.ok) {
        return { ok: false, stage: "parse", error: `元宝解析接口返回 HTTP ${response.status}` };
      }
      const value = await response.json();
      const playableUrl = value?.data?.playable_url || "";
      if (!playableUrl) {
        return { ok: false, stage: "parse", error: "元宝没有返回视频号官方播放页" };
      }
      return { ok: true, playableUrl };
    },
    args: [shareUrl],
  });
  if (!result?.result?.ok) {
    const error = new Error(result?.result?.error || "元宝解析失败");
    error.stage = result?.result?.stage || "parse";
    throw error;
  }
  return officialPlayableUrl(result.result.playableUrl);
}

async function inspectPlayableTab(tabId) {
  const started = Date.now();
  while (Date.now() - started < INSPECT_PLAYABLE_TIMEOUT_MS) {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      func: () => {
        const video = document.querySelector("video");
        const source = video?.currentSrc || video?.src || video?.querySelector("source")?.src || "";
        if (!video || !source) return { ok: false };
        const meta = (sel) =>
          document.querySelector(sel)?.getAttribute("content") || "";
        return {
          ok: true,
          source,
          title: meta('meta[property="og:title"]') || document.title || "视频号媒体",
          author: meta('meta[name="author"]') || meta('meta[property="article:author"]') || "",
          description: meta('meta[property="og:description"]') || meta('meta[name="description"]') || "",
        };
      },
    });
    if (result?.result?.ok) return result.result;
    await new Promise((r) => setTimeout(r, 1500));
  }
  throw new Error("官方播放页没有加载出可下载视频");
}

async function handoffToPython(port, payload) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), HANDOFF_TIMEOUT_MS);
  try {
    const response = await fetch(`http://127.0.0.1:${port}/handoff`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!response.ok) throw new Error(`Handoff HTTP ${response.status}`);
    const data = await response.json();
    if (!data?.ok) throw new Error(data?.error || "Handoff 返回失败");
  } catch (error) {
    clearTimeout(timer);
    throw error;
  }
}

async function handleCapture(tabId, job) {
  busy = true;
  setStatus({ busy: true, stage: "parse", lastError: "" });
  try {
    let playableUrl;
    try { playableUrl = await parseWithYuanbao(tabId, job.captureUrl); } catch (e) { e.stage = e.stage || "parse"; throw e; }

    setStatus({ stage: "playable_page" });
    let media, source;
    try {
      const playableTab = await chrome.tabs.update(tabId, { url: playableUrl, active: false });
      await waitForTab(playableTab.id);
      media = await inspectPlayableTab(playableTab.id);
      source = officialMediaUrl(media.source);
    } catch (e) { e.stage = e.stage || "playable_page"; throw e; }

    setStatus({ stage: "handoff" });
    const shortId = job.captureUrl.split("/sph/")[1] || "video";
    try {
      await handoffToPython(job.port, { url: source, title: media.title, author: media.author, short_id: shortId });
    } catch (e) { e.stage = e.stage || "handoff"; throw e; }

    setStatus({ busy: false, stage: "completed", lastError: "" });
  } catch (error) {
    const message = sanitizedError(error);
    const stage = error?.stage || "unknown";
    setStatus({ busy: false, stage: "failed", lastError: `[${stage}] ${message}` });
  } finally {
    busy = false;
  }
}

// Yuanbao's SPA strips the #cap_port/... hash during page load, so the
// capture task is only observable while the tab is still "loading". We
// capture it there and fire handleCapture once the tab reaches "complete".
let pendingJob = null;
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (busy) return;
  const url = String(tab.url || "");
  if (!url.startsWith(YUANBAO_PREFIX)) return;

  const job = parseHashJob(url);
  if (job) pendingJob = job;

  if (changeInfo.status !== "complete" || !pendingJob) return;
  const captured = pendingJob;
  pendingJob = null;

  try {
    await chrome.tabs.update(tabId, { url: YUANBAO_PREFIX });
    await waitForTab(tabId);
  } catch { return; }

  handleCapture(tabId, captured).catch(() => {});
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.action === "status") { sendResponse(publicStatus); return true; }
  return false;
});

chrome.runtime.onInstalled.addListener(() => { setStatus({ stage: "idle" }); });
chrome.runtime.onStartup.addListener(() => { setStatus({ stage: "idle" }); });

if (typeof module !== "undefined") module.exports = {};

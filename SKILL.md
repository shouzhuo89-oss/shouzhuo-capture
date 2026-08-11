---
name: shouzhuo-capture
description: 守拙 Capture — 用 Chrome for Testing 加载内置扩展，在已登录腾讯元宝的会话中自动解析视频号分享链接并下载视频到本地。Use when the user asks to download WeChat Channels (视频号) videos.
---

# 守拙 Capture

## What It Does

守拙 Capture 通过 Chrome for Testing 加载内置扩展，在已登录的腾讯元宝会话中自动解析视频号分享链接并下载视频到本地。

核心流程（HTTP handoff 架构）：

1. Python 脚本启动一个本地 HTTP 服务器
2. Python 脚本以 headless 模式启动 Chrome for Testing，加载内置扩展，打开 `yuanbao.tencent.com#cap_port=<port>&cap_url=<sph链接>`
3. 扩展检测到页面 hash 里的任务，在元宝页面同源调用 `/api/weixin/get_parse_result` 解析出官方播放页
4. 扩展导航到播放页，从 `<video>` 标签提取媒体源 URL
5. 扩展把媒体源 URL POST 回 Python 的 HTTP 服务器
6. Python 用标准 HTTP 客户端直接下载视频到指定文件夹
7. Python 验证文件完整性，关闭 Chrome

这个架构不依赖 `chrome.downloads` API，下载完全由 Python 完成，跨平台（macOS/Windows/Linux）可靠。

## Workflow

1. `setup` — 安装 Chrome for Testing，创建本地状态目录
2. `login` — 打开腾讯元宝页面，扫码登录（独立 profile，不影响日常浏览器）
3. `capture <url>` — 传入视频号分享链接，headless 自动解析并下载
4. `doctor` — 诊断环境问题
5. `self-test` — 编辑脚本或扩展后运行回归测试

Use `references/architecture.md` for component boundaries, `references/validation-gates.md` for acceptance criteria, `references/troubleshooting.md` for failure handling, and `references/github-release.md` when preparing public GitHub copy.

## Helper Script

```bash
python3 scripts/shouzhuo_capture.py setup
python3 scripts/shouzhuo_capture.py login
python3 scripts/shouzhuo_capture.py capture "https://weixin.qq.com/sph/XXXXXXXX"
python3 scripts/shouzhuo_capture.py doctor
python3 scripts/shouzhuo_capture.py self-test
```

Run these commands from the skill directory, or resolve `scripts/shouzhuo_capture.py` relative to this `SKILL.md`.

The script default state root is `~/.shouzhuo-capture`. Override it with `--root <path>` or `SHOUZHUO_CAPTURE_HOME`.

`setup` downloads Chrome for Testing from Google's official JSON endpoint when no configured executable exists. Use `--no-install` for a local dry run.

`capture` defaults to **headless mode** (no visible browser window). The extension resolves the link via Yuanbao, extracts the video source URL, and hands it back to Python over a local HTTP socket. Python downloads the file directly with `urllib`. Use `--no-headless` to show the browser window for debugging.

## Operating Rules

- Default login target is `https://yuanbao.tencent.com/` (Tencent Yuanbao). The user scans the WeChat QR code to log in once.
- The extension only resolves links from `weixin.qq.com` and only accepts media from official Tencent domains (`*.qq.com`, `*.qpic.cn`, `*.gtimg.com`).
- Downloads are performed by Python's HTTP client, not Chrome's download API — this ensures cross-platform reliability in headless mode.
- Never close all Chrome processes by name. Only stop a process that this workflow started and whose PID is known.
- When re-running `setup`, preserve the existing configured download directory unless the user passes a new `--download-dir`.

## Public Positioning

> 守拙 Capture 用 Chrome for Testing 加载内置扩展，在已登录腾讯元宝的会话中自动解析视频号分享链接并下载视频到本地。headless 模式，全程无窗口，跨平台。

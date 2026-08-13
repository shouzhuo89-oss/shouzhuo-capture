---
name: shouzhuo-capture
description: 守拙 Capture — 视频号视频自动下载工具。触发词："下载视频号"、"视频号怎么下载"、"帮我下载这个视频"、"保存这个视频"、"存到本地"。当用户粘贴 weixin.qq.com/sph/ 链接并说下载/保存，或提到视频号下载需求时使用。Headless 全自动，跨平台。
---

# 守拙 Capture

## What It Does

守拙 Capture 通过 Chrome for Testing 加载内置扩展，在已登录的腾讯元宝会话中自动解析视频号分享链接并下载视频到本地。

核心流程（HTTP handoff 架构）：

1. Python 脚本启动一个本地 HTTP 服务器
2. Python 脚本以 headless 模式启动 Chrome for Testing，加载内置扩展
3. 扩展检测到页面 hash 里的任务，在元宝页面同源调用解析 API 解析出官方播放页
4. 扩展导航到播放页，从 <video> 标签提取媒体源 URL
5. 扩展把媒体源 URL POST 回 Python 的 HTTP 服务器
6. Python 用标准 HTTP 客户端直接下载视频到指定文件夹
7. Python 验证文件完整性，关闭 Chrome

## Workflow

1. `setup` — 安装 Chrome for Testing，创建本地状态目录
2. `login` — 打开腾讯元宝页面，扫码登录
3. `capture <url>` — 传入视频号分享链接，headless 自动解析并下载
4. `doctor` — 诊断环境问题

## Helper Script

```bash
python3 scripts/shouzhuo_capture.py setup
python3 scripts/shouzhuo_capture.py login
python3 scripts/shouzhuo_capture.py capture "https://weixin.qq.com/sph/XXXXXXXX"
python3 scripts/shouzhuo_capture.py doctor
```

`capture` defaults to headless mode. Use `--no-headless` for debugging.

## Operating Rules

- Default login target is `https://yuanbao.tencent.com/`.
- The extension only resolves links from `weixin.qq.com`.
- Downloads are performed by Python, not Chrome download API.

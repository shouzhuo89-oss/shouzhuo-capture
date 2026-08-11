# 守拙 Capture

守拙 Capture 是一个视频号视频下载工具：用 Chrome for Testing 加载内置扩展，在已登录腾讯元宝的浏览器会话中，自动解析视频号分享链接并下载视频到本地文件夹。

## 工作原理

```
视频号分享链接 (weixin.qq.com/sph/XXX)
  ↓  Python 启动 Chrome for Testing（headless，无窗口）
扩展在腾讯元宝页面同源调用解析 API
  ↓  得到官方播放页 URL
从播放页提取 <video> 媒体源 URL
  ↓  扩展把 URL 回传给 Python（本地 HTTP）
Python 直接下载视频到本地文件夹
  ↓  ffprobe 校验
完成
```

下载由 Python 完成，不依赖 Chrome 下载 API，跨平台（macOS/Windows/Linux）可靠。

## Features

- 一条命令自动下载视频号视频
- Headless 模式默认开启，全程无浏览器窗口
- Chrome 扩展自动解析（通过腾讯元宝官方 API）
- 独立浏览器 profile，不影响日常 Chrome
- 首次扫码登录，后续自动复用
- 下载文件自动校验（ffprobe）
- 跨平台：macOS、Windows、Linux
- 自动安装 Chrome for Testing

## Quick Start

```bash
cd shouzhuo-capture

# 1. 安装 Chrome for Testing 并初始化
python3 scripts/shouzhuo_capture.py setup

# 2. 打开腾讯元宝，扫码登录（首次）
python3 scripts/shouzhuo_capture.py login

# 3. 下载视频（headless，无窗口）
python3 scripts/shouzhuo_capture.py capture "https://weixin.qq.com/sph/XXXXXXXX"

# 4. 检查环境
python3 scripts/shouzhuo_capture.py doctor
```

默认下载目录：`~/.shouzhuo-capture/downloads/`

自定义下载目录：
```bash
python3 scripts/shouzhuo_capture.py setup --download-dir "$HOME/Movies/ShouzhuoCapture"
```

## Commands

```text
setup      安装 Chrome for Testing，创建本地状态
login      打开腾讯元宝页面扫码登录
capture    传入视频号链接，自动解析并下载（默认 headless）
verify     校验本地媒体文件
doctor     诊断环境问题
self-test  离线回归测试
```

## Requirements

- Python 3.8+
- 网络（首次安装 Chrome for Testing 时需要）
- ffmpeg/ffprobe（可选，用于媒体文件校验）

## License

MIT License — Copyright (c) 2026 守拙

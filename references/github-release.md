# GitHub Release Copy

## Repository Name
```text
shouzhuo-capture
```

## One-Line Description
```text
守拙 Capture: 自动下载视频号视频到本地。Headless 模式，全程无窗口，跨平台。
```

## Short Intro

守拙 Capture 是一个视频号视频下载工具。它用 Chrome for Testing（headless 无窗口模式）加载一个内置 Chrome 扩展，在已登录腾讯元宝的会话中自动解析视频号分享链接，提取视频源地址，再由 Python 直接下载到本地文件夹。

## Quick Start
```bash
git clone https://github.com/shouzhuo89-oss/shouzhuo-capture.git
cd shouzhuo-capture
python3 scripts/shouzhuo_capture.py setup
python3 scripts/shouzhuo_capture.py login
python3 scripts/shouzhuo_capture.py capture "https://weixin.qq.com/sph/XXXXXXXX"
```

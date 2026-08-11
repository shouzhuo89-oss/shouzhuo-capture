# Architecture

## Components

- `Chrome for Testing`: dedicated browser binary, runs headless by default.
- `extension/`: Chrome extension that detects capture tasks, calls the Yuanbao parse API, extracts the `<video>` media source URL, and POSTs it to the local Python handoff server.
- `scripts/shouzhuo_capture.py`: Python CLI that installs Chrome, manages browser lifecycle, runs the handoff HTTP server, and downloads the video directly with `urllib`.

## How A Capture Works (HTTP Handoff)

```text
python3 scripts/shouzhuo_capture.py capture "https://weixin.qq.com/sph/XXX"
  |
  +-- Python starts a local HTTP server on 127.0.0.1:<random port>
  |
  +-- Python launches Chrome (headless) with --load-extension=extension/
  |   URL = yuanbao.tencent.com#cap_port=<port>&cap_url=<sph link>
  |
  +-- Extension service-worker.js:
        +-- detects yuanbao.tencent.com page with capture task in hash
        +-- clears hash to prevent re-trigger
        +-- calls POST /api/weixin/get_parse_result (same-origin, has Yuanbao cookies)
        +-- gets playable_url from response
        +-- navigates the tab to playable_url
        +-- injects script to read <video> currentSrc
        +-- validates media domain (*.qq.com, *.qpic.cn, *.gtimg.com)
        +-- POSTs {url, title, short_id} to http://127.0.0.1:<port>/handoff
              |
              +-- Python receives the POST, downloads the video with urllib,
                  validates with ffprobe, closes Chrome.
```

## Why Not chrome.downloads?

Chrome's `chrome.downloads.download()` API is unreliable in `--headless=new` mode, especially on Windows. The HTTP handoff architecture bypasses Chrome's download pipeline entirely.

## State Root

```text
~/.shouzhuo-capture/
+-- chrome/
+-- profile/          <- Yuanbao login state persists here
+-- downloads/        <- Videos saved here
+-- logs/
+-- config.json
```

## Security Boundary

The extension uses Yuanbao cookies only within the `yuanbao.tencent.com` same-origin context. Cookies are never exported to Python or any external process. The video source URL handed off to Python is a public CDN link.

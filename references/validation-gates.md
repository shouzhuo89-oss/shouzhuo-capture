# Validation Gates

## Setup Gate

Pass only when:
- Chrome for Testing executable exists and can be launched.
- Extension directory with `manifest.json` and `service-worker.js` exists.
- Profile directory exists and is writable.
- Download directory exists and is writable.
- `ffprobe` is found or the result says validation will be weaker without it.

## Login Gate

Pass only when:
- Chrome for Testing opens with the isolated profile.
- The user navigates to `yuanbao.tencent.com` and completes QR login.
- The Yuanbao home page shows a logged-in state.

## Capture Gate

Pass only when:
- Chrome launches headless with the extension loaded.
- The extension detects the capture task in the yuanbao page hash.
- The Yuanbao API returns a valid `playable_url`.
- The playable page loads and exposes a `<video>` media source.
- The extension POSTs the video source URL to the Python handoff server.
- Python downloads the file to the configured download directory.
- The file is non-empty and passes `ffprobe` when available.

## Failure Stages

- `auth`: Yuanbao login expired (HTTP 401/403).
- `parse`: Yuanbao API error or no `playable_url`.
- `playable_page`: Official page did not load a downloadable video.
- `handoff`: Extension failed to POST the video URL to Python.
- `download`: Python download failed or timed out.

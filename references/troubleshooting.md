# Troubleshooting

## Chrome for Testing Missing
```bash
python3 scripts/shouzhuo_capture.py setup
```

## Login Expired (auth stage)
```bash
python3 scripts/shouzhuo_capture.py login
```

## Parse Fails
- Verify the share link is a valid `weixin.qq.com/sph/*` URL.
- The video may have been deleted or made private.

## Handoff Fails
- No firewall is blocking localhost connections.
- The Python handoff server is running.

## Extension Not Loaded
Run `doctor` and check `extension_manifest_exists` and `extension_service_worker_exists`.

## Windows-Specific Notes
- Headless mode (`--headless=new`) is the default and works reliably with the HTTP handoff architecture.
- If headless fails on Windows, try `--no-headless` to debug.

## Regressions After Editing
```bash
python3 scripts/shouzhuo_capture.py self-test
python3 scripts/shouzhuo_capture.py doctor
```

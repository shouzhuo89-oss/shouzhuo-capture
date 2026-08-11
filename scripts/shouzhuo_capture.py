#!/usr/bin/env python3
"""Local helper for Shouzhuo Capture workflows.

Launches Chrome for Testing with the bundled extension. The extension
resolves the share link via Tencent Yuanbao and hands the video source
URL back to this script over a local HTTP socket. The script downloads
the video directly with urllib — no chrome.downloads dependency.
"""

from __future__ import annotations

import argparse
import contextlib
import http.server
import io
import json
import os
import platform
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


CFT_URL = "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"
TEMP_SUFFIXES = (".crdownload", ".tmp", ".download", ".part")
DEFAULT_YUANBAO_URL = "https://yuanbao.tencent.com/"
SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_EXTENSION_DIR = SKILL_DIR / "extension"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def default_root() -> Path:
    root = os.environ.get("SHOUZHUO_CAPTURE_HOME") or os.environ.get("WECHAT_CHANNELS_CAPTURE_HOME")
    return Path(root or "~/.shouzhuo-capture").expanduser()


def load_config(root: Path) -> dict[str, Any]:
    path = root / "config.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_config(root: Path, config: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Chrome for Testing install / discovery
# ---------------------------------------------------------------------------

def platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        return "mac-arm64" if machine in {"arm64", "aarch64"} else "mac-x64"
    if system == "linux":
        return "linux64"
    if system == "windows":
        return "win64"
    raise RuntimeError(f"Unsupported platform: {platform.system()} {platform.machine()}")


def executable_from_extract(root: Path, key: str) -> Path:
    chrome_root = root / "chrome"
    if key.startswith("mac-"):
        folder = "chrome-mac-arm64" if key == "mac-arm64" else "chrome-mac-x64"
        return chrome_root / folder / "Google Chrome for Testing.app" / "Contents" / "MacOS" / "Google Chrome for Testing"
    if key == "linux64":
        return chrome_root / "chrome-linux64" / "chrome"
    if key == "win64":
        return chrome_root / "chrome-win64" / "chrome.exe"
    raise RuntimeError(f"Unsupported Chrome for Testing platform: {key}")


def find_ffprobe(explicit: str | None = None) -> str | None:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.exists():
            raise RuntimeError(f"ffprobe path does not exist: {path}")
        return str(path)
    return shutil.which("ffprobe")


def find_download(downloads: list[dict[str, Any]], key: str) -> dict[str, Any]:
    for item in downloads:
        if item.get("platform") == key and item.get("url"):
            return item
    raise RuntimeError(f"No Chrome for Testing download found for {key}")


def install_chrome(root: Path, channel: str) -> tuple[Path, str]:
    key = platform_key()
    with urllib.request.urlopen(CFT_URL, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    channel_data = payload["channels"][channel]
    download = find_download(channel_data["downloads"]["chrome"], key)
    version = channel_data["version"]
    zip_path = root / "chrome" / f"chrome-{key}-{version}.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(download["url"], zip_path)
    safe_extract(zip_path, root / "chrome")
    exe = executable_from_extract(root, key)
    if not exe.exists():
        raise RuntimeError(f"Chrome for Testing executable not found after extract: {exe}")
    exe.chmod(exe.stat().st_mode | 0o111)
    return exe, version


def safe_extract(zip_path: Path, destination: Path) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if target != destination and destination not in target.parents:
                raise RuntimeError(f"Refusing unsafe archive member: {member.filename}")
        archive.extractall(destination)


# ---------------------------------------------------------------------------
# Directories & preferences
# ---------------------------------------------------------------------------

def ensure_dirs(root: Path, download_dir: Path | None = None) -> dict[str, Path]:
    profile = root / "profile"
    downloads = download_dir.expanduser() if download_dir else root / "downloads"
    logs = root / "logs"
    for directory in (root, profile, downloads, logs):
        directory.mkdir(parents=True, exist_ok=True)
    return {"profile_dir": profile, "download_dir": downloads, "logs_dir": logs}


def set_chrome_preferences(profile: Path, download_dir: Path) -> None:
    default_dir = profile / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)
    prefs_path = default_dir / "Preferences"
    prefs: dict[str, Any] = {}
    if prefs_path.exists():
        try:
            prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prefs = {}
    prefs.setdefault("download", {})
    prefs["download"].update(
        {
            "default_directory": str(download_dir),
            "directory_upgrade": True,
            "prompt_for_download": False,
        }
    )
    prefs_path.write_text(json.dumps(prefs, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Commands: setup
# ---------------------------------------------------------------------------

def setup(args: argparse.Namespace) -> int:
    root = args.root.expanduser()
    config = load_config(root)
    configured_download_dir = Path(config["download_dir"]).expanduser() if config.get("download_dir") else None
    if args.download_dir:
        download_dir = args.download_dir
    elif configured_download_dir:
        download_dir = configured_download_dir
    elif sys.stdin.isatty():
        default_dir = root / "downloads"
        print()
        print("================================================")
        print("  视频存放位置设置")
        print("================================================")
        print(f"  默认存放位置：{default_dir}")
        print()
        print("  如果你想存到别的文件夹，请打开 Finder，")
        print("  选中文件夹后按 Cmd+C 复制，再粘贴到下面。")
        print("  直接按回车就用默认位置。")
        print("------------------------------------------------")
        answer = input("  视频存放路径: ").strip()
        if answer:
            download_dir = Path(answer)
            if not download_dir.exists():
                download_dir.mkdir(parents=True, exist_ok=True)
        else:
            download_dir = default_dir
        print("================================================")
        print(f"  已设置：{download_dir}")
        print()
    else:
        download_dir = None
    dirs = ensure_dirs(root, download_dir)

    extension_dir = Path(args.extension_dir or DEFAULT_EXTENSION_DIR).expanduser()
    if not (extension_dir / "manifest.json").exists():
        raise RuntimeError(f"Extension manifest not found in: {extension_dir}")

    chrome_executable: Path | None = None
    if args.chrome_executable:
        chrome_executable = args.chrome_executable.expanduser()
        if not chrome_executable.exists():
            raise RuntimeError(f"Chrome executable does not exist: {chrome_executable}")
        chrome_version = "manual"
    elif config.get("chrome_executable") and Path(config["chrome_executable"]).exists():
        chrome_executable = Path(config["chrome_executable"])
        chrome_version = config.get("chrome_version", "configured")
    elif args.no_install:
        chrome_version = "missing"
    else:
        chrome_executable, chrome_version = install_chrome(root, args.channel)

    ffprobe = find_ffprobe(args.ffprobe)
    new_config = {
        **config,
        "root": str(root),
        "chrome_executable": str(chrome_executable) if chrome_executable else "",
        "chrome_version": chrome_version,
        "profile_dir": str(dirs["profile_dir"]),
        "download_dir": str(dirs["download_dir"]),
        "extension_dir": str(extension_dir),
        "logs_dir": str(dirs["logs_dir"]),
        "ffprobe": ffprobe or "",
    }
    save_config(root, new_config)
    status = "ok" if chrome_executable else "needs_chrome"
    result = {"status": status, "config": new_config}
    if sys.stdin.isatty():
        result["download_dir"] = str(dirs["download_dir"])
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def require_config(root: Path) -> dict[str, Any]:
    config = load_config(root)
    missing = [key for key in ("chrome_executable", "profile_dir", "download_dir") if not config.get(key)]
    if missing:
        raise RuntimeError(f"Run setup first; missing config keys: {', '.join(missing)}")
    exe = Path(config["chrome_executable"])
    if not exe.exists():
        raise RuntimeError(f"Configured Chrome executable does not exist: {exe}")
    return config


def resolve_extension_dir(config: dict[str, Any]) -> Path:
    ext = config.get("extension_dir")
    if ext:
        path = Path(ext).expanduser()
        if (path / "manifest.json").exists():
            return path
    path = DEFAULT_EXTENSION_DIR
    if (path / "manifest.json").exists():
        return path
    raise RuntimeError("Extension directory not found; run setup or pass --extension-dir")


# ---------------------------------------------------------------------------
# Chrome launch
# ---------------------------------------------------------------------------

def build_launch_args(
    config: dict[str, Any],
    url: str,
    with_extension: bool,
    headless: bool = False,
) -> list[str]:
    profile = Path(config["profile_dir"]).expanduser()
    downloads = Path(config["download_dir"]).expanduser()
    downloads.mkdir(parents=True, exist_ok=True)
    set_chrome_preferences(profile, downloads)

    cmd = [
        config["chrome_executable"],
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-first-run-ui",
        "--disable-session-crashed-bubble",
    ]
    if with_extension:
        ext_dir = str(resolve_extension_dir(config))
        cmd.extend([f"--disable-extensions-except={ext_dir}", f"--load-extension={ext_dir}"])
    if headless:
        cmd.append("--headless=new")
    cmd.append(url)
    return cmd


def terminate_owned_process(proc: subprocess.Popen[bytes], timeout: int = 10) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=timeout)


# ---------------------------------------------------------------------------
# Commands: login
# ---------------------------------------------------------------------------

def login(args: argparse.Namespace) -> int:
    config = require_config(args.root.expanduser())
    url = args.url or DEFAULT_YUANBAO_URL
    cmd = build_launch_args(config, url, with_extension=False)
    proc = subprocess.Popen(cmd)
    print(json.dumps({
        "status": "waiting_for_user",
        "pid": proc.pid,
        "url": url,
        "message": "在打开的 Chrome 窗口里扫码登录腾讯元宝。登录完成后关闭窗口即可，登录态会保存在独立 profile 中。",
    }, ensure_ascii=False))
    if args.wait:
        return proc.wait()
    return 0


# ---------------------------------------------------------------------------
# HTTP handoff server: extension POSTs video source URL here
# ---------------------------------------------------------------------------

class HandoffServer:
    """Tiny HTTP server that waits for the extension to POST the resolved
    video source URL, then signals the main thread."""

    def __init__(self) -> None:
        self.result: dict[str, Any] | None = None
        self.error: str | None = None
        self._event = threading.Event()
        self._server: http.server.HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("Server not started")
        return self._server.server_address[1]

    def start(self) -> int:
        handoff = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _respond(self, code: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("access-control-allow-origin", "*")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                if self.path != "/handoff":
                    self._respond(404, {"ok": False, "error": "not found"})
                    return
                length = int(self.headers.get("content-length", 0))
                try:
                    data = json.loads(self.rfile.read(length))
                except Exception:
                    handoff.error = "invalid JSON from extension"
                    handoff._event.set()
                    self._respond(400, {"ok": False, "error": "invalid json"})
                    return
                handoff.result = data
                handoff._event.set()
                self._respond(200, {"ok": True})

            def do_OPTIONS(self) -> None:
                self.send_response(204)
                self.send_header("access-control-allow-origin", "*")
                self.send_header("access-control-allow-methods", "POST, OPTIONS")
                self.send_header("access-control-allow-headers", "content-type")
                self.end_headers()

            def log_message(self, *_args: Any) -> None:
                pass

        self._server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.port

    def wait(self, timeout: float = 120) -> dict[str, Any]:
        if not self._event.wait(timeout):
            raise TimeoutError(f"Extension did not hand off within {timeout}s")
        if self.error:
            raise RuntimeError(self.error)
        if not self.result:
            raise RuntimeError("No result received")
        return self.result

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()


# ---------------------------------------------------------------------------
# Direct download (bypasses chrome.downloads entirely)
# ---------------------------------------------------------------------------

def download_video(
    url: str,
    download_dir: Path,
    short_id: str,
    referer: str | None = None,
    timeout: int = 600,
) -> Path:
    """Download a video URL directly with urllib."""
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in short_id)
    filename = f"{safe_name}.mp4"
    filepath = download_dir / filename
    req = urllib.request.Request(url)
    req.add_header("user-agent", "Mozilla/5.0")
    if referer:
        req.add_header("referer", referer)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        total = 0
        with open(filepath, "wb") as f:
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
    return filepath


# ---------------------------------------------------------------------------
# File validation
# ---------------------------------------------------------------------------

def ffprobe_duration(path: Path, ffprobe: str) -> float:
    completed = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"ffprobe failed for {path}")
    return float(completed.stdout.strip())


def validate_file(path: Path, ffprobe: str | None) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise RuntimeError(f"File does not exist: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise RuntimeError(f"File is empty: {path}")
    report: dict[str, Any] = {"status": "accepted", "path": str(path), "bytes": size}
    if ffprobe:
        duration = ffprobe_duration(path, ffprobe)
        if duration <= 0:
            raise RuntimeError(f"ffprobe duration is not positive: {duration}")
        report["duration_seconds"] = duration
    else:
        report["warning"] = "ffprobe not configured; accepted by non-empty file only"
    return report


# ---------------------------------------------------------------------------
# Commands: capture
# ---------------------------------------------------------------------------

def capture(args: argparse.Namespace) -> int:
    config = require_config(args.root.expanduser())
    download_dir = Path(config["download_dir"]).expanduser()
    ffprobe = config.get("ffprobe") or None

    # 1. Start handoff HTTP server
    handoff = HandoffServer()
    port = handoff.start()

    # 2. Build yuanbao URL with capture task in hash fragment
    short_id = args.url.split("/sph/")[1] if "/sph/" in args.url else "video"
    encoded_url = urllib.parse.quote(args.url, safe="")
    chrome_url = f"{DEFAULT_YUANBAO_URL}#cap_port={port}&cap_url={encoded_url}"

    # 3. Launch Chrome headless with extension
    cmd = build_launch_args(config, chrome_url, with_extension=True, headless=args.headless)
    proc = subprocess.Popen(cmd)
    print(json.dumps({
        "status": "launched",
        "pid": proc.pid,
        "headless": args.headless,
        "handoff_port": port,
        "message": "Chrome 已启动，扩展正在解析视频号链接...",
    }, ensure_ascii=False))

    try:
        # 4. Wait for extension to hand off the video source URL
        video_info = handoff.wait(timeout=args.parse_timeout)
        source_url = video_info["url"]
        title = video_info.get("title", short_id)
        sid = video_info.get("short_id", short_id)

        print(json.dumps({"status": "downloading", "url_source": source_url[:80] + "..."}, ensure_ascii=False))

        # 5. Download directly with urllib (cross-platform reliable)
        filepath = download_video(source_url, download_dir, sid)

        # 6. Validate
        report = validate_file(filepath, ffprobe)
        report["title"] = title
        print(json.dumps(report, indent=2, ensure_ascii=False))
    finally:
        terminate_owned_process(proc)
        handoff.stop()

    return 0


# ---------------------------------------------------------------------------
# Commands: verify, doctor, self-test
# ---------------------------------------------------------------------------

def verify(args: argparse.Namespace) -> int:
    ffprobe = find_ffprobe(args.ffprobe)
    report = validate_file(args.path.expanduser(), ffprobe)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def doctor(args: argparse.Namespace) -> int:
    root = args.root.expanduser()
    config = load_config(root)
    chrome_path = Path(config["chrome_executable"]).expanduser() if config.get("chrome_executable") else None
    profile_dir = Path(config["profile_dir"]).expanduser() if config.get("profile_dir") else root / "profile"
    download_dir = Path(config["download_dir"]).expanduser() if config.get("download_dir") else root / "downloads"
    extension_dir = Path(config["extension_dir"]).expanduser() if config.get("extension_dir") else DEFAULT_EXTENSION_DIR

    chrome_version_output = ""
    if chrome_path and chrome_path.exists():
        completed = subprocess.run(
            [str(chrome_path), "--version"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=15,
        )
        chrome_version_output = (completed.stdout or completed.stderr).strip()

    checks: dict[str, Any] = {
        "root": str(root),
        "config_exists": (root / "config.json").exists(),
        "chrome_executable": config.get("chrome_executable", ""),
        "chrome_exists": bool(chrome_path and chrome_path.exists()),
        "chrome_version_output": chrome_version_output,
        "profile_dir": str(profile_dir),
        "profile_exists": profile_dir.exists(),
        "profile_writable": os.access(profile_dir, os.W_OK),
        "download_dir": str(download_dir),
        "download_exists": download_dir.exists(),
        "download_writable": os.access(download_dir, os.W_OK),
        "extension_dir": str(extension_dir),
        "extension_manifest_exists": (extension_dir / "manifest.json").exists(),
        "extension_service_worker_exists": (extension_dir / "service-worker.js").exists(),
        "ffprobe": config.get("ffprobe") or find_ffprobe(),
    }
    status = "ok"
    if not checks["config_exists"]:
        status = "needs_setup"
    elif not checks["chrome_exists"]:
        status = "needs_chrome"
    elif not checks["extension_manifest_exists"]:
        status = "needs_extension"
    elif not checks["profile_exists"] or not checks["profile_writable"] or not checks["download_exists"] or not checks["download_writable"]:
        status = "needs_permission_fix"
    elif not checks["ffprobe"]:
        status = "ok_with_warning"
    print(json.dumps({"status": status, "checks": checks}, indent=2, ensure_ascii=False))
    return 0


def self_test(args: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory(prefix="shouzhuo-capture-self-test-") as temp:
        root = Path(temp)
        custom_downloads = root / "custom-downloads"
        with contextlib.redirect_stdout(io.StringIO()):
            setup(argparse.Namespace(
                root=root, download_dir=custom_downloads,
                chrome_executable=None, ffprobe=None,
                no_install=True, channel="Stable",
                extension_dir=str(DEFAULT_EXTENSION_DIR),
            ))
        config = load_config(root)
        assert Path(config["download_dir"]) == custom_downloads
        assert Path(config["extension_dir"]) == DEFAULT_EXTENSION_DIR

        # Test handoff server
        hs = HandoffServer()
        p = hs.start()
        assert p > 0
        # Simulate extension POST
        test_payload = {"url": "https://example.com/video.mp4", "short_id": "test123", "title": "Test"}
        req = urllib.request.Request(f"http://127.0.0.1:{p}/handoff", data=json.dumps(test_payload).encode(), method="POST")
        req.add_header("content-type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
        result = hs.wait(timeout=5)
        assert result["short_id"] == "test123"
        hs.stop()

    print(json.dumps({"status": "ok"}, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    root_parent = argparse.ArgumentParser(add_help=False)
    root_parent.add_argument("--root", type=Path, default=argparse.SUPPRESS, help="state root; defaults to ~/.shouzhuo-capture")

    parser = argparse.ArgumentParser(description="Shouzhuo Capture — WeChat Channels video downloader")
    parser.add_argument("--root", type=Path, default=default_root(), help="state root; defaults to ~/.shouzhuo-capture")
    sub = parser.add_subparsers(dest="command", required=True)

    setup_parser = sub.add_parser("setup", parents=[root_parent], help="install Chrome for Testing and create local state")
    setup_parser.add_argument("--channel", default="Stable", choices=["Stable", "Beta", "Dev", "Canary"])
    setup_parser.add_argument("--chrome-executable", type=Path)
    setup_parser.add_argument("--download-dir", type=Path)
    setup_parser.add_argument("--extension-dir", type=Path)
    setup_parser.add_argument("--ffprobe")
    setup_parser.add_argument("--no-install", action="store_true", help="do not download Chrome for Testing")
    setup_parser.set_defaults(func=setup)

    login_parser = sub.add_parser("login", parents=[root_parent], help="open Chrome to log in to Tencent Yuanbao")
    login_parser.add_argument("--url", default="")
    login_parser.add_argument("--wait", action="store_true")
    login_parser.set_defaults(func=login)

    capture_parser = sub.add_parser("capture", parents=[root_parent], help="download a WeChat Channels video")
    capture_parser.add_argument("url", help="weixin.qq.com/sph/... share link")
    capture_parser.add_argument("--no-headless", dest="headless", action="store_false", help="show the browser window")
    capture_parser.add_argument("--parse-timeout", type=int, default=120, help="seconds to wait for extension to resolve the link")
    capture_parser.add_argument("--keep-open", dest="close_after_accept", action="store_false", help="leave browser open after download")
    capture_parser.set_defaults(func=capture, headless=True)

    verify_parser = sub.add_parser("verify", parents=[root_parent], help="validate a local media file")
    verify_parser.add_argument("path", type=Path)
    verify_parser.add_argument("--ffprobe")
    verify_parser.set_defaults(func=verify)

    doctor_parser = sub.add_parser("doctor", parents=[root_parent], help="diagnose local setup")
    doctor_parser.set_defaults(func=doctor)

    self_test_parser = sub.add_parser("self-test", help="run offline helper self-tests")
    self_test_parser.set_defaults(func=self_test)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

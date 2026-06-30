"""
Desktop GUI entry point for EComCrawler.

Architecture
============
  - Flask runs on a random localhost port in a daemon thread.
  - PyWebView wraps it in a native OS window (Edge/WebView2 on Windows,
    WebKit on macOS/Linux).  Falls back to the system browser when
    PyWebView is not installed (useful for development on Linux).
  - Each scrape job runs in its own daemon thread identified by a UUID.
  - The frontend polls GET /api/status/<job_id> every 2 s for progress.
  - On completion, CSVs are auto-saved to ~/Downloads/EComCrawler/.
    In browser mode, /download/<path> also serves them directly.

PyInstaller notes
=================
  When frozen, __file__ is inside the _MEIPASS temp directory.
  All file-path lookups use BASE_DIR (resolved at import time) so they
  work identically whether run from source or from the bundled exe.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_from_directory

# ── Path resolution (works both from source and PyInstaller bundle) ───────────

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)  # type: ignore[attr-defined]
else:
    BASE_DIR = Path(__file__).parent

FRONTEND_DIR = BASE_DIR / "frontend"

# Temp working dir for in-progress jobs
OUTPUT_DIR = Path(tempfile.gettempdir()) / "ecomcrawler_out"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Final save location: ~/Downloads/EComCrawler/
_downloads_base = Path.home() / "Downloads"
if not _downloads_base.exists():
    _downloads_base = Path.home()
DOWNLOADS_DIR = _downloads_base / "EComCrawler"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# ── Global mode flag (set in main() before Flask starts) ──────────────────────

IS_WEBVIEW = False   # True when running inside PyWebView window

# ── Job registry ──────────────────────────────────────────────────────────────

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_cancel_events: dict[str, threading.Event] = {}

# ── Flask app ─────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=None)
log = logging.getLogger(__name__)


@app.route("/")
def index():
    return send_from_directory(str(FRONTEND_DIR), "index.html")


@app.route("/static/<path:filename>")
def static_files(filename: str):
    return send_from_directory(str(FRONTEND_DIR / "static"), filename)


@app.route("/api/mode")
def api_mode():
    """Tell the frontend whether we're inside a PyWebView window."""
    return jsonify({"webview": IS_WEBVIEW})


@app.route("/api/extract", methods=["POST"])
def api_extract():
    data = request.get_json(force=True) or {}
    url = (data.get("link") or "").strip()
    no_skip = bool(data.get("no_skip", False))
    if not url:
        return jsonify({"error": "لینک نمی‌تواند خالی باشد"}), 400

    job_id = str(uuid.uuid4())
    cancel_event = threading.Event()
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "logs": [],
            "message": "",
            "files": [],
            "downloads_dir": "",
            "error": "",
        }
        _cancel_events[job_id] = cancel_event

    threading.Thread(target=_run_job, args=(job_id, url, no_skip, cancel_event), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def api_status(job_id: str):
    with _jobs_lock:
        job = dict(_jobs.get(job_id) or {})
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/api/cancel/<job_id>", methods=["POST"])
def api_cancel(job_id: str):
    with _jobs_lock:
        event = _cancel_events.get(job_id)
    if not event:
        return jsonify({"error": "Job not found"}), 404
    event.set()
    return jsonify({"ok": True})


@app.route("/download/<path:filename>")
def download_file(filename: str):
    return send_from_directory(str(OUTPUT_DIR), filename, as_attachment=True)


# ── PyWebView JS API (exposed to the frontend as window.pywebview.api) ────────

class _JsApi:
    """Methods callable from JavaScript via window.pywebview.api.<method>()."""

    def open_folder(self, path: str) -> None:
        """Open the given folder path in the OS file explorer."""
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", path])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            log.warning("Could not open folder %s: %s", path, exc)


# ── Log capture ───────────────────────────────────────────────────────────────

class _JobLogHandler(logging.Handler):
    """Appends formatted log records to a job's log list."""

    def __init__(self, job_id: str) -> None:
        super().__init__()
        self.job_id = job_id

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        with _jobs_lock:
            entry = _jobs.get(self.job_id)
            if entry is not None:
                entry["logs"].append(msg)


# ── Crawler job ───────────────────────────────────────────────────────────────

_REGISTRY = {
    "basalam.com":  "crawlers.basalam:BasalamCrawler",
    "emalls.ir":    "crawlers.emalls:EmallsCrawler",
    "snappshop.ir": "crawlers.snappshop:SnappShopCrawler",
    "shopino.app":  "crawlers.shopino:ShopinoCrawler",
}


def _resolve_crawler(url: str):
    """Return an instantiated crawler for *url*, or raise ValueError."""
    host = urlparse(url).netloc.lower().lstrip("www.")
    for domain, dotted in _REGISTRY.items():
        if host == domain or host.endswith("." + domain):
            module_path, cls_name = dotted.split(":")
            import importlib
            mod = importlib.import_module(module_path)
            return getattr(mod, cls_name)()
    supported = ", ".join(_REGISTRY)
    raise ValueError(
        f"سایت «{host}» پشتیبانی نمی‌شود.\n"
        f"سایت‌های پشتیبانی‌شده: {supported}"
    )


def _run_job(job_id: str, url: str, no_skip: bool = False, cancel_event: threading.Event | None = None) -> None:
    from crawlers.base import CrawlerError, ProductUnavailableError
    from exporters.sazito_csv import SazitoCsvExporter
    from memory import ExportMemory

    handler = _JobLogHandler(job_id)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    )
    root = logging.getLogger()
    root.addHandler(handler)

    try:
        crawler = _resolve_crawler(url)
        source_site = crawler.site_name
        vendor_id = crawler.extract_vendor_id(url)

        job_out = OUTPUT_DIR / job_id
        job_out.mkdir(parents=True, exist_ok=True)

        stats = {"seen": 0, "skipped": 0, "exported": 0, "errors": 0}

        with ExportMemory() as memory, \
             SazitoCsvExporter(str(job_out), file_prefix="output") as exporter:

            for product_id in crawler.iter_product_ids(vendor_id):
                if cancel_event and cancel_event.is_set():
                    log.info("Job cancelled after %d products exported", stats["exported"])
                    break

                stats["seen"] += 1

                if not no_skip and memory.is_exported(source_site, product_id):
                    stats["skipped"] += 1
                    continue

                try:
                    product = crawler.get_product_detail(product_id)
                    time.sleep(crawler.rate_limit)
                except ProductUnavailableError:
                    stats["skipped"] += 1
                    continue
                except CrawlerError as exc:
                    log.warning("Failed to fetch %s: %s", product_id, exc)
                    stats["errors"] += 1
                    continue

                if not product.is_active:
                    stats["skipped"] += 1
                    continue

                exporter.write_product(product)
                memory.mark_exported(source_site, product_id, vendor_id)
                stats["exported"] += 1
                log.info("[%d] %s | %s", stats["exported"], product_id, product.title[:60])

        cancelled = bool(cancel_event and cancel_event.is_set())
        csv_files = sorted(f for f in job_out.iterdir() if f.suffix == ".csv")

        # Copy finished CSVs to ~/Downloads/EComCrawler/<vendor_id>/
        # so they're accessible from a native file manager on Windows.
        save_dir = DOWNLOADS_DIR / vendor_id
        save_dir.mkdir(parents=True, exist_ok=True)
        for f in csv_files:
            shutil.copy2(str(f), str(save_dir / f.name))
        log.info("Files saved to %s", save_dir)

        files = [
            {"filename": f"{job_id}/{f.name}", "name": f.name}
            for f in csv_files
        ]
        if cancelled:
            message = (
                f"لغو شد — "
                f"{stats['exported']} محصول ذخیره شد "
                f"({stats['skipped']} رد شد، {stats['errors']} خطا)"
            )
        else:
            message = (
                f"استخراج کامل شد — "
                f"{stats['exported']} محصول جدید "
                f"({stats['skipped']} رد شد، {stats['errors']} خطا)"
            )
        with _jobs_lock:
            _jobs[job_id].update(
                status="cancelled" if cancelled else "done",
                message=message,
                files=files,
                downloads_dir=str(save_dir),
            )

    except Exception as exc:  # noqa: BLE001
        log.error("Job %s failed: %s", job_id, exc)
        with _jobs_lock:
            _jobs[job_id].update(status="error", error=str(exc))
    finally:
        root.removeHandler(handler)


# ── Entry point ───────────────────────────────────────────────────────────────

def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    global IS_WEBVIEW

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Persist all logs to a file alongside the output CSVs
    log_file = DOWNLOADS_DIR / "ecomcrawler.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")
    )
    logging.getLogger().addHandler(file_handler)
    log.info("Log file: %s", log_file)

    port = _find_free_port()
    flask_thread = threading.Thread(
        target=lambda: app.run(
            host="127.0.0.1", port=port, debug=False, use_reloader=False
        ),
        daemon=True,
    )
    flask_thread.start()
    time.sleep(0.8)  # give Flask a moment to bind

    url = f"http://127.0.0.1:{port}"

    _has_webview = False
    try:
        import webview  # type: ignore[import]
        _has_webview = True
    except ImportError:
        pass

    if _has_webview:
        try:
            IS_WEBVIEW = True
            api = _JsApi()
            window = webview.create_window(  # noqa: F821
                "🐙 EComCrawler",
                url,
                width=700,
                height=720,
                resizable=True,
                min_size=(560, 520),
                js_api=api,
            )
            webview.start()  # noqa: F821
            return
        except Exception as exc:
            IS_WEBVIEW = False
            log.info("pywebview backend unavailable (%s) — falling back to browser", exc)

    import webbrowser
    log.info("Opening browser at %s  (press Ctrl+C to quit)", url)
    webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

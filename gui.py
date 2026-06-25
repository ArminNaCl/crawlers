"""
Desktop GUI entry point for the Product Scraper application.

Architecture
============
  - Flask runs on a random localhost port in a daemon thread.
  - PyWebView wraps it in a native OS window (Edge/WebView2 on Windows,
    WebKit on macOS/Linux).  Falls back to the system browser when
    PyWebView is not installed (useful for development on Linux).
  - Each scrape job runs in its own daemon thread identified by a UUID.
  - The frontend polls GET /api/status/<job_id> every 2 s for progress.
  - Finished CSV files are served via GET /download/<path>.

PyInstaller notes
=================
  When frozen, __file__ is inside the _MEIPASS temp directory.
  All file-path lookups use BASE_DIR (resolved at import time) so they
  work identically whether run from source or from the bundled exe.
"""

from __future__ import annotations

import logging
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

# Per-session output lives in a sub-folder of the system temp dir so it
# survives across multiple crawls in one session but is cleaned up on reboot.
OUTPUT_DIR = Path(tempfile.gettempdir()) / "product_scraper_out"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Job registry ──────────────────────────────────────────────────────────────

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

# ── Flask app ─────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=None)
log = logging.getLogger(__name__)


@app.route("/")
def index():
    return send_from_directory(str(FRONTEND_DIR), "index.html")


@app.route("/static/<path:filename>")
def static_files(filename: str):
    return send_from_directory(str(FRONTEND_DIR / "static"), filename)


@app.route("/api/extract", methods=["POST"])
def api_extract():
    data = request.get_json(force=True) or {}
    url = (data.get("link") or "").strip()
    if not url:
        return jsonify({"error": "لینک نمی‌تواند خالی باشد"}), 400

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "logs": [],
            "message": "",
            "files": [],
            "error": "",
        }

    threading.Thread(target=_run_job, args=(job_id, url), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def api_status(job_id: str):
    with _jobs_lock:
        job = dict(_jobs.get(job_id) or {})
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/download/<path:filename>")
def download_file(filename: str):
    return send_from_directory(str(OUTPUT_DIR), filename, as_attachment=True)


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


def _run_job(job_id: str, url: str) -> None:
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
                stats["seen"] += 1

                if memory.is_exported(source_site, product_id):
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

        csv_files = sorted(f for f in job_out.iterdir() if f.suffix == ".csv")
        files = [
            {"filename": f"{job_id}/{f.name}", "name": f.name}
            for f in csv_files
        ]

        message = (
            f"استخراج کامل شد — "
            f"{stats['exported']} محصول جدید "
            f"({stats['skipped']} رد شد، {stats['errors']} خطا)"
        )
        with _jobs_lock:
            _jobs[job_id].update(status="done", message=message, files=files)

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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

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

    _use_webview = False
    try:
        import webview  # type: ignore[import]
        _use_webview = True
    except ImportError:
        pass

    if _use_webview:
        try:
            window = webview.create_window(  # noqa: F821
                "Product Scraper — استخراج محصولات",
                url,
                width=700,
                height=720,
                resizable=True,
                min_size=(560, 520),
            )
            webview.start()  # noqa: F821
            return
        except Exception as exc:
            # WebViewException: no GTK/Qt backend available (common on Linux)
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

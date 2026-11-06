import os
import re
import io
import sys
import time
import json
import uuid
import base64
import socket
import zipfile
import threading
import subprocess
from pathlib import Path
from collections import OrderedDict
from urllib.parse import urlparse, unquote
from flask import Flask, render_template, request, jsonify, Response
from PIL import Image
from bs4 import BeautifulSoup

from scraper import (
    create_session,
    scrape_page,
    register_browser_fetcher,
    is_cloudflare_challenge,
    extract_real_image_from_viewer_html,
    extract_texts_and_links,
    format_text_with_links_for_txt,
    is_likely_video_url,
    KNOWN_IMAGE_HOST_DOMAINS,
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    FILE_ARCHIVE_EXTENSIONS,
)

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
LOG_PATH = BASE_DIR / "app.log"
DEFAULT_DOWNLOAD_DIR = str(Path.home() / "Downloads" / "ImageDownloader")

# Fix stdout/stderr when running under pythonw.exe or Turkish cp1254 console so logging never fails
if sys.stdout is None:
    sys.stdout = open(LOG_PATH, "a", encoding="utf-8", errors="replace")
elif hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if sys.stderr is None:
    sys.stderr = open(LOG_PATH, "a", encoding="utf-8", errors="replace")
elif hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/avif": ".avif",
    "image/svg+xml": ".svg",
    "image/tiff": ".tiff",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/x-matroska": ".mkv",
    "video/quicktime": ".mov",
    "video/x-msvideo": ".avi",
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "application/x-rar-compressed": ".rar",
    "application/x-7z-compressed": ".7z",
    "text/plain": ".txt",
}

FORMAT_TO_EXT = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "GIF": ".gif",
    "BMP": ".bmp",
    "TIFF": ".tiff",
    "AVIF": ".avif",
    "MPO": ".jpg",
}


def load_config() -> dict:
    default_cfg = {
        "download_dir": DEFAULT_DOWNLOAD_DIR,
        "min_size": 120,
        "create_site_subfolder": True,
        "large_file_threshold_mb": 5,
        "include_links_in_txt": True,
    }
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                default_cfg.update(data)
        except Exception:
            pass
    os.makedirs(default_cfg["download_dir"], exist_ok=True)
    return default_cfg


def save_config(cfg: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


app = Flask(__name__, template_folder="templates", static_folder="static")
# Dedicated session for scraping HTML pages so thumbnail proxy requests never contend with or pollute page cookies
page_scraper_session = create_session("chrome")
# Dedicated session with large connection pool for concurrent thumbnail proxies & file downloads
scraper_session = create_session("chrome")
config = load_config()

# Track current page scrape epoch so stale thumbnail proxy requests from previous pages abort immediately
current_scrape_epoch = 0

# In-memory LRU cache for thumbnail proxy responses so repeated forum assets/thumbs load in 0ms
PROXY_CACHE = OrderedDict()
PROXY_CACHE_LOCK = threading.Lock()
PROXY_CACHE_MAX = 400


def sanitize_folder_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" ._")
    return cleaned[:80] if cleaned else "Genel"


def sanitize_filename(name: str, default_name: str = "dosya") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (name or "").strip()).strip(" ._")
    return cleaned[:140] if cleaned else default_name


def get_target_directory(referer: str = "", item_url: str = "", site_title: str = "") -> Path:
    target_dir = Path(config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
    if config.get("create_site_subfolder", True):
        domain = urlparse(referer or item_url).netloc.replace("www.", "")
        folder_label = sanitize_folder_name(domain or site_title or "Indirilenler")
        target_dir = target_dir / folder_label
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def get_unique_filepath(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    counter = 1
    while True:
        new_candidate = directory / f"{stem}_({counter}){suffix}"
        if not new_candidate.exists():
            return new_candidate
        counter += 1


def validate_image_bytes(data: bytes, content_type: str = ""):
    """
    Verifies that `data` is actual image binary content (not an empty file or HTML error page).
    Returns (is_valid: bool, detected_ext: str or None, mime_type: str).
    """
    if not data or len(data) < 32:
        return False, None, ""

    head = data[:256].lstrip().lower()
    if head.startswith((b"<!doctype html", b"<html", b"<head", b"<script", b"access denied", b"403 forbidden")):
        return False, None, ""

    # Check if SVG
    if b"<svg" in head[:200] or "image/svg" in content_type:
        return True, ".svg", "image/svg+xml"

    # Verify with Pillow
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = (im.format or "").upper()
            ext = FORMAT_TO_EXT.get(fmt, MIME_TO_EXT.get(content_type, ".jpg"))
            mime = Image.MIME.get(fmt, content_type or "image/jpeg")
            return True, ext, mime
    except Exception:
        # If Pillow cannot decode (e.g., some AVIF builds), check Content-Type & magic bytes
        if content_type.startswith("image/") and len(data) > 128:
            return True, MIME_TO_EXT.get(content_type, ".jpg"), content_type
        return False, None, ""


def fetch_valid_image(target_url: str, referer: str = "", fallback_thumb_url: str = "", progress_cb=None, is_proxy: bool = False):
    """
    Fetches an image from `target_url` with optional streaming progress callback.
    Returns (image_bytes, detected_ext, mime_type).
    """
    req_timeout = 10 if is_proxy else 25

    def _download_raw(url_to_get: str, ref_header: str):
        headers = {
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        if ref_header:
            headers["Referer"] = ref_header
        resp = None
        use_stream = bool(progress_cb is not None)
        try:
            resp = scraper_session.get(url_to_get, headers=headers, timeout=req_timeout, stream=use_stream)
            resp.raise_for_status()
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            total_len = int(resp.headers.get("Content-Length") or 0)
            final_resp_url = str(resp.url)

            if not use_stream:
                return resp.content or b"", ctype, final_resp_url

            chunks = []
            downloaded = 0
            for chunk in resp.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                chunks.append(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    progress_cb(downloaded, total_len)
            return b"".join(chunks), ctype, final_resp_url
        except Exception:
            return None, "", url_to_get
        finally:
            if resp:
                resp.close()

    def try_single_url(url_to_get: str, ref: str, allow_html_resolve=True):
        if not url_to_get:
            return None, None, None

        if url_to_get.startswith("data:image/"):
            try:
                header, b64_data = url_to_get.split(",", 1)
                mime = header.split(";")[0].replace("data:", "").strip().lower()
                raw_bytes = base64.b64decode(b64_data)
                ok, ext, out_mime = validate_image_bytes(raw_bytes, mime)
                if ok:
                    if progress_cb:
                        progress_cb(len(raw_bytes), len(raw_bytes))
                    return raw_bytes, ext, out_mime
            except Exception:
                return None, None, None

        parsed_u = urlparse(url_to_get)
        self_ref = f"{parsed_u.scheme}://{parsed_u.netloc}/"

        # Try candidate referers in order: page referer -> image host self-origin -> no referer
        candidate_refs = []
        for r in (ref, self_ref, ""):
            if r not in candidate_refs:
                candidate_refs.append(r)

        last_html_bytes = None
        last_ctype = ""
        last_resp_url = url_to_get

        for cand_ref in candidate_refs:
            content_bytes, ctype, final_resp_url = _download_raw(url_to_get, cand_ref)
            if not content_bytes:
                continue
            ok, ext, out_mime = validate_image_bytes(content_bytes, ctype)
            if ok:
                return content_bytes, ext, out_mime
            if last_html_bytes is None:
                last_html_bytes = content_bytes
                last_ctype = ctype
                last_resp_url = final_resp_url
            # If it's a known image viewer HTML page (not a hotlink error on a .jpg URL), break early to resolve it
            if allow_html_resolve and not any(parsed_u.path.lower().endswith(e) for e in IMAGE_EXTENSIONS):
                break

        # If we received an HTML page (viewer page), extract the real image URL from inside it
        if allow_html_resolve and last_html_bytes and (
            "text/html" in last_ctype or last_html_bytes[:100].lstrip().lower().startswith((b"<!doctype", b"<html"))
        ):
            html_str = last_html_bytes.decode("utf-8", errors="replace")
            real_img_url = extract_real_image_from_viewer_html(html_str, last_resp_url)
            if real_img_url and real_img_url != url_to_get:
                return try_single_url(real_img_url, ref=last_resp_url, allow_html_resolve=False)

        return None, None, None

    img_bytes, ext, mime = try_single_url(target_url, referer, allow_html_resolve=not is_proxy)
    if img_bytes:
        return img_bytes, ext, mime

    if fallback_thumb_url and fallback_thumb_url != target_url:
        img_bytes, ext, mime = try_single_url(fallback_thumb_url, referer, allow_html_resolve=False)
        if img_bytes:
            return img_bytes, ext, mime

    raise ValueError("Görsel verisi alınamadı veya hedef adres geçerli bir resim içermiyor.")


# ==============================================================================
# SMART DOWNLOAD QUEUE & LARGE FILE MANAGER
# ==============================================================================

class DownloadQueueManager:
    """
    Manages single and multi-file downloads.
    - Probes file sizes and automatically queues large files (>= threshold MB) or videos
      so they download sequentially without choking bandwidth.
    - Small files can run up to 2 concurrently, but if a large file is active or multiple
      items are queued, excess tasks wait in 'queued' status with real-time progress tracking.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.tasks = {}          # task_id -> dict
        self.task_order = []     # list of task_ids in creation order
        self.active_count = 0
        self.active_large_count = 0
        self.max_small_concurrent = 2
        self.scheduler_event = threading.Event()
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.scheduler_thread.start()

    def _get_threshold_bytes(self) -> int:
        mb = float(config.get("large_file_threshold_mb", 5) or 5)
        return int(mb * 1024 * 1024)

    def probe_size(self, url: str, referer: str = "") -> int:
        """Quick HEAD request to estimate Content-Length before scheduling."""
        if not url or url.startswith("data:"):
            return 0
        headers = {}
        if referer:
            headers["Referer"] = referer
        try:
            resp = scraper_session.head(url, headers=headers, timeout=6, allow_redirects=True)
            cl = int(resp.headers.get("Content-Length") or 0)
            resp.close()
            return cl
        except Exception:
            return 0

    def add_tasks(self, items: list) -> list:
        created = []
        threshold_bytes = self._get_threshold_bytes()
        batch_size = len(items)

        for raw in items:
            task_id = f"dl_{uuid.uuid4().hex[:10]}"
            item_type = raw.get("item_type") or "image"  # image | video | text | link_txt | link_content
            url = (raw.get("url") or "").strip()
            thumb_url = (raw.get("thumb_url") or "").strip()
            referer = (raw.get("referer") or "").strip()
            filename = sanitize_filename(raw.get("filename") or "indirilen_dosya")
            site_title = (raw.get("site_title") or "").strip()
            source_type = (raw.get("source_type") or "direct").strip()

            known_size = int(raw.get("size_bytes") or 0)
            is_large = bool(
                item_type == "video"
                or (known_size >= threshold_bytes)
                or any(url.lower().endswith(ext) for ext in VIDEO_EXTENSIONS + (".zip", ".rar", ".7z", ".iso", ".pdf"))
            )

            with self.lock:
                busy = self.active_count > 0 or any(
                    self.tasks[tid]["status"] == "queued" for tid in self.task_order if tid in self.tasks
                )

                queue_reason = ""
                if is_large and (busy or batch_size > 1):
                    queue_reason = "Büyük dosya — Sıraya alındı"
                elif busy or batch_size > 1:
                    queue_reason = "Çoklu indirme sırası"

                task = {
                    "id": task_id,
                    "item_type": item_type,
                    "url": url,
                    "thumb_url": thumb_url,
                    "referer": referer,
                    "filename": filename,
                    "site_title": site_title,
                    "source_type": source_type,
                    "text_content": raw.get("text_content") or "",
                    "text_title": raw.get("text_title") or filename,
                    "links_list": raw.get("links_list") or [],
                    "include_links": raw.get("include_links", config.get("include_links_in_txt", True)),
                    "status": "queued",
                    "is_large": is_large,
                    "queue_reason": queue_reason,
                    "total_bytes": known_size,
                    "downloaded_bytes": 0,
                    "progress": 0.0,
                    "speed_kbps": 0.0,
                    "saved_path": "",
                    "size_kb": 0.0,
                    "error": "",
                    "cancel_requested": False,
                    "created_at": time.time(),
                }
                self.tasks[task_id] = task
                self.task_order.append(task_id)
                created.append(self._serialize_task(task))

        self.scheduler_event.set()
        return created

    def _serialize_task(self, t: dict, queue_pos: int = 0) -> dict:
        return {
            "id": t["id"],
            "item_type": t["item_type"],
            "url": t["url"],
            "filename": t["filename"],
            "status": t["status"],
            "is_large": t["is_large"],
            "queue_reason": t["queue_reason"],
            "queue_position": queue_pos,
            "total_bytes": t["total_bytes"],
            "downloaded_bytes": t["downloaded_bytes"],
            "progress": round(t["progress"], 1),
            "speed_kbps": round(t["speed_kbps"], 1),
            "saved_path": t["saved_path"],
            "size_kb": t["size_kb"],
            "error": t["error"],
        }

    def get_status_snapshot(self) -> dict:
        with self.lock:
            out_tasks = []
            q_pos = 0
            counts = {"queued": 0, "downloading": 0, "completed": 0, "failed": 0, "cancelled": 0}
            for tid in reversed(self.task_order):
                t = self.tasks.get(tid)
                if not t:
                    continue
                st = t["status"]
                counts[st] = counts.get(st, 0) + 1

            # Compute queue positions in FIFO order
            fifo_positions = {}
            for tid in self.task_order:
                t = self.tasks.get(tid)
                if t and t["status"] == "queued":
                    q_pos += 1
                    fifo_positions[tid] = q_pos

            for tid in reversed(self.task_order[-150:]):
                t = self.tasks.get(tid)
                if t:
                    out_tasks.append(self._serialize_task(t, fifo_positions.get(tid, 0)))

            return {
                "tasks": out_tasks,
                "counts": counts,
                "large_threshold_mb": config.get("large_file_threshold_mb", 5),
            }

    def cancel_task(self, task_id: str = "all"):
        with self.lock:
            targets = list(self.tasks.values()) if task_id == "all" else ([self.tasks[task_id]] if task_id in self.tasks else [])
            for t in targets:
                if t["status"] == "queued":
                    t["status"] = "cancelled"
                    t["cancel_requested"] = True
                elif t["status"] == "downloading":
                    t["cancel_requested"] = True
        self.scheduler_event.set()

    def clear_finished(self):
        with self.lock:
            keep_ids = []
            for tid in self.task_order:
                t = self.tasks.get(tid)
                if t and t["status"] in ("queued", "downloading"):
                    keep_ids.append(tid)
                else:
                    self.tasks.pop(tid, None)
            self.task_order = keep_ids

    def _scheduler_loop(self):
        while True:
            self.scheduler_event.wait(timeout=0.5)
            self.scheduler_event.clear()

            while True:
                next_task = None
                with self.lock:
                    queued_tasks = [
                        self.tasks[tid]
                        for tid in self.task_order
                        if tid in self.tasks and self.tasks[tid]["status"] == "queued"
                    ]
                    if not queued_tasks:
                        break

                    candidate = queued_tasks[0]

                    # Concurrency rules:
                    # 1. If a large file is currently downloading, wait until it finishes (strictly 1 at a time for large files)
                    if self.active_large_count > 0:
                        break

                    # 2. If candidate is known to be large and another download is active, wait for active downloads to finish
                    if candidate["is_large"] and self.active_count > 0:
                        if not candidate["queue_reason"]:
                            candidate["queue_reason"] = "Büyük dosya — Sıra bekleniyor"
                        break

                    # 3. Max concurrent downloads cap
                    if self.active_count >= self.max_small_concurrent:
                        break

                    # Start candidate
                    candidate["status"] = "downloading"
                    self.active_count += 1
                    if candidate["is_large"]:
                        self.active_large_count += 1
                    next_task = candidate

                if next_task:
                    worker = threading.Thread(target=self._run_task, args=(next_task,), daemon=True)
                    worker.start()
                else:
                    break

    def _run_task(self, task: dict):
        was_large = task["is_large"]
        threshold_bytes = self._get_threshold_bytes()
        start_time = time.time()

        def update_progress(downloaded: int, total: int):
            if task["cancel_requested"]:
                raise RuntimeError("İndirme kullanıcı tarafından iptal edildi.")
            elapsed = max(time.time() - start_time, 0.05)
            speed = (downloaded / 1024.0) / elapsed
            with self.lock:
                task["downloaded_bytes"] = downloaded
                if total > 0:
                    task["total_bytes"] = total
                    task["progress"] = min(99.5, (downloaded / total) * 100.0)
                    if total >= threshold_bytes and not task["is_large"]:
                        task["is_large"] = True
                        task["queue_reason"] = f"Büyük dosya ({round(total / (1024*1024), 1)} MB)"
                else:
                    task["progress"] = min(95.0, task["progress"] + 2.0)
                task["speed_kbps"] = speed

        try:
            # Before starting heavy transfer, if size is unknown for network file and other downloads are running, probe size
            if (
                not task["is_large"]
                and task["total_bytes"] == 0
                and task["item_type"] in ("image", "video", "link_content")
                and task["url"].startswith("http")
            ):
                probed = self.probe_size(task["url"], task["referer"])
                if probed > 0:
                    with self.lock:
                        task["total_bytes"] = probed
                        if probed >= threshold_bytes:
                            task["is_large"] = True
                            task["queue_reason"] = f"Büyük dosya ({round(probed / (1024*1024), 1)} MB) — Sıraya alındı"
                            # If another download is already active, re-queue this large file so it waits its turn!
                            if self.active_count > 1:
                                task["status"] = "queued"
                                self.active_count -= 1
                                self.scheduler_event.set()
                                return

            itype = task["item_type"]
            if itype == "image":
                self._execute_image_download(task, update_progress)
            elif itype == "video":
                self._execute_video_download(task, update_progress)
            elif itype == "text":
                self._execute_text_download(task)
            elif itype == "link_txt":
                self._execute_link_txt_download(task, update_progress)
            elif itype == "link_content":
                self._execute_link_content_download(task, update_progress)
            else:
                self._execute_link_content_download(task, update_progress)

            with self.lock:
                task["status"] = "completed"
                task["progress"] = 100.0

        except Exception as exc:
            with self.lock:
                if task["cancel_requested"]:
                    task["status"] = "cancelled"
                    task["error"] = "İptal edildi"
                else:
                    task["status"] = "failed"
                    task["error"] = str(exc)
        finally:
            with self.lock:
                self.active_count = max(0, self.active_count - 1)
                if was_large:
                    self.active_large_count = max(0, self.active_large_count - 1)
            self.scheduler_event.set()

    def _execute_image_download(self, task: dict, progress_cb):
        img_bytes, detected_ext, _ = fetch_valid_image(
            task["url"],
            referer=task["referer"],
            fallback_thumb_url=task["thumb_url"],
            progress_cb=progress_cb,
        )
        clean_name = sanitize_filename(task["filename"], "gorsel.jpg")
        base_stem, current_ext = os.path.splitext(clean_name)
        if detected_ext:
            clean_name = f"{base_stem}{detected_ext}"
        elif not current_ext:
            clean_name = f"{base_stem}.jpg"

        target_dir = get_target_directory(task["referer"], task["url"], task["site_title"])
        save_path = get_unique_filepath(target_dir, clean_name)
        with open(save_path, "wb") as f:
            f.write(img_bytes)

        with self.lock:
            task["filename"] = save_path.name
            task["saved_path"] = str(save_path)
            task["downloaded_bytes"] = len(img_bytes)
            task["total_bytes"] = len(img_bytes)
            task["size_kb"] = round(len(img_bytes) / 1024, 1)

    def _execute_video_download(self, task: dict, progress_cb):
        url = task["url"]
        referer = task["referer"]
        target_dir = get_target_directory(referer, url, task["site_title"])
        clean_name = sanitize_filename(task["filename"], "video.mp4")
        base_stem, current_ext = os.path.splitext(clean_name)
        if not current_ext or current_ext.lower() not in VIDEO_EXTENSIONS:
            clean_name = f"{base_stem}.mp4"

        # 1. Try direct HTTP streaming if source_type is 'direct'
        if task["source_type"] == "direct" and not url.lower().endswith((".m3u8", ".mpd")):
            headers = {"Accept": "*/*"}
            if referer:
                headers["Referer"] = referer
            resp = None
            try:
                resp = scraper_session.get(url, headers=headers, timeout=30, stream=True)
                resp.raise_for_status()
                ctype = (resp.headers.get("Content-Type") or "").lower()
                # Verify it's not an HTML webpage pretending to be a direct video link
                if "text/html" not in ctype:
                    total_len = int(resp.headers.get("Content-Length") or 0)
                    save_path = get_unique_filepath(target_dir, clean_name)
                    downloaded = 0
                    with open(save_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=131072):
                            if task["cancel_requested"]:
                                f.close()
                                save_path.unlink(missing_ok=True)
                                raise RuntimeError("İndirme iptal edildi.")
                            if not chunk:
                                continue
                            f.write(chunk)
                            downloaded += len(chunk)
                            progress_cb(downloaded, total_len)

                    if downloaded > 512:
                        with self.lock:
                            task["filename"] = save_path.name
                            task["saved_path"] = str(save_path)
                            task["downloaded_bytes"] = downloaded
                            task["total_bytes"] = downloaded
                            task["size_kb"] = round(downloaded / 1024, 1)
                        return
                    else:
                        save_path.unlink(missing_ok=True)
            except RuntimeError:
                raise
            except Exception:
                pass
            finally:
                if resp:
                    resp.close()

        # 2. Use yt-dlp for streaming (.m3u8), embedded players, YouTube/Vimeo/Twitter/etc., or fallback
        self._download_with_ytdlp(task, target_dir, base_stem, progress_cb)

    def _download_with_ytdlp(self, task: dict, target_dir: Path, base_stem: str, progress_cb):
        import yt_dlp

        out_tmpl = str(target_dir / f"{base_stem}_%(id)s.%(ext)s")
        final_saved_path = [None]

        def ytdlp_hook(d):
            if task["cancel_requested"]:
                raise RuntimeError("İndirme kullanıcı tarafından iptal edildi.")
            if d.get("status") == "downloading":
                dl_bytes = int(d.get("downloaded_bytes") or 0)
                tot_bytes = int(d.get("total_bytes") or d.get("total_bytes_estimate") or 0)
                progress_cb(dl_bytes, tot_bytes)
            elif d.get("status") == "finished":
                final_saved_path[0] = d.get("filename")

        ydl_opts = {
            "outtmpl": out_tmpl,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "progress_hooks": [ytdlp_hook],
            "http_headers": {
                "User-Agent": scraper_session.headers.get("User-Agent", ""),
                "Referer": task["referer"] or task["url"],
            },
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(task["url"], download=True)
            if not final_saved_path[0] and info:
                final_saved_path[0] = ydl.prepare_filename(info)

        saved_p = Path(final_saved_path[0]) if final_saved_path[0] else None
        if not saved_p or not saved_p.exists():
            # Fallback: look for the most recently modified file matching base_stem in target_dir
            candidates = sorted(target_dir.glob(f"{base_stem}*"), key=lambda p: p.stat().st_mtime, reverse=True)
            if candidates:
                saved_p = candidates[0]

        if not saved_p or not saved_p.exists():
            raise ValueError("Video akışı indirilemedi.")

        fsize = saved_p.stat().st_size
        with self.lock:
            task["filename"] = saved_p.name
            task["saved_path"] = str(saved_p)
            task["downloaded_bytes"] = fsize
            task["total_bytes"] = fsize
            task["size_kb"] = round(fsize / 1024, 1)

    def _execute_text_download(self, task: dict):
        target_dir = get_target_directory(task["referer"], task["url"], task["site_title"])
        clean_name = sanitize_filename(task["filename"], "metin.txt")
        if not clean_name.lower().endswith(".txt"):
            clean_name = f"{os.path.splitext(clean_name)[0]}.txt"

        formatted = format_text_with_links_for_txt(
            title=task.get("text_title") or clean_name,
            source_url=task["url"] or task["referer"],
            text_body=task["text_content"],
            links=task.get("links_list") or [],
            include_links=bool(task.get("include_links", True)),
        )
        encoded = formatted.encode("utf-8")
        save_path = get_unique_filepath(target_dir, clean_name)
        with open(save_path, "wb") as f:
            f.write(encoded)

        with self.lock:
            task["filename"] = save_path.name
            task["saved_path"] = str(save_path)
            task["downloaded_bytes"] = len(encoded)
            task["total_bytes"] = len(encoded)
            task["size_kb"] = round(len(encoded) / 1024, 1)

    def _execute_link_txt_download(self, task: dict, progress_cb):
        """Fetches a target link's webpage, extracts its readable text & links, and saves as .txt."""
        url = task["url"]
        referer = task["referer"]
        headers = {"Referer": referer} if referer else {}
        resp = scraper_session.get(url, headers=headers, timeout=25)
        resp.raise_for_status()

        final_u = str(resp.url)
        ctype = (resp.headers.get("Content-Type") or "").lower()
        target_dir = get_target_directory(referer, final_u, task["site_title"])

        if "text/plain" in ctype:
            raw_text = resp.text
            page_title = unquote(urlparse(final_u).path.split("/")[-1]) or "baglanti_metni"
            links = []
        else:
            soup = BeautifulSoup(resp.text, "lxml")
            page_title = (
                soup.title.string.strip()
                if soup.title and soup.title.string
                else urlparse(final_u).netloc
            )
            texts_list, links = extract_texts_and_links(soup, final_u, page_title)
            raw_text = texts_list[0]["text"] if texts_list else soup.get_text("\n", strip=True)

        clean_name = sanitize_filename(task["filename"] or f"{page_title}.txt", "baglanti_icerigi.txt")
        if not clean_name.lower().endswith(".txt"):
            clean_name = f"{os.path.splitext(clean_name)[0]}.txt"

        formatted = format_text_with_links_for_txt(
            title=page_title,
            source_url=final_u,
            text_body=raw_text,
            links=links,
            include_links=True,
        )
        encoded = formatted.encode("utf-8")
        progress_cb(len(encoded), len(encoded))

        save_path = get_unique_filepath(target_dir, clean_name)
        with open(save_path, "wb") as f:
            f.write(encoded)

        with self.lock:
            task["filename"] = save_path.name
            task["saved_path"] = str(save_path)
            task["downloaded_bytes"] = len(encoded)
            task["total_bytes"] = len(encoded)
            task["size_kb"] = round(len(encoded) / 1024, 1)

    def _execute_link_content_download(self, task: dict, progress_cb):
        """
        Smart downloader for any hyperlink ('Linkin İçeriğini İndir'):
        - If the link is a known video platform URL -> downloads video via yt-dlp.
        - If the link is a known image host / direct image -> downloads full-res image.
        - If the link responds with binary/file/archive/PDF/audio/video -> streams file to disk.
        - If the link responds with an HTML article/webpage -> extracts its full text + links and saves as .txt.
        """
        url = task["url"]
        referer = task["referer"]

        is_vid, vid_type = is_likely_video_url(url)
        if is_vid:
            task["source_type"] = vid_type
            self._execute_video_download(task, progress_cb)
            return

        parsed_host = urlparse(url).netloc.lower()
        if any(d in parsed_host for d in KNOWN_IMAGE_HOST_DOMAINS):
            self._execute_image_download(task, progress_cb)
            return

        headers = {"Referer": referer} if referer else {}
        resp = scraper_session.get(url, headers=headers, timeout=30, stream=True)
        resp.raise_for_status()

        final_u = str(resp.url)
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        total_len = int(resp.headers.get("Content-Length") or 0)
        content_disp = resp.headers.get("Content-Disposition") or ""

        # Check if response is an image
        if ctype.startswith("image/"):
            resp.close()
            self._execute_image_download(task, progress_cb)
            return

        # Check if response is an HTML page
        if "text/html" in ctype:
            html_bytes = resp.content
            resp.close()
            html_str = html_bytes.decode(resp.encoding or "utf-8", errors="replace")

            # Check if it's an image viewer page with an og:image or main image if URL looked like an image viewer
            soup = BeautifulSoup(html_str, "lxml")
            page_title = (
                soup.title.string.strip()
                if soup.title and soup.title.string
                else urlparse(final_u).netloc
            )
            texts_list, links = extract_texts_and_links(soup, final_u, page_title)
            raw_text = texts_list[0]["text"] if texts_list else soup.get_text("\n", strip=True)

            target_dir = get_target_directory(referer, final_u, task["site_title"])
            clean_name = sanitize_filename(f"{page_title}.txt", "baglanti_metni.txt")
            if not clean_name.lower().endswith(".txt"):
                clean_name = f"{os.path.splitext(clean_name)[0]}.txt"

            formatted = format_text_with_links_for_txt(
                title=page_title,
                source_url=final_u,
                text_body=raw_text,
                links=links,
                include_links=True,
            )
            encoded = formatted.encode("utf-8")
            progress_cb(len(encoded), len(encoded))

            save_path = get_unique_filepath(target_dir, clean_name)
            with open(save_path, "wb") as f:
                f.write(encoded)

            with self.lock:
                task["filename"] = save_path.name
                task["saved_path"] = str(save_path)
                task["downloaded_bytes"] = len(encoded)
                task["total_bytes"] = len(encoded)
                task["size_kb"] = round(len(encoded) / 1024, 1)
            return

        # Otherwise, stream binary file (video, archive, PDF, document, audio, etc.)
        filename_from_cd = ""
        m_cd = re.search(r'filename\*?=["\']?(?:UTF-8\'\')?([^"\';\r\n]+)', content_disp, re.IGNORECASE)
        if m_cd:
            filename_from_cd = unquote(m_cd.group(1).strip())

        url_basename = unquote(urlparse(final_u).path.rstrip("/").split("/")[-1])
        chosen_name = sanitize_filename(filename_from_cd or url_basename or task["filename"], "indirilen_dosya")
        base_stem, ext = os.path.splitext(chosen_name)
        if not ext:
            ext = MIME_TO_EXT.get(ctype, ".bin")
            chosen_name = f"{base_stem}{ext}"

        target_dir = get_target_directory(referer, final_u, task["site_title"])
        save_path = get_unique_filepath(target_dir, chosen_name)
        downloaded = 0
        try:
            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=131072):
                    if task["cancel_requested"]:
                        f.close()
                        save_path.unlink(missing_ok=True)
                        raise RuntimeError("İndirme iptal edildi.")
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    progress_cb(downloaded, total_len)
        finally:
            resp.close()

        with self.lock:
            task["filename"] = save_path.name
            task["saved_path"] = str(save_path)
            task["downloaded_bytes"] = downloaded
            task["total_bytes"] = downloaded
            task["size_kb"] = round(downloaded / 1024, 1)


queue_manager = DownloadQueueManager()


# ==============================================================================
# FLASK ROUTES
# ==============================================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    global config
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        if "download_dir" in body and body["download_dir"]:
            config["download_dir"] = str(body["download_dir"])
            os.makedirs(config["download_dir"], exist_ok=True)
        if "min_size" in body:
            config["min_size"] = int(body["min_size"])
        if "create_site_subfolder" in body:
            config["create_site_subfolder"] = bool(body["create_site_subfolder"])
        if "large_file_threshold_mb" in body:
            config["large_file_threshold_mb"] = max(1, int(body["large_file_threshold_mb"]))
        if "include_links_in_txt" in body:
            config["include_links_in_txt"] = bool(body["include_links_in_txt"])
        save_config(config)
    return jsonify(config)


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    global current_scrape_epoch
    body = request.get_json(silent=True) or {}
    target_url = (body.get("url") or "").strip()
    referer = (body.get("referer") or "").strip()
    append_mode = bool(body.get("append", False))
    if not target_url:
        return jsonify({"error": "Lütfen geçerli bir web sitesi adresi girin."}), 400

    if not append_mode:
        current_scrape_epoch += 1

    try:
        result = scrape_page(target_url, session=page_scraper_session, referer=referer)
        result["scrape_epoch"] = current_scrape_epoch
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": f"Sayfa taranırken hata oluştu: {str(exc)}"}), 500


@app.route("/api/proxy")
def api_proxy():
    img_url = request.args.get("url", "").strip()
    referer = request.args.get("referer", "").strip()
    fallback_thumb = request.args.get("thumb", "").strip()
    sid_raw = request.args.get("sid", "").strip()
    if not img_url:
        return "Missing URL", 400

    # Check if this thumbnail request belongs to an older page navigation and should be dropped immediately
    if sid_raw.isdigit():
        sid = int(sid_raw)
        if 0 < sid < current_scrape_epoch:
            return Response(b"", status=204)

    # Check in-memory LRU cache first
    with PROXY_CACHE_LOCK:
        cached = PROXY_CACHE.get(img_url)
        if cached:
            PROXY_CACHE.move_to_end(img_url)
            cached_bytes, cached_mime = cached
            return Response(
                cached_bytes,
                status=200,
                headers={
                    "Content-Type": cached_mime,
                    "Cache-Control": "public, max-age=3600",
                },
            )

    try:
        img_bytes, _, mime = fetch_valid_image(
            img_url,
            referer=referer,
            fallback_thumb_url=fallback_thumb,
            is_proxy=True,
        )
        out_mime = mime or "image/jpeg"
        if len(img_bytes) <= 2 * 1024 * 1024:
            with PROXY_CACHE_LOCK:
                PROXY_CACHE[img_url] = (img_bytes, out_mime)
                PROXY_CACHE.move_to_end(img_url)
                while len(PROXY_CACHE) > PROXY_CACHE_MAX:
                    PROXY_CACHE.popitem(last=False)

        return Response(
            img_bytes,
            status=200,
            headers={
                "Content-Type": out_mime,
                "Cache-Control": "public, max-age=3600",
            },
        )
    except Exception as exc:
        return f"Proxy error: {exc}", 502


@app.route("/api/video-proxy")
def api_video_proxy():
    """Streams direct video bytes for preview playback inside the Lightbox."""
    video_url = request.args.get("url", "").strip()
    referer = request.args.get("referer", "").strip()
    if not video_url:
        return "Missing video URL", 400

    headers = {"Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    if "Range" in request.headers:
        headers["Range"] = request.headers["Range"]

    try:
        resp = scraper_session.get(video_url, headers=headers, timeout=25, stream=True)
        resp_headers = {
            "Content-Type": resp.headers.get("Content-Type", "video/mp4"),
            "Accept-Ranges": "bytes",
        }
        if "Content-Length" in resp.headers:
            resp_headers["Content-Length"] = resp.headers["Content-Length"]
        if "Content-Range" in resp.headers:
            resp_headers["Content-Range"] = resp.headers["Content-Range"]

        def generate():
            try:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        yield chunk
            finally:
                resp.close()

        return Response(generate(), status=resp.status_code, headers=resp_headers)
    except Exception as exc:
        return f"Video proxy error: {exc}", 502


@app.route("/api/queue/add", methods=["POST"])
def api_queue_add():
    """Adds one or more items (image, video, text, link_txt, link_content) to the smart download queue."""
    body = request.get_json(silent=True) or {}
    items = body.get("items")
    if not items and body.get("url") or body.get("text_content"):
        items = [body]
    if not items or not isinstance(items, list):
        return jsonify({"error": "İndirilecek öğe bulunamadı."}), 400

    created_tasks = queue_manager.add_tasks(items)
    return jsonify({
        "success": True,
        "added_count": len(created_tasks),
        "tasks": created_tasks,
    })


@app.route("/api/queue/status", methods=["GET"])
def api_queue_status():
    return jsonify(queue_manager.get_status_snapshot())


@app.route("/api/queue/cancel", methods=["POST"])
def api_queue_cancel():
    body = request.get_json(silent=True) or {}
    task_id = body.get("task_id") or "all"
    queue_manager.cancel_task(task_id)
    return jsonify({"success": True})


@app.route("/api/queue/clear", methods=["POST"])
def api_queue_clear():
    queue_manager.clear_finished()
    return jsonify({"success": True})


@app.route("/api/download", methods=["POST"])
def api_download():
    """Direct synchronous download endpoint kept for backwards compatibility."""
    body = request.get_json(silent=True) or {}
    img_url = (body.get("url") or "").strip()
    thumb_url = (body.get("thumb_url") or "").strip()
    referer = (body.get("referer") or "").strip()
    raw_filename = (body.get("filename") or "image.jpg").strip()
    site_title = (body.get("site_title") or "").strip()

    if not img_url:
        return jsonify({"error": "Görsel URL'si bulunamadı."}), 400

    try:
        img_bytes, detected_ext, _ = fetch_valid_image(
            img_url, referer=referer, fallback_thumb_url=thumb_url
        )

        clean_name = sanitize_filename(raw_filename, "gorsel.jpg")
        base_stem, current_ext = os.path.splitext(clean_name)
        if detected_ext:
            clean_name = f"{base_stem}{detected_ext}"
        elif not current_ext:
            clean_name = f"{base_stem}.jpg"

        target_dir = get_target_directory(referer, img_url, site_title)
        save_path = get_unique_filepath(target_dir, clean_name)
        with open(save_path, "wb") as f:
            f.write(img_bytes)

        size_kb = round(len(img_bytes) / 1024, 1)
        return jsonify(
            {
                "success": True,
                "filename": save_path.name,
                "saved_path": str(save_path),
                "size_kb": size_kb,
            }
        )
    except Exception as exc:
        return jsonify({"error": f"İndirme başarısız: {str(exc)}"}), 500


@app.route("/api/pick-folder", methods=["POST"])
def api_pick_folder():
    global config
    selected_dir = None
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(initialdir=config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
        root.destroy()
        if chosen:
            selected_dir = os.path.normpath(chosen)
    except Exception:
        pass

    if selected_dir:
        config["download_dir"] = selected_dir
        os.makedirs(selected_dir, exist_ok=True)
        save_config(config)

    return jsonify({"download_dir": config["download_dir"], "changed": bool(selected_dir)})


@app.route("/api/open-folder", methods=["POST"])
def api_open_folder():
    body = request.get_json(silent=True) or {}
    file_path = body.get("path")
    target = Path(file_path) if file_path else Path(config.get("download_dir", DEFAULT_DOWNLOAD_DIR))

    try:
        if target.exists() and target.is_file():
            subprocess.Popen(["explorer", "/select,", str(target)])
        else:
            folder = target if target.exists() else Path(config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ==============================================================================
# GITHUB AUTO-UPDATER (GIT PULL + ZIP FALLBACK + AUTO RESTART)
# ==============================================================================

GITHUB_REPO = "yogruce/threadsnap"
GITHUB_BRANCH = "main"
GITHUB_ZIP_URL = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/{GITHUB_BRANCH}.zip"
GITHUB_API_COMMIT_URL = f"https://api.github.com/repos/{GITHUB_REPO}/commits/{GITHUB_BRANCH}"
VERSION_FILE = BASE_DIR / ".version_sha"
NO_WINDOW_FLAG = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run_git(args: list, timeout: int = 20) -> tuple[bool, str]:
    try:
        res = subprocess.run(
            ["git"] + args,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=NO_WINDOW_FLAG,
        )
        if res.returncode == 0:
            return True, (res.stdout or "").strip()
        return False, (res.stderr or res.stdout or "").strip()
    except Exception as exc:
        return False, str(exc)


def get_local_version_info() -> dict:
    if (BASE_DIR / ".git").exists():
        ok, sha = _run_git(["rev-parse", "--short", "HEAD"])
        ok_msg, msg = _run_git(["log", "-1", "--pretty=format:%s (%cr)"])
        if ok and sha:
            return {"commit": sha, "last_message": msg if ok_msg else "", "method": "git"}

    if VERSION_FILE.exists():
        try:
            sha = VERSION_FILE.read_text(encoding="utf-8").strip()[:7]
            return {"commit": sha, "last_message": "ZIP Kurulumu", "method": "zip"}
        except Exception:
            pass
    return {"commit": "Bilinmiyor", "last_message": "", "method": "zip"}


@app.route("/api/update/check", methods=["POST", "GET"])
def api_update_check():
    """Checks GitHub repository for new commits/updates."""
    local_info = get_local_version_info()

    # 1. Try via Git CLI if .git exists
    if (BASE_DIR / ".git").exists():
        ok_fetch, fetch_err = _run_git(["fetch", "origin", GITHUB_BRANCH], timeout=25)
        if ok_fetch:
            _, local_sha = _run_git(["rev-parse", "--short", "HEAD"])
            _, remote_sha = _run_git(["rev-parse", "--short", f"origin/{GITHUB_BRANCH}"])
            ok_cnt, behind_str = _run_git(["rev-list", f"HEAD..origin/{GITHUB_BRANCH}", "--count"])
            behind_count = int(behind_str) if (ok_cnt and behind_str.isdigit()) else 0

            changelog = []
            if behind_count > 0:
                ok_log, log_out = _run_git([
                    "log", f"HEAD..origin/{GITHUB_BRANCH}", "--pretty=format:%h — %s (%cr)", "-n", "15"
                ])
                if ok_log and log_out:
                    changelog = [line.strip() for line in log_out.splitlines() if line.strip()]
            else:
                ok_last, last_out = _run_git(["log", "-1", "--pretty=format:%h — %s (%cr)"])
                if ok_last and last_out:
                    changelog = [f"Güncel Sürüm: {last_out}"]

            return jsonify({
                "success": True,
                "repo": GITHUB_REPO,
                "branch": GITHUB_BRANCH,
                "local_commit": local_sha or local_info["commit"],
                "remote_commit": remote_sha or local_sha,
                "has_update": behind_count > 0 and (local_sha != remote_sha),
                "behind_count": behind_count,
                "changelog": changelog,
                "method": "git",
            })

    # 2. Fallback: Check via GitHub REST API
    try:
        resp = scraper_session.get(
            GITHUB_API_COMMIT_URL,
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        remote_full_sha = data.get("sha") or ""
        remote_sha = remote_full_sha[:7]
        commit_msg = (data.get("commit", {}).get("message") or "").splitlines()[0]
        commit_date = data.get("commit", {}).get("committer", {}).get("date") or ""

        local_sha = local_info["commit"]
        has_update = bool(remote_sha and local_sha != remote_sha)

        return jsonify({
            "success": True,
            "repo": GITHUB_REPO,
            "branch": GITHUB_BRANCH,
            "local_commit": local_sha,
            "remote_commit": remote_sha,
            "has_update": has_update,
            "behind_count": 1 if has_update else 0,
            "changelog": [f"{remote_sha} — {commit_msg} ({commit_date[:10]})"],
            "method": "zip",
        })
    except Exception as exc:
        return jsonify({
            "success": False,
            "error": f"GitHub bağlantı hatası: {str(exc)}",
            "local_commit": local_info["commit"],
        }), 500


@app.route("/api/update/apply", methods=["POST"])
def api_update_apply():
    """Pulls the latest code from GitHub (via git or ZIP archive), updates requirements, and preserves config.json."""
    saved_cfg = load_config()
    updated_files = []
    new_commit = ""

    try:
        used_git = False
        if (BASE_DIR / ".git").exists():
            ok_fetch, _ = _run_git(["fetch", "origin", GITHUB_BRANCH], timeout=30)
            if ok_fetch:
                ok_reset, _ = _run_git(["reset", "--hard", f"origin/{GITHUB_BRANCH}"], timeout=20)
                if ok_reset:
                    used_git = True
                    _, new_commit = _run_git(["rev-parse", "--short", "HEAD"])

        if not used_git:
            # Fallback: Download ZIP archive directly from GitHub
            resp = scraper_session.get(GITHUB_ZIP_URL, timeout=40)
            resp.raise_for_status()

            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                namelist = zf.namelist()
                root_prefix = namelist[0].split("/")[0] + "/" if namelist else ""
                for member in namelist:
                    if not member.startswith(root_prefix):
                        continue
                    rel_path = member[len(root_prefix):]
                    if not rel_path or rel_path.endswith("/"):
                        continue
                    # Never overwrite user config or logs
                    if rel_path in ("config.json", "app.log") or rel_path.startswith(".git/"):
                        continue

                    dest_path = BASE_DIR / rel_path
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src_f, open(dest_path, "wb") as dst_f:
                        dst_f.write(src_f.read())
                    updated_files.append(rel_path)

            # Record latest SHA if possible
            try:
                api_resp = scraper_session.get(GITHUB_API_COMMIT_URL, timeout=10)
                if api_resp.ok:
                    new_commit = (api_resp.json().get("sha") or "")[:7]
                    if new_commit:
                        VERSION_FILE.write_text(new_commit, encoding="utf-8")
            except Exception:
                pass

        # Restore user's config.json
        save_config(saved_cfg)

        # Install / update dependencies in requirements.txt quietly
        req_file = BASE_DIR / "requirements.txt"
        if req_file.exists():
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-r", str(req_file), "--quiet"],
                    cwd=str(BASE_DIR),
                    timeout=90,
                    creationflags=NO_WINDOW_FLAG,
                )
            except Exception:
                pass

        return jsonify({
            "success": True,
            "new_commit": new_commit or "Güncel",
            "method": "git" if used_git else "zip",
            "message": "GitHub üzerinden en güncel sürüm başarıyla indirildi ve uygulandı!",
        })
    except Exception as exc:
        save_config(saved_cfg)
        return jsonify({"success": False, "error": f"Güncelleme başarısız: {str(exc)}"}), 500


@app.route("/api/update/restart", methods=["POST"])
def api_update_restart():
    """Restarts the application process so updated Python & UI files take effect immediately."""
    def _delayed_restart():
        time.sleep(0.7)
        try:
            python_exe = sys.executable
            subprocess.Popen(
                [python_exe, str(BASE_DIR / "app.py")],
                cwd=str(BASE_DIR),
            )
        finally:
            os._exit(0)

    threading.Thread(target=_delayed_restart, daemon=True).start()
    return jsonify({"success": True, "message": "Uygulama yeniden başlatılıyor..."})


def find_free_port(default_port=5482):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", default_port)) != 0:
            return default_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_flask(port: int):
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True, use_reloader=False)


def launch_desktop_window(url: str):
    from PyQt6.QtCore import QUrl, QObject, QTimer, pyqtSignal, Qt
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from PyQt6.QtWebEngineCore import QWebEngineProfile
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Medya, Video, Metin & Forum İndirici")

    # Persist browser cookies (including cf_clearance) across runs
    profile_dir = BASE_DIR / ".browser_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    default_profile = QWebEngineProfile.defaultProfile()
    default_profile.setPersistentStoragePath(str(profile_dir))
    default_profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)

    captured_cookies = {}

    def _on_cookie_added(cookie):
        try:
            name = bytes(cookie.name()).decode("utf-8", errors="ignore")
            val = bytes(cookie.value()).decode("utf-8", errors="ignore")
            domain = cookie.domain().lstrip(".")
            if name and val:
                captured_cookies[name] = val
                try:
                    page_scraper_session.cookies.set(name, val, domain=domain)
                    scraper_session.cookies.set(name, val, domain=domain)
                except Exception:
                    pass
        except Exception:
            pass

    default_profile.cookieStore().cookieAdded.connect(_on_cookie_added)

    main_win = QMainWindow()
    main_win.setWindowTitle("ImgCatcher Pro — Görsel, Video, Metin & Link İndirici")
    main_win.resize(1340, 860)
    main_win.setMinimumSize(960, 640)
    main_win.setStyleSheet("background-color: #0f172a;")

    class CloudflareSolverBridge(QObject):
        solve_requested = pyqtSignal(str, str, object)

        def __init__(self, parent=None):
            super().__init__(parent)
            self.solve_requested.connect(self._handle_solve_on_main_thread)

        def _handle_solve_on_main_thread(self, target_url: str, referer: str, state_box: dict):
            cf_win = QMainWindow(main_win)
            cf_win.setWindowTitle("Cloudflare Güvenlik Doğrulaması Geçiliyor...")
            cf_win.resize(900, 620)
            cf_win.setStyleSheet("background-color: #0f172a;")

            cf_view = QWebEngineView(cf_win)
            cf_win.setCentralWidget(cf_view)

            poll_timer = QTimer(cf_win)
            poll_timer.setInterval(700)
            start_ts = time.time()
            finished_flag = [False]

            def finish_with(html_str: str):
                if finished_flag[0]:
                    return
                finished_flag[0] = True
                poll_timer.stop()
                state_box["html"] = html_str.encode("utf-8", errors="replace") if html_str else b""
                state_box["final_url"] = cf_view.url().toString() or target_url
                state_box["cookies"] = dict(captured_cookies)
                cf_win.close()
                cf_win.deleteLater()
                state_box["event"].set()

            def check_html(html_str: str):
                if finished_flag[0]:
                    return
                raw_b = (html_str or "").encode("utf-8", errors="replace")
                elapsed = time.time() - start_ts
                if len(raw_b) > 600 and not is_cloudflare_challenge(200, raw_b):
                    finish_with(html_str)
                elif elapsed > 2.5 and not cf_win.isVisible():
                    # Show window if interactive Turnstile challenge requires visual rendering or click
                    cf_win.show()
                    cf_win.raise_()
                    cf_win.activateWindow()
                elif elapsed > 28.0:
                    finish_with(html_str)

            def on_poll():
                if finished_flag[0]:
                    return
                cf_view.page().toHtml(check_html)

            poll_timer.timeout.connect(on_poll)
            cf_view.loadFinished.connect(lambda _: on_poll())
            poll_timer.start()
            cf_view.setUrl(QUrl(target_url))

    cf_bridge = CloudflareSolverBridge(main_win)

    def fetch_via_qt_browser(target_url: str, referer: str = "") -> dict | None:
        state_box = {"event": threading.Event(), "html": b"", "final_url": target_url, "cookies": {}}
        cf_bridge.solve_requested.emit(target_url, referer, state_box)
        state_box["event"].wait(timeout=30.0)
        if state_box["html"]:
            return state_box
        return None

    register_browser_fetcher(fetch_via_qt_browser)

    browser = QWebEngineView(main_win)
    browser.page().setBackgroundColor(QColor("#0f172a"))
    browser.setUrl(QUrl(url))
    main_win.setCentralWidget(browser)

    main_win.show()
    main_win.raise_()
    main_win.activateWindow()
    sys.exit(qt_app.exec())


if __name__ == "__main__":
    port = find_free_port()
    server_thread = threading.Thread(target=start_flask, args=(port,), daemon=True)
    server_thread.start()

    url = f"http://127.0.0.1:{port}"
    if "--headless-test" in sys.argv:
        print(f"Server started on {url}")
        server_thread.join()
    else:
        launch_desktop_window(url)

import os
import re
import io
import sys
import json
import base64
import socket
import threading
import subprocess
from pathlib import Path
from urllib.parse import urlparse
from flask import Flask, render_template, request, jsonify, Response
from PIL import Image

from scraper import create_session, scrape_page, extract_real_image_from_viewer_html

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
LOG_PATH = BASE_DIR / "app.log"
DEFAULT_DOWNLOAD_DIR = str(Path.home() / "Downloads" / "ImageDownloader")

# Fix stdout/stderr when running under pythonw.exe so Flask/Werkzeug logging never fails
if sys.stdout is None:
    sys.stdout = open(LOG_PATH, "a", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(LOG_PATH, "a", encoding="utf-8")

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
scraper_session = create_session()
config = load_config()


def sanitize_folder_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" ._")
    return cleaned[:80] if cleaned else "Genel"


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


def fetch_valid_image(target_url: str, referer: str = "", fallback_thumb_url: str = ""):
    """
    Fetches an image from `target_url`.
    1. Handles data:image/... base64 URLs.
    2. If `target_url` returns an HTML viewer page (e.g., pixhost.to/show/..., ibb.co/..., imgbox.com/...),
       automatically parses the viewer page and downloads the embedded full-resolution image.
    3. Validates the image bytes so HTML pages or 0-byte responses are never saved as .jpg.
    4. Falls back to `fallback_thumb_url` if `target_url` fails or is invalid.
    Returns (image_bytes, detected_ext, mime_type).
    """
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
                    return raw_bytes, ext, out_mime
            except Exception:
                return None, None, None

        headers = {
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        if ref:
            headers["Referer"] = ref

        try:
            resp = scraper_session.get(url_to_get, headers=headers, timeout=25)
            resp.raise_for_status()
        except Exception:
            # Retry once with the target origin itself as Referer (some image hosts require their own domain as Referer)
            try:
                parsed_u = urlparse(url_to_get)
                self_ref = f"{parsed_u.scheme}://{parsed_u.netloc}/"
                headers["Referer"] = self_ref
                resp = scraper_session.get(url_to_get, headers=headers, timeout=25)
                resp.raise_for_status()
            except Exception:
                return None, None, None

        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()

        # Check if we got a valid image directly
        ok, ext, out_mime = validate_image_bytes(resp.content, ctype)
        if ok:
            return resp.content, ext, out_mime

        # If we received an HTML page (viewer page), extract the real image URL from inside it
        if allow_html_resolve and ("text/html" in ctype or resp.content[:100].lstrip().lower().startswith((b"<!doctype", b"<html"))):
            real_img_url = extract_real_image_from_viewer_html(resp.text, str(resp.url))
            if real_img_url and real_img_url != url_to_get:
                return try_single_url(real_img_url, ref=str(resp.url), allow_html_resolve=False)

        return None, None, None

    img_bytes, ext, mime = try_single_url(target_url, referer, allow_html_resolve=True)
    if img_bytes:
        return img_bytes, ext, mime

    # Fallback to thumbnail URL if full_url couldn't be resolved to a valid image
    if fallback_thumb_url and fallback_thumb_url != target_url:
        img_bytes, ext, mime = try_single_url(fallback_thumb_url, referer, allow_html_resolve=False)
        if img_bytes:
            return img_bytes, ext, mime

    raise ValueError("Görsel verisi alınamadı veya hedef adres geçerli bir resim içermiyor.")


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
        save_config(config)
    return jsonify(config)


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    body = request.get_json(silent=True) or {}
    target_url = (body.get("url") or "").strip()
    if not target_url:
        return jsonify({"error": "Lütfen geçerli bir web sitesi adresi girin."}), 400

    try:
        result = scrape_page(target_url, session=scraper_session)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": f"Sayfa taranırken hata oluştu: {str(exc)}"}), 500


@app.route("/api/proxy")
def api_proxy():
    img_url = request.args.get("url", "").strip()
    referer = request.args.get("referer", "").strip()
    fallback_thumb = request.args.get("thumb", "").strip()
    if not img_url:
        return "Missing URL", 400

    try:
        img_bytes, _, mime = fetch_valid_image(img_url, referer=referer, fallback_thumb_url=fallback_thumb)
        return Response(
            img_bytes,
            status=200,
            headers={
                "Content-Type": mime or "image/jpeg",
                "Cache-Control": "public, max-age=3600",
            },
        )
    except Exception as exc:
        return f"Proxy error: {exc}", 502


@app.route("/api/download", methods=["POST"])
def api_download():
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

        clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw_filename).strip(" ._")
        if not clean_name:
            clean_name = "gorsel.jpg"

        base_stem, current_ext = os.path.splitext(clean_name)
        if detected_ext:
            # Always use the verified image format extension so files are never saved with a mismatched extension
            clean_name = f"{base_stem}{detected_ext}"
        elif not current_ext:
            clean_name = f"{base_stem}.jpg"

        target_dir = Path(config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
        if config.get("create_site_subfolder", True):
            domain = urlparse(referer or img_url).netloc.replace("www.", "")
            folder_label = sanitize_folder_name(domain or site_title or "Indirilenler")
            target_dir = target_dir / folder_label

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
    from PyQt6.QtCore import QUrl, Qt
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Görsel Yakalayıcı & Forum İndirici")

    main_win = QMainWindow()
    main_win.setWindowTitle("Görsel Yakalayıcı & Forum İndirici")
    main_win.resize(1280, 840)
    main_win.setMinimumSize(900, 620)
    main_win.setStyleSheet("background-color: #0f172a;")

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

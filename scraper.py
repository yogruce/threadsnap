import os
import re
import json
from urllib.parse import urljoin, urlparse, unquote
import requests
import cloudscraper
from bs4 import BeautifulSoup


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

IMAGE_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".svg", ".jfif", ".tiff"
)

VIDEO_EXTENSIONS = (
    ".mp4", ".webm", ".mkv", ".mov", ".avi", ".flv", ".m4v", ".m3u8", ".ts", ".ogv", ".3gp", ".wmv"
)

FILE_ARCHIVE_EXTENSIONS = (
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
    ".pdf", ".epub", ".mobi", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".csv", ".json", ".xml", ".apk", ".exe", ".msi", ".dmg", ".iso", ".torrent",
    ".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac"
)

ATTACHMENT_PATTERNS = re.compile(
    r"(/attachments/[^/?#]+|attachment\.php\?.*attachmentid=|\baction=dlattach\b|/uploads/[^/?#]+)",
    re.IGNORECASE,
)

# Known external image host domains commonly used in forums
KNOWN_IMAGE_HOST_DOMAINS = (
    "pixhost.to",
    "imgbox.com",
    "imagebam.com",
    "ibb.co",
    "imgbb.com",
    "postimg.cc",
    "postimages.org",
    "imx.to",
    "imagetwist.com",
    "vipr.im",
    "turboimagehost.com",
    "acidimg.cc",
    "imgspice.com",
    "fastpic.org",
    "pixl.li",
    "picstate.com",
    "imagevenue.com",
    "imgur.com",
    "flickr.com",
    "wallhaven.cc",
)

# Known video / streaming platforms & video hosts
KNOWN_VIDEO_HOST_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "dailymotion.com",
    "streamable.com",
    "tiktok.com",
    "redgifs.com",
    "gfycat.com",
    "twitch.tv",
    "rumble.com",
    "bitchute.com",
    "odysee.com",
    "vk.com",
    "ok.ru",
    "vidyard.com",
    "wistia.com",
    "loom.com",
    "bunkr.",
    "gofile.io",
    "pixeldrain.com",
    "cyberdrop.",
    "saint2.",
    "streamtape.com",
    "doodstream.",
    "voe.sx",
    "mixdrop.",
    "filemoon.",
)

# Known cloud / file sharing hosts
KNOWN_CLOUD_HOST_DOMAINS = (
    "mega.nz",
    "mega.co.nz",
    "drive.google.com",
    "docs.google.com",
    "mediafire.com",
    "gofile.io",
    "pixeldrain.com",
    "bunkr.",
    "cyberdrop.",
    "1fichier.com",
    "rapidgator.net",
    "turbobit.net",
    "nitroflare.com",
    "katfile.com",
    "uploaded.net",
    "ddownload.com",
    "dropbox.com",
    "onedrive.live.com",
    "yadi.sk",
    "disk.yandex.",
    "wetransfer.com",
    "sendspace.com",
    "zippyshare.com",
    "krakenfiles.com",
    "anonfiles.com",
    "workupload.com",
    "bowfile.com",
    " hexupload.",
)


def create_session():
    """Creates a CloudScraper session with browser-like headers."""
    try:
        session = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
    except Exception:
        session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    return session


def is_likely_image_or_viewer_url(url: str) -> bool:
    """Checks if a URL points to a direct image file, forum attachment, or known image host viewer."""
    if not url or url.startswith(("javascript:", "mailto:", "tel:", "#")):
        return False
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path_lower = parsed.path.lower()

    if any(path_lower.endswith(ext) for ext in IMAGE_EXTENSIONS):
        return True
    if ATTACHMENT_PATTERNS.search(url):
        return True
    if any(d in host for d in KNOWN_IMAGE_HOST_DOMAINS):
        return True

    query_lower = parsed.query.lower()
    if any(ext in query_lower for ext in IMAGE_EXTENSIONS):
        return True
    if re.search(r"(format=(jpg|jpeg|png|webp|gif)|image|img)", query_lower):
        return True
    return False


def is_likely_video_url(url: str) -> tuple[bool, str]:
    """
    Checks if a URL is a direct video file, HLS/DASH stream, or a known video platform URL.
    Returns (is_video: bool, source_type: 'direct' | 'stream' | 'embed' | 'ytdlp' | '').
    """
    if not url or url.startswith(("javascript:", "mailto:", "tel:", "#", "data:")):
        return False, ""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path_lower = parsed.path.lower()
    query_lower = parsed.query.lower()

    if path_lower.endswith((".m3u8", ".mpd")):
        return True, "stream"

    if any(path_lower.endswith(ext) for ext in VIDEO_EXTENSIONS):
        return True, "direct"

    if any(ext in query_lower for ext in (".mp4", ".webm", ".mkv", ".mov", ".m3u8")):
        return True, "direct"

    if "mime=video" in query_lower or "content_type=video" in query_lower:
        return True, "direct"

    # Check known video platforms
    if any(d in host for d in KNOWN_VIDEO_HOST_DOMAINS):
        # Filter out channel/profile/home links on YouTube/Vimeo/etc.
        if "youtube.com" in host:
            if any(p in path_lower for p in ("/watch", "/shorts/", "/embed/", "/v/", "/live/")) or "v=" in query_lower:
                return True, "ytdlp"
            return False, ""
        if "youtu.be" in host and len(path_lower.strip("/")) >= 5:
            return True, "ytdlp"
        if "vimeo.com" in host and re.search(r"/\d+", path_lower):
            return True, "ytdlp"
        if "vk.com" in host and "video" not in path_lower and "video" not in query_lower:
            return False, ""
        if "ok.ru" in host and "video" not in path_lower:
            return False, ""
        return True, "ytdlp"

    if ("twitter.com" in host or "x.com" in host) and "/status/" in path_lower:
        return True, "ytdlp"

    return False, ""


def transform_known_thumb_to_full(thumb_url: str, link_url: str = None) -> str:
    """
    Converts known forum image host thumbnail URLs directly into their full-res direct image URLs
    where deterministic, or returns link_url / thumb_url.
    """
    if not thumb_url:
        return link_url or ""

    # 1. Pixhost.to: https://t10.pixhost.to/thumbs/123/456_pic.jpg -> https://img10.pixhost.to/images/123/456_pic.jpg
    m_pixhost = re.match(r"^https?://t(\d+)\.pixhost\.to/thumbs/(.+)$", thumb_url, re.IGNORECASE)
    if m_pixhost:
        return f"https://img{m_pixhost.group(1)}.pixhost.to/images/{m_pixhost.group(2)}"

    # 2. Imx.to: https://imx.to/u/t/2026/11/05/abc.jpg -> https://imx.to/u/i/2026/11/05/abc.jpg
    if "imx.to/u/t/" in thumb_url:
        return thumb_url.replace("/u/t/", "/u/i/")

    return link_url or thumb_url


def parse_srcset(srcset_val: str, base_url: str):
    """Parses an HTML srcset attribute and returns (smallest_url, largest_url)."""
    if not srcset_val:
        return None, None
    candidates = []
    for part in srcset_val.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        raw_url = tokens[0]
        full_u = urljoin(base_url, raw_url)
        score = 1
        if len(tokens) > 1:
            desc = tokens[1].lower()
            if desc.endswith("w"):
                try:
                    score = int(desc[:-1])
                except ValueError:
                    score = 1
            elif desc.endswith("x"):
                try:
                    score = int(float(desc[:-1]) * 1000)
                except ValueError:
                    score = 1
        candidates.append((score, full_u))
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1], candidates[-1][1]


def extract_best_img_sources(img_tag, base_url: str):
    """
    Given a BeautifulSoup <img> tag, extracts:
    - thumb_url: the preview/thumbnail URL
    - full_url: the full-size original image URL (or image viewer page URL to be resolved on download)
    """
    thumb_candidates = [
        img_tag.get("data-src"),
        img_tag.get("data-lazy-src"),
        img_tag.get("data-original"),
        img_tag.get("data-thumb"),
        img_tag.get("src"),
    ]
    thumb_url = None
    for cand in thumb_candidates:
        if cand and not cand.strip().startswith(("data:image/svg", "data:image/gif")):
            thumb_url = urljoin(base_url, cand.strip())
            break
    if not thumb_url and img_tag.get("src"):
        thumb_url = urljoin(base_url, img_tag.get("src").strip())

    high_res_attrs = [
        img_tag.get("data-full-url"),
        img_tag.get("data-full"),
        img_tag.get("data-zoom-image"),
        img_tag.get("data-large_image"),
        img_tag.get("data-highres"),
        img_tag.get("data-src-full"),
        img_tag.get("data-original"),
    ]
    full_url = None
    for cand in high_res_attrs:
        if cand and not cand.strip().startswith("data:"):
            full_url = urljoin(base_url, cand.strip())
            break

    srcset_str = img_tag.get("data-srcset") or img_tag.get("srcset")
    if srcset_str:
        smallest_src, largest_src = parse_srcset(srcset_str, base_url)
        if not thumb_url and smallest_src:
            thumb_url = smallest_src
        if not full_url and largest_src:
            full_url = largest_src

    parent_picture = img_tag.find_parent("picture")
    if parent_picture:
        for source in parent_picture.find_all("source"):
            s_srcset = source.get("srcset") or source.get("data-srcset")
            if s_srcset:
                _, largest_src = parse_srcset(s_srcset, base_url)
                if largest_src and not full_url:
                    full_url = largest_src
                    break

    parent_a = img_tag.find_parent("a")
    if parent_a:
        href = (parent_a.get("href") or "").strip()
        data_full = (
            parent_a.get("data-src")
            or parent_a.get("data-href")
            or parent_a.get("data-full")
            or parent_a.get("data-lightbox")
            or ""
        ).strip()

        if data_full and not data_full.startswith(("javascript:", "#")):
            candidate_a = urljoin(base_url, data_full)
            if is_likely_image_or_viewer_url(candidate_a):
                full_url = candidate_a

        if href and not href.startswith(("javascript:", "#")):
            candidate_href = urljoin(base_url, href)
            a_classes = " ".join(parent_a.get("class", [])).lower()
            is_lightbox_link = any(
                k in a_classes
                for k in (
                    "lightbox", "lbimage", "js-lbimage", "fancybox", "glightbox",
                    "photoswipe", "attachment", "highslide", "zoom"
                )
            ) or parent_a.get("data-fancybox") is not None or parent_a.get("data-lightbox") is not None

            if is_likely_image_or_viewer_url(candidate_href) or is_lightbox_link:
                full_url = candidate_href

    if not full_url:
        lb_parent = img_tag.find_parent(attrs={"data-src": True})
        if lb_parent and lb_parent is not img_tag:
            cand = lb_parent.get("data-src", "").strip()
            if cand and is_likely_image_or_viewer_url(urljoin(base_url, cand)):
                full_url = urljoin(base_url, cand)

    # Apply direct deterministic upgrades (like pixhost thumbs -> pixhost direct image)
    full_url = transform_known_thumb_to_full(thumb_url, full_url)

    return thumb_url, full_url


def extract_real_image_from_viewer_html(html_text: str, viewer_url: str) -> str:
    """
    When a full_url turns out to be an HTML viewer page (e.g., pixhost.to/show/...,
    ibb.co/..., imgbox.com/..., imagebam.com/view/..., postimg.cc/..., imagetwist, etc.),
    parses the HTML and extracts the direct full-resolution image URL.
    """
    soup = BeautifulSoup(html_text, "lxml")

    # 1. Explicit viewer image selectors used by popular image hosts
    priority_selectors = [
        "img#image",                       # pixhost.to, imgbox
        "img#img",                         # imagevenue
        "img.main-image",                  # imagebam
        "img#main-image",                  # postimg / ibb
        "div#image-viewer-container img",  # ibb.co
        "img.pic",                         # imagetwist / vipr / turboimagehost
        "img.centred",                     # imx.to
        "img.centred_resized",             # imx.to
        "a#download-everywhere",           # postimg direct download link
    ]
    for sel in priority_selectors:
        el = soup.select_one(sel)
        if el:
            src = el.get("src") or el.get("href") or el.get("data-src")
            if src and not src.startswith("data:"):
                return urljoin(viewer_url, src.strip())

    # 2. Check OpenGraph og:image / twitter:image meta tags (reliable on ibb.co, postimg, imgur, imgbox)
    for meta_sel in [
        ('meta', {'property': 'og:image'}),
        ('meta', {'name': 'twitter:image'}),
        ('link', {'rel': 'image_src'}),
    ]:
        tag = soup.find(*meta_sel)
        if tag:
            content = (tag.get("content") or tag.get("href") or "").strip()
            if content and not content.startswith("data:"):
                return urljoin(viewer_url, content)

    # 3. Fallback: Find the most prominent <img> on the page that isn't a logo/icon
    for img in soup.find_all("img", src=True):
        src = img["src"].strip()
        if not src or src.startswith("data:"):
            continue
        low = src.lower()
        if any(skip in low for skip in ("logo", "avatar", "icon", "banner", " loader", "button", " blank", ".svg")):
            continue
        return urljoin(viewer_url, src)

    return None


def extract_filename(url: str, index: int, fallback_url: str = None, default_prefix: str = "gorsel", default_ext: str = ".jpg", allowed_exts=IMAGE_EXTENSIONS) -> str:
    """Extracts a clean filename from a URL."""
    for candidate_url in (url, fallback_url):
        if not candidate_url or candidate_url.startswith("data:"):
            continue
        parsed = urlparse(candidate_url)
        path = unquote(parsed.path).rstrip("/")
        segments = [s for s in path.split("/") if s]
        if not segments:
            continue
        name = segments[-1]
        # Convert XenForo slug like "photo-name-png.48291" -> "photo-name.png"
        xf_match = re.match(r"^(.+)-(jpe?g|png|webp|gif|avif|mp4|webm|mkv|mov)\.\d+$", name, re.IGNORECASE)
        if xf_match:
            name = f"{xf_match.group(1)}.{xf_match.group(2).lower()}"
        if name.lower().endswith(".html") or name.lower().endswith(".htm"):
            name = name[: name.rfind(".")]
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" ._")
        if any(name.lower().endswith(ext) for ext in allowed_exts):
            return name[:120]

    return f"{default_prefix}_{index:03d}{default_ext}"


def extract_video_filename(url: str, index: int, title: str = "") -> str:
    """Extracts a clean filename for a video item."""
    parsed = urlparse(url)
    path = unquote(parsed.path).rstrip("/")
    segments = [s for s in path.split("/") if s]
    detected_ext = ".mp4"
    for ext in VIDEO_EXTENSIONS:
        if path.lower().endswith(ext):
            detected_ext = ".mp4" if ext in (".m3u8", ".ts") else ext
            break

    if title and len(title.strip()) > 2:
        clean_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title.strip()).strip(" ._")
        clean_title = re.sub(r"\s+", " ", clean_title)[:90]
        if clean_title:
            if not any(clean_title.lower().endswith(ext) for ext in VIDEO_EXTENSIONS):
                return f"{clean_title}{detected_ext}"
            return clean_title

    if segments:
        last = segments[-1]
        last_clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", last).strip(" ._")
        if any(last_clean.lower().endswith(ext) for ext in VIDEO_EXTENSIONS):
            if last_clean.lower().endswith((".m3u8", ".ts")):
                last_clean = last_clean[: last_clean.rfind(".")] + ".mp4"
            return last_clean[:110]

    return f"video_{index:03d}{detected_ext}"


def extract_videos_from_soup(soup: BeautifulSoup, final_url: str, page_title: str = "") -> list:
    """
    Extracts all videos from the page:
    - <video> and <source> elements
    - Direct <a href="..."> video links (.mp4, .webm, .mkv, .mov, .m3u8, etc.)
    - Embedded video iframes (YouTube, Vimeo, Dailymotion, Streamable, Redgifs, etc.)
    - OpenGraph og:video / twitter:player:stream meta tags & JSON-LD VideoObject
    """
    videos = []
    seen_urls = set()

    og_image_tag = soup.find("meta", attrs={"property": "og:image"}) or soup.find("meta", attrs={"name": "twitter:image"})
    default_poster = urljoin(final_url, og_image_tag["content"].strip()) if (og_image_tag and og_image_tag.get("content")) else ""

    def add_video(video_url: str, thumb_url: str = "", title: str = "", source_type: str = "direct", width: int = 0, height: int = 0):
        if not video_url or video_url.startswith(("javascript:", "mailto:", "#", "data:")):
            return
        full_v = urljoin(final_url, video_url.strip())
        norm_u = full_v.split("#")[0]
        if norm_u in seen_urls:
            return
        seen_urls.add(norm_u)

        parsed = urlparse(full_v)
        host = parsed.netloc.lower().replace("www.", "")
        path_low = parsed.path.lower()

        ext = ".mp4"
        for v_ext in VIDEO_EXTENSIONS:
            if path_low.endswith(v_ext):
                ext = v_ext
                break

        if source_type == "direct" and ext in (".m3u8", ".ts"):
            source_type = "stream"

        idx = len(videos) + 1
        clean_title = (title or "").strip()
        if not clean_title:
            clean_title = f"{page_title} - Video #{idx}" if page_title else f"Video #{idx}"

        fname = extract_video_filename(full_v, idx, clean_title)
        thumb_full = urljoin(final_url, thumb_url.strip()) if thumb_url and not thumb_url.startswith("data:") else default_poster

        videos.append({
            "id": idx,
            "video_url": full_v,
            "thumb_url": thumb_full,
            "title": clean_title[:140],
            "filename": fname,
            "ext": ext,
            "source_type": source_type,  # "direct" | "stream" | "embed" | "ytdlp"
            "host": host,
            "width": width,
            "height": height,
        })

    # 1. Check if the current page URL itself is a known video platform watch URL (e.g. YouTube, Vimeo, Twitter video, etc.)
    is_page_vid, page_vid_type = is_likely_video_url(final_url)
    if is_page_vid:
        add_video(final_url, default_poster, page_title, source_type=page_vid_type)

    # 2. HTML5 <video> tags
    for v_tag in soup.find_all("video"):
        poster = v_tag.get("poster") or v_tag.get("data-poster") or ""
        w = int(re.sub(r"[^\d]", "", str(v_tag.get("width") or 0)) or 0)
        h = int(re.sub(r"[^\d]", "", str(v_tag.get("height") or 0)) or 0)
        v_title = v_tag.get("title") or v_tag.get("aria-label") or v_tag.get("data-title") or ""

        v_srcs = [
            v_tag.get("src"),
            v_tag.get("data-src"),
            v_tag.get("data-video"),
            v_tag.get("data-mp4"),
        ]
        for s in v_srcs:
            if s:
                add_video(s, poster, v_title, source_type="direct", width=w, height=h)

        for src_tag in v_tag.find_all("source"):
            s_url = src_tag.get("src") or src_tag.get("data-src")
            s_type = (src_tag.get("type") or "").lower()
            s_label = src_tag.get("label") or src_tag.get("res") or v_title
            if s_url:
                st = "stream" if ("mpegurl" in s_type or ".m3u8" in s_url.lower()) else "direct"
                add_video(s_url, poster, s_label, source_type=st, width=w, height=h)

    # 3. <iframe> and <embed> video players
    for iframe in soup.find_all(["iframe", "embed"]):
        i_src = iframe.get("src") or iframe.get("data-src") or iframe.get("data-lazy-src") or ""
        if not i_src or i_src.startswith(("javascript:", "about:", "data:")):
            continue
        full_i = urljoin(final_url, i_src.strip())
        i_title = iframe.get("title") or iframe.get("aria-label") or ""
        is_vid, v_type = is_likely_video_url(full_i)
        if is_vid or any(k in full_i.lower() for k in ("/embed/", "player.vimeo", "youtube.com/embed", "youtube-nocookie.com/embed", "dailymotion.com/embed", "redgifs.com/ifr", "streamable.com/e/")):
            add_video(full_i, default_poster, i_title or f"Gömülü Video ({urlparse(full_i).netloc})", source_type="embed")

    # 4. <a href="..."> links pointing to video files or video platforms
    for a_tag in soup.find_all("a", href=True):
        href = a_tag.get("href", "").strip()
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue
        full_href = urljoin(final_url, href)
        is_vid, v_type = is_likely_video_url(full_href)
        if is_vid:
            a_text = a_tag.get_text(" ", strip=True) or a_tag.get("title") or ""
            # Check if there's an <img> inside the <a> for thumbnail
            inner_img = a_tag.find("img")
            thumb = ""
            if inner_img:
                thumb = inner_img.get("data-src") or inner_img.get("src") or ""
            add_video(full_href, thumb, a_text, source_type=v_type)

    # 5. OpenGraph & Twitter video meta tags
    for meta_prop in ("og:video:secure_url", "og:video:url", "og:video", "twitter:player:stream"):
        m_tag = soup.find("meta", attrs={"property": meta_prop}) or soup.find("meta", attrs={"name": meta_prop})
        if m_tag and m_tag.get("content"):
            m_url = urljoin(final_url, m_tag["content"].strip())
            is_vid, v_type = is_likely_video_url(m_url)
            add_video(m_url, default_poster, page_title, source_type=v_type or "direct")

    # 6. JSON-LD VideoObject
    for script_tag in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        raw_json = script_tag.string or script_tag.get_text()
        if not raw_json:
            continue
        try:
            parsed_ld = json.loads(raw_json)
            items = parsed_ld if isinstance(parsed_ld, list) else [parsed_ld]
            for obj in items:
                if not isinstance(obj, dict):
                    continue
                graph = obj.get("@graph", [obj])
                for node in (graph if isinstance(graph, list) else [graph]):
                    if isinstance(node, dict) and "VideoObject" in str(node.get("@type", "")):
                        c_url = node.get("contentUrl") or node.get("embedUrl")
                        t_url = node.get("thumbnailUrl")
                        if isinstance(t_url, list) and t_url:
                            t_url = t_url[0]
                        v_name = node.get("name") or page_title
                        if c_url:
                            _, vt = is_likely_video_url(c_url)
                            add_video(c_url, t_url if isinstance(t_url, str) else "", v_name, source_type=vt or "direct")
        except Exception:
            pass

    return videos


def categorize_link(url: str, page_domain: str = "") -> tuple[str, str, bool]:
    """
    Categorizes a hyperlink into:
    (category_key, category_label_tr, is_external)
    Categories: 'file', 'video', 'image', 'cloud', 'webpage'
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")
    path_low = unquote(parsed.path).lower()
    is_external = bool(host and page_domain and host != page_domain)

    if any(path_low.endswith(ext) for ext in FILE_ARCHIVE_EXTENSIONS):
        return "file", "📦 Dosya / Belge", is_external

    is_vid, _ = is_likely_video_url(url)
    if is_vid:
        return "video", "🎬 Video Bağlantısı", is_external

    if any(path_low.endswith(ext) for ext in IMAGE_EXTENSIONS) or any(d in host for d in KNOWN_IMAGE_HOST_DOMAINS):
        return "image", "🖼️ Görsel Bağlantısı", is_external

    if any(d in host for d in KNOWN_CLOUD_HOST_DOMAINS):
        return "cloud", "☁️ Bulut / Dosya Host", is_external

    if ATTACHMENT_PATTERNS.search(url):
        return "file", "📎 Forum Eki (Attachment)", is_external

    return "webpage", "🌐 Web Sayfası", is_external


def clean_element_text(el) -> str:
    """Extracts readable, well-spaced text from a BeautifulSoup element."""
    clone = BeautifulSoup(str(el), "lxml")
    for junk in clone.find_all(["script", "style", "noscript", "svg", "iframe", "form", "button"]):
        junk.decompose()

    # Replace <br> and block endings with newlines
    for br in clone.find_all("br"):
        br.replace_with("\n")
    for p in clone.find_all(["p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"]):
        p.append("\n")

    raw_text = clone.get_text()
    lines = []
    for line in raw_text.splitlines():
        cleaned_line = re.sub(r"[ \t\r\f\v]+", " ", line).strip()
        if cleaned_line:
            lines.append(cleaned_line)
        elif lines and lines[-1] != "":
            lines.append("")

    # Collapse multiple blank lines
    result = "\n".join(lines).strip()
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result


def extract_links_from_element(el, base_url: str, page_domain: str) -> list:
    """Extracts all meaningful hyperlinks inside a given HTML element."""
    links = []
    seen = set()

    # Common boilerplate navigation/action patterns to skip inside post bodies
    skip_patterns = (
        "/login", "/register", "/logout", "/search", "/members/",
        "javascript:", "mailto:", "tel:", "#"
    )

    for a_tag in el.find_all("a", href=True):
        raw_href = (a_tag.get("href") or "").strip()
        if not raw_href or raw_href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        full_u = urljoin(base_url, raw_href)
        norm_u = full_u.split("#")[0]
        if not norm_u or norm_u in seen:
            continue

        # Skip self anchor or pure forum quote jump links like /goto/post?id=...
        if any(sp in raw_href.lower() for sp in skip_patterns):
            continue
        if re.search(r"/(goto/post|posts/\d+/reply|posts/\d+/react|posts/\d+/report|misc/contact)", full_u.lower()):
            continue

        seen.add(norm_u)
        anchor_text = a_tag.get_text(" ", strip=True)
        if not anchor_text:
            img = a_tag.find("img")
            if img:
                anchor_text = img.get("alt") or img.get("title") or "Görsel Bağlantısı"
            else:
                anchor_text = a_tag.get("title") or a_tag.get("aria-label") or unquote(urlparse(full_u).path.split("/")[-1]) or full_u

        cat_key, cat_label, is_ext = categorize_link(full_u, page_domain)
        domain = urlparse(full_u).netloc.replace("www.", "")

        links.append({
            "url": full_u,
            "text": anchor_text[:140],
            "domain": domain,
            "category": cat_key,
            "category_label": cat_label,
            "is_external": is_ext,
        })

    # Sort links so cloud/file/video/external links appear prominently first
    priority_map = {"cloud": 0, "file": 1, "video": 2, "image": 3, "webpage": 4}
    links.sort(key=lambda x: (priority_map.get(x["category"], 5), 0 if x["is_external"] else 1))
    return links


def extract_texts_and_links(soup: BeautifulSoup, final_url: str, page_title: str = "") -> tuple[list, list]:
    """
    Extracts structured text blocks (forum posts, articles, or page content) and their associated links.
    Returns (texts_list, all_page_links_list).
    """
    page_domain = urlparse(final_url).netloc.lower().replace("www.", "")
    texts = []

    # 1. Try detecting structured forum posts or article containers
    post_selectors = [
        "article.message",                  # XenForo 2
        "li.message",                       # XenForo 1
        "div.post",                         # vBulletin / phpBB / MyBB
        "div.postbody",                     # phpBB
        "div.topic-post",                   # Discourse
        "div[id^='post_message_']",         # vBulletin
        "div.comment-body",                 # General comments
        "article",                          # Blog / News articles
    ]

    found_posts = []
    for sel in post_selectors:
        candidates = soup.select(sel)
        if candidates:
            found_posts = candidates
            break

    post_blocks = []
    for idx, post_el in enumerate(found_posts[:60], start=1):
        # Try finding the specific message body inside a forum post container
        body_el = (
            post_el.select_one(".message-body .bbWrapper")
            or post_el.select_one(".message-body")
            or post_el.select_one(".postcontent")
            or post_el.select_one(".content")
            or post_el.select_one(".entry-content")
            or post_el.select_one(".post-content")
            or post_el
        )

        author = (
            post_el.get("data-author")
            or (post_el.select_one(".message-name, .username, .author, [itemprop='name'], .postauthor") and
                post_el.select_one(".message-name, .username, .author, [itemprop='name'], .postauthor").get_text(strip=True))
            or ""
        )

        date_str = ""
        time_el = post_el.find("time") or post_el.select_one(".message-date, .postdate, .date")
        if time_el:
            date_str = time_el.get_text(" ", strip=True) or time_el.get("datetime") or ""

        heading_el = post_el.find(["h1", "h2", "h3"])
        heading_txt = heading_el.get_text(" ", strip=True) if heading_el else ""

        clean_txt = clean_element_text(body_el)
        block_links = extract_links_from_element(body_el, final_url, page_domain)

        # Keep block if it has meaningful text or links
        if len(clean_txt) < 15 and not block_links:
            continue

        title_parts = []
        if author:
            title_parts.append(f"👤 {author}")
        if heading_txt and heading_txt != author:
            title_parts.append(heading_txt[:70])
        if not title_parts:
            title_parts.append(f"Bölüm / Mesaj #{len(post_blocks) + 1}")

        block_title = f"#{len(post_blocks) + 1} — " + " • ".join(title_parts)
        words = len(clean_txt.split())

        post_blocks.append({
            "id": len(post_blocks) + 2,  # ID 1 is reserved for Full Page Summary
            "title": block_title,
            "author": author,
            "date": date_str[:40],
            "text": clean_txt,
            "char_count": len(clean_txt),
            "word_count": words,
            "links": block_links,
            "is_full_page": False,
            "filename": f"metin_bolum_{len(post_blocks) + 1:02d}.txt",
        })

    # 2. Extract full page main content text & all links
    main_container = (
        soup.find("main")
        or soup.select_one("#content, .p-body-main, .main-content, #main, article, .container")
        or soup.body
        or soup
    )

    if post_blocks:
        # Combine all post blocks into a clean full-page compilation
        combined_sections = []
        seen_links_map = {}
        for pb in post_blocks:
            header_line = f"=== {pb['title']} {('(' + pb['date'] + ')') if pb['date'] else ''} ==="
            section_str = f"{header_line}\n{pb['text']}"
            if pb["links"]:
                links_str = "\n".join(f"  - [{l['category_label']}] {l['text']}: {l['url']}" for l in pb["links"])
                section_str += f"\n\n[Bu Bölümdeki Bağlantılar ({len(pb['links'])})]:\n{links_str}"
            combined_sections.append(section_str)
            for l in pb["links"]:
                seen_links_map[l["url"]] = l

        full_text = "\n\n" + ("\n\n" + "-" * 60 + "\n\n").join(combined_sections)
        full_text = f"Sayfa Başlığı: {page_title}\nKaynak URL: {final_url}\n" + full_text
        all_links = list(seen_links_map.values())
    else:
        full_body_text = clean_element_text(main_container)
        all_links = extract_links_from_element(main_container, final_url, page_domain)
        full_text = f"Sayfa Başlığı: {page_title}\nKaynak URL: {final_url}\n\n{full_body_text}"

    # Create #1 Summary Entry ("Tüm Sayfa Metni & Bağlantılar")
    safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (page_title or "sayfa_metni")).strip(" ._")[:60] or "sayfa_metni"
    texts.append({
        "id": 1,
        "title": f"📑 Tüm Sayfa Metni & Bağlantılar ({page_title[:65]})",
        "author": "Tam Sayfa",
        "date": "",
        "text": full_text.strip(),
        "char_count": len(full_text),
        "word_count": len(full_text.split()),
        "links": all_links,
        "is_full_page": True,
        "filename": f"{safe_title}_tam_metin.txt",
    })

    texts.extend(post_blocks)
    return texts, all_links


def format_text_with_links_for_txt(title: str, source_url: str, text_body: str, links: list = None, include_links: bool = True) -> str:
    """Formats a text item and its detected links into a clean UTF-8 .txt document."""
    lines = [
        "=" * 70,
        f"BAŞLIK : {title}",
        f"KAYNAK : {source_url}",
        "=" * 70,
        "",
        text_body.strip(),
    ]
    if include_links and links:
        lines.extend([
            "",
            "=" * 70,
            f"İÇERİKTEKİ BAĞLANTILAR / LİNKLER ({len(links)} Adet)",
            "=" * 70,
        ])
        for i, lnk in enumerate(links, start=1):
            label = lnk.get("category_label") or "Link"
            txt = lnk.get("text") or ""
            u = lnk.get("url") or ""
            lines.append(f"{i:02d}. [{label}] {txt}\n    URL: {u}")
    lines.append("")
    return "\n".join(lines)


def detect_pagination(soup: BeautifulSoup, current_url: str):
    """Detects forum/gallery pagination controls."""
    prev_url = None
    next_url = None
    pages_map = {}

    link_prev = soup.find(
        "link",
        attrs={"rel": lambda r: r and "prev" in (r if isinstance(r, list) else r.lower().split())},
    )
    if link_prev and link_prev.get("href"):
        prev_url = urljoin(current_url, link_prev["href"].strip())

    link_next = soup.find(
        "link",
        attrs={"rel": lambda r: r and "next" in (r if isinstance(r, list) else r.lower().split())},
    )
    if link_next and link_next.get("href"):
        next_url = urljoin(current_url, link_next["href"].strip())

    pagination_selectors = [
        ".pageNav", ".pagenav", ".pagination", ".pager", ".pages",
        "nav[aria-label*='page' i]", "nav[aria-label*='sayfa' i]",
        ".navPages", ".pg", ".page-numbers", ".forum-pagination",
        "[class*='pagination' i]", "[class*='pagenav' i]",
    ]

    pagination_containers = []
    for sel in pagination_selectors:
        try:
            for el in soup.select(sel):
                if el not in pagination_containers:
                    pagination_containers.append(el)
        except Exception:
            pass

    def inspect_anchor(a_tag, in_pagination_container=False):
        nonlocal prev_url, next_url
        href = (a_tag.get("href") or "").strip()
        if not href or href.startswith(("javascript:", "#")):
            return
        full_href = urljoin(current_url, href)

        rel = a_tag.get("rel")
        rel_str = " ".join(rel).lower() if isinstance(rel, list) else str(rel or "").lower()
        classes = " ".join(a_tag.get("class", [])).lower()
        text = a_tag.get_text(" ", strip=True).lower()
        title = (a_tag.get("title") or "").lower()
        aria = (a_tag.get("aria-label") or "").lower()
        combined = f"{text} {title} {aria} {classes}"

        if not prev_url:
            if (
                "prev" in rel_str
                or "pagenav-jump--prev" in classes
                or any(k in combined for k in ("önceki", "onceki", "previous", "« önceki", "‹ önceki", "prev page"))
                or (in_pagination_container and text in ("‹", "«", "<", "prev", "önceki"))
            ):
                prev_url = full_href
                return

        if not next_url:
            if (
                "next" in rel_str
                or "pagenav-jump--next" in classes
                or any(k in combined for k in ("sonraki", "next page", "sonraki »", "sonraki ›", "ileri"))
                or (in_pagination_container and text in ("›", "»", ">", "next", "sonraki"))
            ):
                next_url = full_href
                return

        if in_pagination_container and text.isdigit():
            num = int(text)
            if 1 <= num <= 50000:
                is_curr = (
                    any(c in classes for c in ("current", "active", "selected", "pagenav-page--current"))
                    or a_tag.get("aria-current") == "page"
                )
                if num not in pages_map or is_curr:
                    pages_map[num] = {
                        "number": num,
                        "label": str(num),
                        "url": full_href,
                        "is_current": is_curr,
                    }

    for container in pagination_containers:
        for a_tag in container.find_all("a", href=True):
            inspect_anchor(a_tag, in_pagination_container=True)
        for el in container.find_all(["span", "strong", "em", "li", "a"]):
            el_classes = " ".join(el.get("class", [])).lower()
            is_curr = (
                any(c in el_classes for c in ("current", "active", "selected", "pagenav-page--current"))
                or el.get("aria-current") == "page"
            )
            if is_curr:
                txt = el.get_text(strip=True)
                if txt.isdigit():
                    num = int(txt)
                    pages_map[num] = {
                        "number": num,
                        "label": str(num),
                        "url": current_url,
                        "is_current": True,
                    }

    if not prev_url or not next_url:
        for a_tag in soup.find_all("a", href=True):
            inspect_anchor(a_tag, in_pagination_container=False)

    current_page = None
    for num, info in pages_map.items():
        if info["is_current"] or info["url"].rstrip("/") == current_url.rstrip("/"):
            info["is_current"] = True
            current_page = num

    if current_page is None:
        url_page_match = re.search(
            r"(?:/page[-/]|/p|[?&](?:page|p|sayfa)=)(\d+)\b", current_url, re.IGNORECASE
        )
        if url_page_match:
            current_page = int(url_page_match.group(1))
        elif pages_map or next_url:
            current_page = 1

    if current_page and current_page not in pages_map and (pages_map or prev_url or next_url):
        pages_map[current_page] = {
            "number": current_page,
            "label": str(current_page),
            "url": current_url,
            "is_current": True,
        }

    sorted_pages = [pages_map[k] for k in sorted(pages_map.keys())]
    page_url_template = detect_page_url_template(current_url, sorted_pages, next_url, prev_url)

    return {
        "has_pagination": bool(prev_url or next_url or len(sorted_pages) > 1),
        "current_page": current_page or 1,
        "prev_url": prev_url,
        "next_url": next_url,
        "pages": sorted_pages,
        "page_url_template": page_url_template,
    }


def detect_page_url_template(current_url: str, pages: list, next_url: str, prev_url: str):
    sample_urls = [p["url"] for p in pages if p["url"] != current_url]
    if next_url:
        sample_urls.append(next_url)
    if prev_url:
        sample_urls.append(prev_url)
    sample_urls.append(current_url)

    patterns = [
        (r"(/page-)(\d+)(?=/|$|\?)", r"\g<1>{page}"),
        (r"(/page/)(\d+)(?=/|$|\?)", r"\g<1>{page}"),
        (r"([?&](?:page|sayfa|p)=)(\d+)\b", r"\g<1>{page}"),
    ]
    for s_url in sample_urls:
        for pat, repl in patterns:
            if re.search(pat, s_url, re.IGNORECASE):
                return re.sub(pat, repl, s_url, count=1, flags=re.IGNORECASE)
    return None


def scrape_page(url: str, session=None):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    sess = session or create_session()

    # Use stream=True first so if the user pastes a direct link to a 500MB video/file, we don't load 500MB into RAM during scrape!
    resp = sess.get(url, timeout=25, stream=True)
    resp.raise_for_status()

    final_url = str(resp.url)
    content_type = (resp.headers.get("Content-Type") or "").lower()
    content_length = int(resp.headers.get("Content-Length") or 0)

    empty_pagination = {
        "has_pagination": False,
        "current_page": 1,
        "prev_url": None,
        "next_url": None,
        "pages": [],
        "page_url_template": None,
    }

    # Case 1: Direct Image URL
    if content_type.startswith("image/"):
        resp.close()
        fname = extract_filename(final_url, 1)
        return {
            "page_title": fname,
            "final_url": final_url,
            "images": [
                {
                    "id": 1,
                    "thumb_url": final_url,
                    "full_url": final_url,
                    "is_upgraded": False,
                    "width": 0,
                    "height": 0,
                    "alt": fname,
                    "filename": fname,
                }
            ],
            "videos": [],
            "texts": [],
            "links": [],
            "pagination": empty_pagination,
        }

    # Case 2: Direct Video Stream / File URL
    if content_type.startswith("video/") or any(urlparse(final_url).path.lower().endswith(ext) for ext in VIDEO_EXTENSIONS):
        resp.close()
        fname = extract_video_filename(final_url, 1)
        return {
            "page_title": fname,
            "final_url": final_url,
            "images": [],
            "videos": [
                {
                    "id": 1,
                    "video_url": final_url,
                    "thumb_url": "",
                    "title": fname,
                    "filename": fname,
                    "ext": os.path.splitext(fname)[1] if "." in fname else ".mp4",
                    "source_type": "direct",
                    "host": urlparse(final_url).netloc.replace("www.", ""),
                    "width": 0,
                    "height": 0,
                    "size_bytes": content_length,
                }
            ],
            "texts": [],
            "links": [],
            "pagination": empty_pagination,
        }

    # Case 3: Plain text document URL
    if content_type.startswith("text/plain"):
        raw_bytes = resp.raw.read(2 * 1024 * 1024, decode_content=True)
        resp.close()
        text_content = raw_bytes.decode("utf-8", errors="replace")
        fname = unquote(urlparse(final_url).path.split("/")[-1]) or "metin.txt"
        if not fname.lower().endswith(".txt"):
            fname += ".txt"
        return {
            "page_title": fname,
            "final_url": final_url,
            "images": [],
            "videos": [],
            "texts": [
                {
                    "id": 1,
                    "title": fname,
                    "author": "",
                    "date": "",
                    "text": text_content,
                    "char_count": len(text_content),
                    "word_count": len(text_content.split()),
                    "links": [],
                    "is_full_page": True,
                    "filename": fname,
                }
            ],
            "links": [],
            "pagination": empty_pagination,
        }

    # Read HTML content
    html_bytes = resp.content
    resp.close()
    html_text = html_bytes.decode(resp.encoding or "utf-8", errors="replace")

    soup = BeautifulSoup(html_text, "lxml")
    page_title = (
        soup.title.string.strip()
        if soup.title and soup.title.string
        else urlparse(final_url).netloc
    )

    seen_keys = {}
    images = []

    def add_image_entry(thumb_u, full_u, width=0, height=0, alt="", source_type="img"):
        if not thumb_u and not full_u:
            return
        thumb_u = thumb_u or full_u
        full_u = full_u or thumb_u

        if full_u.startswith(("data:image/gif", "data:image/svg")) and thumb_u == full_u:
            return

        norm_key = (full_u.split("#")[0], thumb_u.split("#")[0])
        if norm_key in seen_keys:
            return
        seen_keys[norm_key] = True

        idx = len(images) + 1
        fname = extract_filename(full_u, idx, fallback_url=thumb_u)
        images.append(
            {
                "id": idx,
                "thumb_url": thumb_u,
                "full_url": full_u,
                "is_upgraded": thumb_u != full_u,
                "width": width,
                "height": height,
                "alt": (alt or "").strip(),
                "filename": fname,
                "source_type": source_type,
            }
        )

    for img in soup.find_all("img"):
        thumb_u, full_u = extract_best_img_sources(img, final_url)
        if not thumb_u and not full_u:
            continue

        w_attr = img.get("width") or img.get("data-width") or "0"
        h_attr = img.get("height") or img.get("data-height") or "0"
        try:
            w = int(re.sub(r"[^\d]", "", str(w_attr)) or 0)
        except ValueError:
            w = 0
        try:
            h = int(re.sub(r"[^\d]", "", str(h_attr)) or 0)
        except ValueError:
            h = 0

        alt_text = img.get("alt") or img.get("title") or ""
        add_image_entry(thumb_u, full_u, w, h, alt_text, source_type="img")

    for a_tag in soup.find_all("a", href=True):
        if a_tag.find("img"):
            continue
        href = a_tag.get("href", "").strip()
        if not href or href.startswith(("javascript:", "#")):
            continue
        full_href = urljoin(final_url, href)
        parsed_path = urlparse(full_href).path.lower()
        if any(parsed_path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")):
            label = a_tag.get_text(" ", strip=True) or "Bağlantı Görseli"
            add_image_entry(full_href, full_href, 0, 0, label, source_type="link")

    bg_regex = re.compile(r"background(?:-image)?\s*:[^;]*url\(['\"]?([^'\")]+)['\"]?\)", re.IGNORECASE)
    for el in soup.find_all(style=True):
        style_str = el.get("style") or ""
        for match in bg_regex.finditer(style_str):
            raw_bg = match.group(1).strip()
            if raw_bg and not raw_bg.startswith("data:"):
                bg_url = urljoin(final_url, raw_bg)
                add_image_entry(bg_url, bg_url, 0, 0, "Arka Plan Görseli", source_type="bg")

    og_img = soup.find("meta", attrs={"property": "og:image"}) or soup.find("meta", attrs={"name": "twitter:image"})
    if og_img and og_img.get("content"):
        og_url = urljoin(final_url, og_img["content"].strip())
        add_image_entry(og_url, og_url, 0, 0, "Kapak Görseli (og:image)", source_type="meta")

    # Extract Videos
    videos = extract_videos_from_soup(soup, final_url, page_title)

    # Extract Texts & Links
    texts, links = extract_texts_and_links(soup, final_url, page_title)

    # Extract Pagination
    pagination = detect_pagination(soup, final_url)

    return {
        "page_title": page_title,
        "final_url": final_url,
        "images": images,
        "videos": videos,
        "texts": texts,
        "links": links,
        "pagination": pagination,
    }

import re
from urllib.parse import urljoin, urlparse, urlunparse
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
    " picstate.com",
    "imagevenue.com",
    "imgur.com",
    "flickr.com",
    "wallhaven.cc",
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


def extract_filename(url: str, index: int, fallback_url: str = None) -> str:
    """Extracts a clean filename from a URL."""
    for candidate_url in (url, fallback_url):
        if not candidate_url or candidate_url.startswith("data:"):
            continue
        parsed = urlparse(candidate_url)
        path = parsed.path.rstrip("/")
        segments = [s for s in path.split("/") if s]
        if not segments:
            continue
        name = segments[-1]
        # Convert XenForo slug like "photo-name-png.48291" -> "photo-name.png"
        xf_match = re.match(r"^(.+)-(jpe?g|png|webp|gif|avif)\.\d+$", name, re.IGNORECASE)
        if xf_match:
            name = f"{xf_match.group(1)}.{xf_match.group(2).lower()}"
        if name.lower().endswith(".html") or name.lower().endswith(".htm"):
            name = name[: name.rfind(".")]
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        if any(name.lower().endswith(ext) for ext in IMAGE_EXTENSIONS):
            return name

    return f"gorsel_{index:03d}.jpg"


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
    resp = sess.get(url, timeout=20)
    resp.raise_for_status()

    final_url = str(resp.url)
    content_type = (resp.headers.get("Content-Type") or "").lower()

    if content_type.startswith("image/"):
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
            "pagination": {
                "has_pagination": False,
                "current_page": 1,
                "prev_url": None,
                "next_url": None,
                "pages": [],
                "page_url_template": None,
            },
        }

    soup = BeautifulSoup(resp.text, "lxml")
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

    pagination = detect_pagination(soup, final_url)

    return {
        "page_title": page_title,
        "final_url": final_url,
        "images": images,
        "pagination": pagination,
    }

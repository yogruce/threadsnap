const state = {
    currentUrl: "",
    pageTitle: "",
    images: [],       // Array of scraped image objects + DOM element references
    pagination: null,
    minSize: 120,
    onlyUpgraded: false,
    downloadedUrls: new Set(),
    activeLightboxItem: null,
};

// DOM Elements
const scrapeForm = document.getElementById("scrape-form");
const urlInput = document.getElementById("url-input");
const scrapeBtn = document.getElementById("scrape-btn");
const pickFolderBtn = document.getElementById("pick-folder-btn");
const folderLabel = document.getElementById("folder-label");
const openFolderBtn = document.getElementById("open-folder-btn");

const minSizeSelect = document.getElementById("min-size-select");
const onlyUpgradedCb = document.getElementById("only-upgraded-cb");
const subfolderCb = document.getElementById("subfolder-cb");
const statsBadge = document.getElementById("stats-badge");
const downloadAllBtn = document.getElementById("download-all-btn");

const paginationBar = document.getElementById("pagination-bar");
const prevPageBtn = document.getElementById("prev-page-btn");
const nextPageBtn = document.getElementById("next-page-btn");
const pageNumbersContainer = document.getElementById("page-numbers");
const appendNextBtn = document.getElementById("append-next-btn");
const jumpPageBox = document.getElementById("jump-page-box");
const jumpPageInput = document.getElementById("jump-page-input");
const jumpPageBtn = document.getElementById("jump-page-btn");

const bottomPagination = document.getElementById("bottom-pagination");
const bottomPrevBtn = document.getElementById("bottom-prev-btn");
const bottomNextBtn = document.getElementById("bottom-next-btn");
const bottomAppendBtn = document.getElementById("bottom-append-btn");
const bottomPageInfo = document.getElementById("bottom-page-info");

const emptyState = document.getElementById("empty-state");
const loadingState = document.getElementById("loading-state");
const loadingText = document.getElementById("loading-text");
const imageGrid = document.getElementById("image-grid");

const lightboxModal = document.getElementById("lightbox-modal");
const lightboxBackdrop = document.getElementById("lightbox-backdrop");
const lightboxImg = document.getElementById("lightbox-img");
const lightboxTitle = document.getElementById("lightbox-title");
const lightboxDownloadBtn = document.getElementById("lightbox-download-btn");
const lightboxCloseBtn = document.getElementById("lightbox-close-btn");
const toastContainer = document.getElementById("toast-container");

// Initialize settings on startup
async function initSettings() {
    try {
        const res = await fetch("/api/settings");
        const cfg = await res.json();
        updateFolderLabel(cfg.download_dir);
        if (typeof cfg.create_site_subfolder === "boolean") {
            subfolderCb.checked = cfg.create_site_subfolder;
        }
    } catch (err) {
        console.error("Ayarlar yüklenemedi:", err);
    }
}

function updateFolderLabel(fullPath) {
    if (!fullPath) return;
    const parts = fullPath.replace(/\\/g, "/").split("/").filter(Boolean);
    const shortName = parts.slice(-2).join("/");
    folderLabel.textContent = shortName || fullPath;
    pickFolderBtn.title = `İndirme Klasörü: ${fullPath}\n(Değiştirmek için tıklayın)`;
}

function buildProxyUrl(imgUrl, referer, fallbackThumb = "") {
    if (!imgUrl) return "";
    if (imgUrl.startsWith("data:")) return imgUrl;
    const params = new URLSearchParams({ url: imgUrl, referer: referer || state.currentUrl });
    if (fallbackThumb && fallbackThumb !== imgUrl && !fallbackThumb.startsWith("data:")) {
        params.set("thumb", fallbackThumb);
    }
    return `/api/proxy?${params.toString()}`;
}

function showToast(message, isError = false, savedPath = null) {
    const toast = document.createElement("div");
    toast.className = `toast ${isError ? "error" : ""}`;

    const textSpan = document.createElement("span");
    textSpan.textContent = message;
    toast.appendChild(textSpan);

    if (savedPath) {
        const openBtn = document.createElement("button");
        openBtn.className = "toast-open-btn";
        openBtn.textContent = "Klasörde Göster";
        openBtn.addEventListener("click", () => {
            fetch("/api/open-folder", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path: savedPath }),
            });
        });
        toast.appendChild(openBtn);
    }

    toastContainer.appendChild(toast);
    setTimeout(() => {
        toast.remove();
    }, 4000);
}

// Scrape Page Function
async function scrapeUrl(targetUrl, appendMode = false) {
    if (!targetUrl) return;
    urlInput.value = targetUrl;

    emptyState.classList.add("hidden");
    loadingState.classList.remove("hidden");
    loadingText.textContent = appendMode
        ? "Sonraki sayfa taranıyor ve mevcut listeye ekleniyor..."
        : "Sayfa taranıyor ve görseller yakalanıyor...";
    scrapeBtn.disabled = true;

    if (!appendMode) {
        imageGrid.innerHTML = "";
        state.images = [];
    }

    try {
        const res = await fetch("/api/scrape", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: targetUrl }),
        });
        const data = await res.json();

        if (!res.ok || data.error) {
            throw new Error(data.error || "Sayfa taranamadı.");
        }

        state.currentUrl = data.final_url || targetUrl;
        state.pageTitle = data.page_title || "";
        state.pagination = data.pagination;
        urlInput.value = state.currentUrl;

        // Deduplicate when appending
        const existingFullUrls = new Set(state.images.map((item) => item.full_url));
        const newItems = (data.images || []).filter((item) => !existingFullUrls.has(item.full_url));

        renderNewImages(newItems, data.final_url);
        renderPagination(data.pagination);
        applyFiltersAndUpdateStats();

        if (!appendMode) {
            window.scrollTo({ top: 0, behavior: "smooth" });
        } else {
            showToast(`${newItems.length} yeni görsel listeye eklendi.`);
        }
    } catch (err) {
        showToast(err.message, true);
        if (state.images.length === 0) {
            emptyState.classList.remove("hidden");
        }
    } finally {
        loadingState.classList.add("hidden");
        scrapeBtn.disabled = false;
    }
}

function renderNewImages(items, pageReferer) {
    items.forEach((item) => {
        item.referer = pageReferer;
        item.loadedWidth = item.width || 0;
        item.loadedHeight = item.height || 0;
        item.loadFailed = false;

        const card = document.createElement("div");
        card.className = "img-card";
        if (state.downloadedUrls.has(item.full_url)) {
            card.classList.add("downloaded");
        }

        const proxyThumbSrc = buildProxyUrl(item.thumb_url, pageReferer);

        card.innerHTML = `
            <div class="thumb-wrapper">
                <div class="card-badges-top">
                    <div class="badge-group-left">
                        ${item.is_upgraded ? '<span class="badge badge-hd" title="Bu küçük resme tıkladığınızda bağlantılı yüksek çözünürlüklü orijinal görsel indirilir">HD Link</span>' : ""}
                        <span class="badge badge-status ${state.downloadedUrls.has(item.full_url) ? "" : "hidden"}">✓ İndirildi</span>
                    </div>
                    <button type="button" class="card-preview-btn" title="Tam Ekran Önizle (Büyüteç)">🔍</button>
                </div>
                <img src="${proxyThumbSrc}" alt="${escapeHtml(item.alt || item.filename)}" loading="lazy" />
                <div class="download-hint-overlay">
                    <span class="hint-pill">${state.downloadedUrls.has(item.full_url) ? "✓ Tekrar İndir" : "⬇ Tıkla & İndir"}</span>
                </div>
                <span class="badge-res">${item.loadedWidth && item.loadedHeight ? `${item.loadedWidth}×${item.loadedHeight}` : "..."}</span>
            </div>
            <div class="card-footer">
                <span class="card-filename" title="${escapeHtml(item.full_url)}">${escapeHtml(item.filename)}</span>
            </div>
        `;

        const imgEl = card.querySelector("img");
        const resBadge = card.querySelector(".badge-res");
        const previewBtn = card.querySelector(".card-preview-btn");

        imgEl.addEventListener("load", () => {
            const nw = imgEl.naturalWidth || item.width || 0;
            const nh = imgEl.naturalHeight || item.height || 0;
            item.loadedWidth = nw;
            item.loadedHeight = nh;
            if (nw && nh) {
                resBadge.textContent = `${nw}×${nh}`;
            } else {
                resBadge.textContent = "Görsel";
            }
            applyFiltersAndUpdateStats();
        });

        imgEl.addEventListener("error", () => {
            // Fallback: try direct URL if proxy had an issue
            if (!imgEl.dataset.retriedDirect) {
                imgEl.dataset.retriedDirect = "1";
                imgEl.src = item.thumb_url;
            } else {
                item.loadFailed = true;
                card.classList.add("hidden");
                applyFiltersAndUpdateStats();
            }
        });

        // Clicking preview button opens lightbox without triggering immediate download
        previewBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            openLightbox(item, card);
        });

        // Clicking anywhere on the thumbnail card downloads the full image immediately
        card.addEventListener("click", () => {
            downloadImage(item, card);
        });

        item.cardEl = card;
        state.images.push(item);
        imageGrid.appendChild(card);
    });
}

function isItemVisible(item) {
    if (item.loadFailed) return false;
    if (state.onlyUpgraded && !item.is_upgraded) return false;

    const minDim = state.minSize;
    if (minDim > 0 && (item.loadedWidth > 0 || item.loadedHeight > 0)) {
        // Keep items that have a high-res link even if their thumbnail on the forum is small (e.g. 100px thumb linking to 1920px image)
        if (!item.is_upgraded && item.loadedWidth < minDim && item.loadedHeight < minDim) {
            return false;
        }
        // Still hide ultra-tiny 1x1 / 16x16 UI icons even if wrapped in a link
        if (item.loadedWidth < 32 && item.loadedHeight < 32) {
            return false;
        }
    }
    return true;
}

function applyFiltersAndUpdateStats() {
    let visibleCount = 0;
    state.images.forEach((item) => {
        const visible = isItemVisible(item);
        if (item.cardEl) {
            item.cardEl.classList.toggle("hidden", !visible);
        }
        if (visible) visibleCount++;
    });

    const totalCount = state.images.length;
    const hiddenCount = totalCount - visibleCount;
    if (totalCount === 0) {
        statsBadge.textContent = "Görsel bulunamadı";
        downloadAllBtn.disabled = true;
    } else {
        statsBadge.textContent = `${visibleCount} görsel gösteriliyor` + (hiddenCount > 0 ? ` (${hiddenCount} küçük ikon gizlendi)` : "");
        downloadAllBtn.disabled = visibleCount === 0;
    }
}

async function downloadImage(item, cardEl) {
    if (!item || !item.full_url) return;
    if (cardEl && cardEl.classList.contains("downloading")) return;

    const hintPill = cardEl ? cardEl.querySelector(".hint-pill") : null;
    const statusBadge = cardEl ? cardEl.querySelector(".badge-status") : null;

    if (cardEl) {
        cardEl.classList.add("downloading");
        if (hintPill) hintPill.textContent = "⏳ İndiriliyor...";
    }

    try {
        const res = await fetch("/api/download", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                url: item.full_url,
                thumb_url: item.thumb_url,
                referer: item.referer || state.currentUrl,
                filename: item.filename,
                site_title: state.pageTitle,
            }),
        });
        const data = await res.json();
        if (!res.ok || data.error) {
            throw new Error(data.error || "İndirme hatası");
        }

        state.downloadedUrls.add(item.full_url);
        if (cardEl) {
            cardEl.classList.remove("downloading");
            cardEl.classList.add("downloaded");
            if (statusBadge) statusBadge.classList.remove("hidden");
            if (hintPill) hintPill.textContent = "✓ Tekrar İndir";
        }
        showToast(`İndirildi: ${data.filename} (${data.size_kb} KB)`, false, data.saved_path);
    } catch (err) {
        if (cardEl) {
            cardEl.classList.remove("downloading");
            if (hintPill) hintPill.textContent = "⬇ Tıkla & İndir";
        }
        showToast(`Hata: ${err.message}`, true);
    }
}

// Render Forum / Multi-Page Pagination Controls
function renderPagination(pag) {
    if (!pag || !pag.has_pagination) {
        paginationBar.classList.add("hidden");
        bottomPagination.classList.add("hidden");
        return;
    }

    paginationBar.classList.remove("hidden");
    bottomPagination.classList.remove("hidden");

    prevPageBtn.disabled = !pag.prev_url;
    prevPageBtn.onclick = () => pag.prev_url && scrapeUrl(pag.prev_url, false);

    nextPageBtn.disabled = !pag.next_url;
    nextPageBtn.onclick = () => pag.next_url && scrapeUrl(pag.next_url, false);

    bottomPrevBtn.disabled = !pag.prev_url;
    bottomPrevBtn.onclick = () => pag.prev_url && scrapeUrl(pag.prev_url, false);

    bottomNextBtn.disabled = !pag.next_url;
    bottomNextBtn.onclick = () => pag.next_url && scrapeUrl(pag.next_url, false);

    bottomPageInfo.textContent = `Sayfa ${pag.current_page || 1}`;

    if (pag.next_url) {
        appendNextBtn.classList.remove("hidden");
        bottomAppendBtn.classList.remove("hidden");
        appendNextBtn.onclick = () => scrapeUrl(pag.next_url, true);
        bottomAppendBtn.onclick = () => scrapeUrl(pag.next_url, true);
    } else {
        appendNextBtn.classList.add("hidden");
        bottomAppendBtn.classList.add("hidden");
    }

    // Numbered page buttons
    pageNumbersContainer.innerHTML = "";
    let lastNum = 0;
    (pag.pages || []).forEach((p) => {
        if (lastNum && p.number - lastNum > 1) {
            const dots = document.createElement("span");
            dots.textContent = "...";
            dots.style.color = "#64748b";
            dots.style.padding = "0 4px";
            pageNumbersContainer.appendChild(dots);
        }
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `btn-page ${p.is_current ? "active" : ""}`;
        btn.textContent = p.label;
        btn.addEventListener("click", () => scrapeUrl(p.url, false));
        pageNumbersContainer.appendChild(btn);
        lastNum = p.number;
    });

    // Direct page jump box if URL template is known
    if (pag.page_url_template) {
        jumpPageBox.classList.remove("hidden");
        jumpPageInput.value = "";
        jumpPageBtn.onclick = () => {
            const targetNum = parseInt(jumpPageInput.value, 10);
            if (targetNum && targetNum > 0) {
                const targetUrl = pag.page_url_template.replace("{page}", String(targetNum));
                scrapeUrl(targetUrl, false);
            }
        };
    } else {
        jumpPageBox.classList.add("hidden");
    }
}

// Lightbox Modal
function openLightbox(item, cardEl) {
    state.activeLightboxItem = { item, cardEl };
    lightboxTitle.textContent = `${item.filename} — ${item.full_url}`;
    lightboxImg.src = buildProxyUrl(item.full_url, item.referer || state.currentUrl, item.thumb_url);
    lightboxModal.classList.remove("hidden");
}

function closeLightbox() {
    lightboxModal.classList.add("hidden");
    lightboxImg.src = "";
    state.activeLightboxItem = null;
}

lightboxCloseBtn.addEventListener("click", closeLightbox);
lightboxBackdrop.addEventListener("click", closeLightbox);
lightboxDownloadBtn.addEventListener("click", () => {
    if (state.activeLightboxItem) {
        downloadImage(state.activeLightboxItem.item, state.activeLightboxItem.cardEl);
    }
});

window.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !lightboxModal.classList.contains("hidden")) {
        closeLightbox();
    }
});

// Event Listeners
scrapeForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const target = urlInput.value.trim();
    if (target) {
        scrapeUrl(target, false);
    }
});

minSizeSelect.addEventListener("change", () => {
    state.minSize = parseInt(minSizeSelect.value, 10) || 0;
    applyFiltersAndUpdateStats();
});

onlyUpgradedCb.addEventListener("change", () => {
    state.onlyUpgraded = onlyUpgradedCb.checked;
    applyFiltersAndUpdateStats();
});

subfolderCb.addEventListener("change", () => {
    fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ create_site_subfolder: subfolderCb.checked }),
    });
});

pickFolderBtn.addEventListener("click", async () => {
    const res = await fetch("/api/pick-folder", { method: "POST" });
    const data = await res.json();
    if (data.download_dir) {
        updateFolderLabel(data.download_dir);
        if (data.changed) {
            showToast(`İndirme klasörü güncellendi: ${data.download_dir}`);
        }
    }
});

openFolderBtn.addEventListener("click", () => {
    fetch("/api/open-folder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
    });
});

downloadAllBtn.addEventListener("click", async () => {
    const visibleItems = state.images.filter((item) => isItemVisible(item));
    if (visibleItems.length === 0) return;

    downloadAllBtn.disabled = true;
    const originalText = downloadAllBtn.textContent;

    for (let i = 0; i < visibleItems.length; i++) {
        downloadAllBtn.textContent = `⏳ İndiriliyor (${i + 1}/${visibleItems.length})...`;
        const item = visibleItems[i];
        await downloadImage(item, item.cardEl);
    }

    downloadAllBtn.textContent = originalText;
    downloadAllBtn.disabled = false;
    showToast(`${visibleItems.length} görselin tamamı indirildi!`);
});

function escapeHtml(str) {
    return String(str || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

initSettings();

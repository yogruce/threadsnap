const state = {
    currentUrl: "",
    pageTitle: "",
    activeTab: "images",  // "images" | "videos" | "texts" | "links"
    images: [],
    videos: [],
    texts: [],
    links: [],
    pagination: null,
    minSize: 120,
    onlyUpgraded: false,
    includeLinksInTxt: true,
    downloadedUrls: new Set(),
    activeLightboxItem: null,
    queueTasks: [],
    notifiedTaskIds: new Set(),
    queuePollTimer: null,
};

// DOM Elements
const scrapeForm = document.getElementById("scrape-form");
const urlInput = document.getElementById("url-input");
const scrapeBtn = document.getElementById("scrape-btn");
const pickFolderBtn = document.getElementById("pick-folder-btn");
const folderLabel = document.getElementById("folder-label");
const openFolderBtn = document.getElementById("open-folder-btn");

const toggleQueueBtn = document.getElementById("toggle-queue-btn");
const queueBadge = document.getElementById("queue-badge");
const queuePanel = document.getElementById("queue-panel");
const queueSummaryText = document.getElementById("queue-summary-text");
const queueItemsList = document.getElementById("queue-items-list");
const queueClearBtn = document.getElementById("queue-clear-btn");
const queueCancelAllBtn = document.getElementById("queue-cancel-all-btn");
const queueCloseBtn = document.getElementById("queue-close-btn");

const tabButtons = document.querySelectorAll(".tab-btn");
const countImagesEl = document.getElementById("count-images");
const countVideosEl = document.getElementById("count-videos");
const countTextsEl = document.getElementById("count-texts");
const countLinksEl = document.getElementById("count-links");

const tabPanelImages = document.getElementById("tab-panel-images");
const tabPanelVideos = document.getElementById("tab-panel-videos");
const tabPanelTexts = document.getElementById("tab-panel-texts");
const tabPanelLinks = document.getElementById("tab-panel-links");
const imageFiltersBar = document.getElementById("image-filters-bar");

const minSizeSelect = document.getElementById("min-size-select");
const onlyUpgradedCb = document.getElementById("only-upgraded-cb");
const thresholdSelect = document.getElementById("threshold-select");
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
const videoGrid = document.getElementById("video-grid");
const textList = document.getElementById("text-list");
const linksListContainer = document.getElementById("links-list-container");

const downloadAllVideosBtn = document.getElementById("download-all-videos-btn");
const includeLinksTxtCb = document.getElementById("include-links-txt-cb");
const downloadFullTextBtn = document.getElementById("download-full-text-btn");
const downloadAllLinksTxtBtn = document.getElementById("download-all-links-txt-btn");

const linkCategoryFilter = document.getElementById("link-category-filter");
const linkSearchInput = document.getElementById("link-search-input");
const exportFilteredLinksTxtBtn = document.getElementById("export-filtered-links-txt-btn");
const downloadFilteredLinksContentBtn = document.getElementById("download-filtered-links-content-btn");

const lightboxModal = document.getElementById("lightbox-modal");
const lightboxBackdrop = document.getElementById("lightbox-backdrop");
const lightboxImg = document.getElementById("lightbox-img");
const lightboxVideo = document.getElementById("lightbox-video");
const lightboxTitle = document.getElementById("lightbox-title");
const lightboxDownloadBtn = document.getElementById("lightbox-download-btn");
const lightboxCloseBtn = document.getElementById("lightbox-close-btn");
const toastContainer = document.getElementById("toast-container");

// Map URL -> DOM card elements so queue updates can reflect on cards
const urlToCardMap = new Map();

// Initialize settings on startup
async function initSettings() {
    try {
        const res = await fetch("/api/settings");
        const cfg = await res.json();
        updateFolderLabel(cfg.download_dir);
        if (typeof cfg.create_site_subfolder === "boolean") {
            subfolderCb.checked = cfg.create_site_subfolder;
        }
        if (cfg.large_file_threshold_mb) {
            thresholdSelect.value = String(cfg.large_file_threshold_mb);
        }
        if (typeof cfg.include_links_in_txt === "boolean") {
            includeLinksTxtCb.checked = cfg.include_links_in_txt;
            state.includeLinksInTxt = cfg.include_links_in_txt;
        }
        pollQueueStatus();
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

function buildVideoProxyUrl(videoUrl, referer) {
    if (!videoUrl) return "";
    const params = new URLSearchParams({ url: videoUrl, referer: referer || state.currentUrl });
    return `/api/video-proxy?${params.toString()}`;
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
    }, 4200);
}

// Switch Active Category Tab
function switchTab(tabName) {
    state.activeTab = tabName;
    tabButtons.forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.tab === tabName);
    });

    tabPanelImages.classList.toggle("hidden", tabName !== "images");
    tabPanelVideos.classList.toggle("hidden", tabName !== "videos");
    tabPanelTexts.classList.toggle("hidden", tabName !== "texts");
    tabPanelLinks.classList.toggle("hidden", tabName !== "links");

    imageFiltersBar.classList.toggle("hidden", tabName !== "images");
    updateToolbarStatsAndMainAction();
}

tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
        switchTab(btn.dataset.tab);
    });
});

// Scrape Page Function
async function scrapeUrl(targetUrl, appendMode = false) {
    if (!targetUrl) return;
    urlInput.value = targetUrl;

    emptyState.classList.add("hidden");
    loadingState.classList.remove("hidden");
    loadingText.textContent = appendMode
        ? "Sonraki sayfa taranıyor ve mevcut listeye ekleniyor..."
        : "Sayfa taranıyor; görseller, videolar, metinler ve linkler yakalanıyor...";
    scrapeBtn.disabled = true;

    if (!appendMode) {
        imageGrid.innerHTML = "";
        videoGrid.innerHTML = "";
        textList.innerHTML = "";
        linksListContainer.innerHTML = "";
        state.images = [];
        state.videos = [];
        state.texts = [];
        state.links = [];
        urlToCardMap.clear();
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

        // 1. Images
        const existingImgUrls = new Set(state.images.map((item) => item.full_url));
        const newImages = (data.images || []).filter((item) => !existingImgUrls.has(item.full_url));
        renderNewImages(newImages, data.final_url);

        // 2. Videos
        const existingVidUrls = new Set(state.videos.map((v) => v.video_url));
        const newVideos = (data.videos || []).filter((v) => !existingVidUrls.has(v.video_url));
        renderNewVideos(newVideos, data.final_url);

        // 3. Texts
        const newTexts = data.texts || [];
        if (!appendMode) {
            state.texts = newTexts;
        } else {
            // When appending next page, append non-summary post blocks
            const extraBlocks = newTexts.filter((t) => !t.is_full_page);
            state.texts.push(...extraBlocks);
        }
        renderTexts(state.texts, data.final_url);

        // 4. Links
        const existingLinkUrls = new Set(state.links.map((l) => l.url));
        const newLinks = (data.links || []).filter((l) => !existingLinkUrls.has(l.url));
        state.links.push(...newLinks);
        renderLinksTab();

        renderPagination(data.pagination);
        applyFiltersAndUpdateStats();

        // Auto-switch tab if current tab is empty and another has content on fresh scrape
        if (!appendMode) {
            const visibleImgs = state.images.filter((i) => isItemVisible(i)).length;
            if (visibleImgs === 0 && state.videos.length > 0) {
                switchTab("videos");
            } else if (visibleImgs === 0 && state.texts.length > 0 && state.images.length === 0) {
                switchTab("texts");
            } else {
                switchTab(state.activeTab);
            }
            window.scrollTo({ top: 0, behavior: "smooth" });
        } else {
            showToast(
                `Eklendi: ${newImages.length} görsel, ${newVideos.length} video, ${newLinks.length} bağlantı.`
            );
        }
    } catch (err) {
        showToast(err.message, true);
        if (state.images.length === 0 && state.videos.length === 0 && state.texts.length === 0) {
            emptyState.classList.remove("hidden");
        }
    } finally {
        loadingState.classList.add("hidden");
        scrapeBtn.disabled = false;
    }
}

// ============================================================================
// RENDER IMAGES
// ============================================================================

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
            resBadge.textContent = nw && nh ? `${nw}×${nh}` : "Görsel";
            applyFiltersAndUpdateStats();
        });

        imgEl.addEventListener("error", () => {
            if (!imgEl.dataset.retriedDirect) {
                imgEl.dataset.retriedDirect = "1";
                imgEl.src = item.thumb_url;
            } else {
                item.loadFailed = true;
                card.classList.add("hidden");
                applyFiltersAndUpdateStats();
            }
        });

        previewBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            openImageLightbox(item, card);
        });

        card.addEventListener("click", () => {
            enqueueDownloads([
                {
                    item_type: "image",
                    url: item.full_url,
                    thumb_url: item.thumb_url,
                    referer: item.referer || state.currentUrl,
                    filename: item.filename,
                    site_title: state.pageTitle,
                },
            ], card);
        });

        item.cardEl = card;
        urlToCardMap.set(item.full_url, card);
        state.images.push(item);
        imageGrid.appendChild(card);
    });
}

// ============================================================================
// RENDER VIDEOS
// ============================================================================

function renderNewVideos(videos, pageReferer) {
    videos.forEach((vid) => {
        vid.referer = pageReferer;
        const card = document.createElement("div");
        card.className = "video-card";
        if (state.downloadedUrls.has(vid.video_url)) {
            card.classList.add("downloaded");
        }

        const typeLabels = {
            direct: "MP4 / Doğrudan Video",
            stream: "Canlı / HLS Akışı",
            embed: "Gömülü Video (Embed)",
            ytdlp: "Platform Videosu",
        };
        const badgeLabel = typeLabels[vid.source_type] || "Video";
        const thumbSrc = vid.thumb_url ? buildProxyUrl(vid.thumb_url, pageReferer) : "";
        const sizeInfo = vid.size_bytes ? ` • ${(vid.size_bytes / (1024 * 1024)).toFixed(1)} MB` : "";

        card.innerHTML = `
            <div class="video-thumb-box">
                <div class="card-badges-top">
                    <div class="badge-group-left">
                        <span class="badge badge-video-type">${escapeHtml(badgeLabel)}</span>
                        <span class="badge badge-status ${state.downloadedUrls.has(vid.video_url) ? "" : "hidden"}">✓ İndirildi</span>
                    </div>
                </div>
                ${thumbSrc ? `<img src="${thumbSrc}" alt="${escapeHtml(vid.title)}" loading="lazy" />` : ""}
                <div class="video-play-icon">▶</div>
                <span class="badge-res">${escapeHtml(vid.ext.toUpperCase().replace(".", ""))}${sizeInfo}</span>
            </div>
            <div class="video-card-body">
                <div class="video-title" title="${escapeHtml(vid.title)}">${escapeHtml(vid.title)}</div>
                <div class="video-meta" title="${escapeHtml(vid.video_url)}">🌐 ${escapeHtml(vid.host || "Video Kaynağı")} — ${escapeHtml(vid.filename)}</div>
                <div class="video-actions">
                    <button type="button" class="btn-secondary btn-sm video-preview-btn">▶ Önizle</button>
                    <button type="button" class="btn-purple btn-sm video-dl-btn">⬇ Videoyu İndir</button>
                </div>
            </div>
        `;

        const previewBtn = card.querySelector(".video-preview-btn");
        const dlBtn = card.querySelector(".video-dl-btn");

        previewBtn.addEventListener("click", () => {
            openVideoLightbox(vid, card);
        });

        dlBtn.addEventListener("click", () => {
            enqueueDownloads([
                {
                    item_type: "video",
                    url: vid.video_url,
                    referer: vid.referer || state.currentUrl,
                    filename: vid.filename,
                    site_title: state.pageTitle,
                    source_type: vid.source_type,
                    size_bytes: vid.size_bytes || 0,
                },
            ], card, true);
        });

        vid.cardEl = card;
        urlToCardMap.set(vid.video_url, card);
        state.videos.push(vid);
        videoGrid.appendChild(card);
    });
}

// ============================================================================
// RENDER TEXTS & EMBEDDED LINKS
// ============================================================================

function renderTexts(texts, pageReferer) {
    textList.innerHTML = "";
    if (!texts || texts.length === 0) {
        textList.innerHTML = `<div class="queue-empty">Bu sayfada anlamlı metin bloğu bulunamadı.</div>`;
        return;
    }

    texts.forEach((tItem) => {
        const card = document.createElement("div");
        card.className = `text-card ${tItem.is_full_page ? "full-page-card" : ""}`;
        const links = tItem.links || [];

        const linksSectionHtml = links.length > 0
            ? `
            <div class="embedded-links-section">
                <div class="embedded-links-header">
                    <span>🔗 Bu Metinde Tespit Edilen Bağlantılar (${links.length} Link Belirtildi)</span>
                    <div class="text-card-actions">
                        <button type="button" class="btn-xs export-block-links-txt-btn">📄 Sadece Bu Linkleri (.txt) İndir</button>
                        <button type="button" class="btn-xs btn-accent download-block-links-content-btn">📥 Tüm Linklerin İçeriğini Sırayla İndir</button>
                    </div>
                </div>
                <div class="embedded-links-grid"></div>
            </div>
            `
            : "";

        card.innerHTML = `
            <div class="text-card-header">
                <div class="text-card-title-group">
                    <span class="text-card-title">${escapeHtml(tItem.title)}</span>
                    ${tItem.date ? `<span class="text-meta-pill">🕒 ${escapeHtml(tItem.date)}</span>` : ""}
                    <span class="text-meta-pill">${tItem.word_count} kelime • ${tItem.char_count} karakter</span>
                    ${links.length > 0
                        ? `<span class="link-alert-pill">🔗 ${links.length} Link Var</span>`
                        : `<span class="text-meta-pill">Link Yok</span>`
                    }
                </div>
                <div class="text-card-actions">
                    <button type="button" class="btn-secondary btn-sm copy-text-btn">📋 Kopyala</button>
                    <button type="button" class="btn-primary btn-sm dl-text-txt-btn">⬇ Metni (.txt) İndir</button>
                </div>
            </div>
            <div class="text-content-box">${escapeHtml(tItem.text)}</div>
            ${linksSectionHtml}
        `;

        // Copy text button
        card.querySelector(".copy-text-btn").addEventListener("click", () => {
            navigator.clipboard.writeText(tItem.text);
            showToast("Metin panoya kopyalandı!");
        });

        // Download text as .txt
        card.querySelector(".dl-text-txt-btn").addEventListener("click", () => {
            enqueueDownloads([
                {
                    item_type: "text",
                    url: state.currentUrl,
                    referer: pageReferer || state.currentUrl,
                    filename: tItem.filename || "sayfa_metni.txt",
                    site_title: state.pageTitle,
                    text_title: tItem.title,
                    text_content: tItem.text,
                    links_list: links,
                    include_links: includeLinksTxtCb.checked,
                },
            ]);
        });

        // Populate embedded links rows if present
        if (links.length > 0) {
            const linksGrid = card.querySelector(".embedded-links-grid");
            links.forEach((lnk) => {
                linksGrid.appendChild(createLinkRowElement(lnk, pageReferer));
            });

            // Export only these links as .txt
            const expLinksBtn = card.querySelector(".export-block-links-txt-btn");
            if (expLinksBtn) {
                expLinksBtn.addEventListener("click", () => {
                    const linksOnlyBody = links
                        .map((l, i) => `${i + 1}. [${l.category_label}] ${l.text}\n   ${l.url}`)
                        .join("\n\n");
                    enqueueDownloads([
                        {
                            item_type: "text",
                            url: state.currentUrl,
                            referer: pageReferer || state.currentUrl,
                            filename: (tItem.filename || "metin").replace(".txt", "") + "_linkler.txt",
                            site_title: state.pageTitle,
                            text_title: `${tItem.title} — Bağlantı Listesi`,
                            text_content: linksOnlyBody,
                            links_list: [],
                            include_links: false,
                        },
                    ]);
                });
            }

            // Queue content download for all links in this block
            const dlAllBlockLinksBtn = card.querySelector(".download-block-links-content-btn");
            if (dlAllBlockLinksBtn) {
                dlAllBlockLinksBtn.addEventListener("click", () => {
                    const batch = links.map((l, idx) => ({
                        item_type: "link_content",
                        url: l.url,
                        referer: pageReferer || state.currentUrl,
                        filename: l.text || `baglanti_${idx + 1}`,
                        site_title: state.pageTitle,
                    }));
                    enqueueDownloads(batch, null, true);
                });
            }
        }

        textList.appendChild(card);
    });
}

function createLinkRowElement(lnk, pageReferer) {
    const row = document.createElement("div");
    row.className = "link-row";

    const catClass = `link-cat-${lnk.category || "webpage"}`;

    row.innerHTML = `
        <div class="link-info-left">
            <span class="link-cat-badge ${catClass}">${escapeHtml(lnk.category_label || "Link")}</span>
            <div class="link-text-and-url">
                <span class="link-anchor-label" title="${escapeHtml(lnk.text)}">${escapeHtml(lnk.text || lnk.domain || "Bağlantı")}</span>
                <a href="${escapeHtml(lnk.url)}" target="_blank" rel="noopener" class="link-raw-url" title="${escapeHtml(lnk.url)}">${escapeHtml(lnk.url)}</a>
            </div>
        </div>
        <div class="link-row-actions">
            <button type="button" class="btn-xs scan-link-btn" title="Bu bağlantıyı ImgCatcher içinde aç ve görsel/video/metinlerini tara">🔍 Uygulamada Tara</button>
            <button type="button" class="btn-xs dl-link-txt-btn" title="Hedef bağlantının sayfa/yazı içeriğini .txt olarak indir">📄 Linki .txt İndir</button>
            <button type="button" class="btn-xs btn-accent dl-link-content-btn" title="Linkteki hedef dosyayı (görsel, video, arşiv, belge veya sayfa içeriği) indir">📥 İçeriği İndir</button>
        </div>
    `;

    // Prevent clicking raw URL from opening inside the PyQt WebView unexpectedly; copy URL on click instead
    const rawLinkEl = row.querySelector(".link-raw-url");
    rawLinkEl.addEventListener("click", (e) => {
        e.preventDefault();
        navigator.clipboard.writeText(lnk.url);
        showToast(`Link kopyalandı: ${lnk.url}`);
    });

    row.querySelector(".scan-link-btn").addEventListener("click", () => {
        scrapeUrl(lnk.url, false);
    });

    row.querySelector(".dl-link-txt-btn").addEventListener("click", () => {
        enqueueDownloads([
            {
                item_type: "link_txt",
                url: lnk.url,
                referer: pageReferer || state.currentUrl,
                filename: `${lnk.text || lnk.domain || "baglanti"}.txt`,
                site_title: state.pageTitle,
            },
        ]);
    });

    row.querySelector(".dl-link-content-btn").addEventListener("click", () => {
        enqueueDownloads([
            {
                item_type: "link_content",
                url: lnk.url,
                referer: pageReferer || state.currentUrl,
                filename: lnk.text || lnk.domain || "baglanti_icerigi",
                site_title: state.pageTitle,
            },
        ], null, true);
    });

    return row;
}

// ============================================================================
// RENDER DEDICATED LINKS TAB
// ============================================================================

function getFilteredLinks() {
    const catFilter = linkCategoryFilter.value;
    const query = (linkSearchInput.value || "").trim().toLowerCase();

    return state.links.filter((l) => {
        if (catFilter === "cloud_file" && l.category !== "cloud" && l.category !== "file") {
            return false;
        }
        if (catFilter === "media" && l.category !== "video" && l.category !== "image") {
            return false;
        }
        if (catFilter === "external" && !l.is_external) {
            return false;
        }
        if (catFilter === "webpage" && l.category !== "webpage") {
            return false;
        }
        if (query) {
            const hay = `${l.text} ${l.url} ${l.domain} ${l.category_label}`.toLowerCase();
            if (!hay.includes(query)) return false;
        }
        return true;
    });
}

function renderLinksTab() {
    linksListContainer.innerHTML = "";
    const filtered = getFilteredLinks();
    if (filtered.length === 0) {
        linksListContainer.innerHTML = `<div class="queue-empty">Seçili filtreye uygun bağlantı (link) bulunamadı.</div>`;
        return;
    }

    filtered.forEach((lnk) => {
        linksListContainer.appendChild(createLinkRowElement(lnk, state.currentUrl));
    });
}

linkCategoryFilter.addEventListener("change", () => {
    renderLinksTab();
    updateToolbarStatsAndMainAction();
});

linkSearchInput.addEventListener("input", () => {
    renderLinksTab();
    updateToolbarStatsAndMainAction();
});

// ============================================================================
// FILTERS, COUNTS & TOOLBAR ACTIONS
// ============================================================================

function isItemVisible(item) {
    if (item.loadFailed) return false;
    if (state.onlyUpgraded && !item.is_upgraded) return false;

    const minDim = state.minSize;
    if (minDim > 0 && (item.loadedWidth > 0 || item.loadedHeight > 0)) {
        if (!item.is_upgraded && item.loadedWidth < minDim && item.loadedHeight < minDim) {
            return false;
        }
        if (item.loadedWidth < 32 && item.loadedHeight < 32) {
            return false;
        }
    }
    return true;
}

function applyFiltersAndUpdateStats() {
    let visibleImgCount = 0;
    state.images.forEach((item) => {
        const visible = isItemVisible(item);
        if (item.cardEl) {
            item.cardEl.classList.toggle("hidden", !visible);
        }
        if (visible) visibleImgCount++;
    });

    countImagesEl.textContent = String(visibleImgCount);
    countVideosEl.textContent = String(state.videos.length);
    countTextsEl.textContent = String(state.texts.length);
    countLinksEl.textContent = String(state.links.length);

    updateToolbarStatsAndMainAction();
}

function updateToolbarStatsAndMainAction() {
    const visibleImgCount = state.images.filter((i) => isItemVisible(i)).length;
    const hiddenImgCount = state.images.length - visibleImgCount;

    if (state.activeTab === "images") {
        statsBadge.textContent =
            `${visibleImgCount} görsel` + (hiddenImgCount > 0 ? ` (${hiddenImgCount} küçük gizlendi)` : "");
        downloadAllBtn.textContent = `⬇ Görünen Görselleri İndir (${visibleImgCount})`;
        downloadAllBtn.disabled = visibleImgCount === 0;
    } else if (state.activeTab === "videos") {
        statsBadge.textContent = `${state.videos.length} video bulundu`;
        downloadAllBtn.textContent = `⬇ Tüm Videoları Sırayla İndir (${state.videos.length})`;
        downloadAllBtn.disabled = state.videos.length === 0;
    } else if (state.activeTab === "texts") {
        statsBadge.textContent = `${state.texts.length} metin bloğu • ${state.links.length} link`;
        downloadAllBtn.textContent = `⬇ Tüm Sayfa Metnini (.txt) İndir`;
        downloadAllBtn.disabled = state.texts.length === 0;
    } else if (state.activeTab === "links") {
        const filteredLinks = getFilteredLinks();
        statsBadge.textContent = `${filteredLinks.length} bağlantı gösteriliyor`;
        downloadAllBtn.textContent = `⬇ Görünen Linkleri (.txt) İndir (${filteredLinks.length})`;
        downloadAllBtn.disabled = filteredLinks.length === 0;
    }
}

// ============================================================================
// SMART DOWNLOAD QUEUE & PROGRESS POLLING
// ============================================================================

async function enqueueDownloads(items, singleCardEl = null, openQueueDrawer = false) {
    if (!items || items.length === 0) return;

    if (singleCardEl) {
        singleCardEl.classList.add("queued");
        const hintPill = singleCardEl.querySelector(".hint-pill");
        if (hintPill) hintPill.textContent = "⏳ Sıraya Alındı...";
    }

    if (openQueueDrawer || items.length > 1) {
        queuePanel.classList.remove("hidden");
    }

    try {
        const res = await fetch("/api/queue/add", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ items }),
        });
        const data = await res.json();
        if (!res.ok || data.error) {
            throw new Error(data.error || "Kuyruğa eklenemedi");
        }

        if (items.length > 1) {
            showToast(`📥 ${items.length} öğe indirme sırasına eklendi.`);
        } else {
            const firstTask = (data.tasks || [])[0];
            if (firstTask && firstTask.is_large) {
                queuePanel.classList.remove("hidden");
                showToast(`⏳ Büyük dosya / medya indirme sırasına alındı: ${firstTask.filename}`);
            }
        }

        await pollQueueStatus();
    } catch (err) {
        if (singleCardEl) {
            singleCardEl.classList.remove("queued");
        }
        showToast(`Hata: ${err.message}`, true);
    }
}

async function pollQueueStatus() {
    try {
        const res = await fetch("/api/queue/status");
        const data = await res.json();
        state.queueTasks = data.tasks || [];
        const counts = data.counts || { queued: 0, downloading: 0, completed: 0, failed: 0 };
        const activeOrQueued = (counts.queued || 0) + (counts.downloading || 0);

        queueBadge.textContent = String(activeOrQueued);
        toggleQueueBtn.classList.toggle("has-active", activeOrQueued > 0);

        queueSummaryText.textContent =
            activeOrQueued > 0
                ? `${counts.downloading} indiriliyor, ${counts.queued} sırada bekliyor (Tamamlanan: ${counts.completed})`
                : `Tamamlanan: ${counts.completed} • Sırada bekleyen yok`;

        renderQueuePanelItems(state.queueTasks);

        // Update cards & fire completion toast once per task
        state.queueTasks.forEach((t) => {
            const card = urlToCardMap.get(t.url);
            if (card) {
                const hintPill = card.querySelector(".hint-pill");
                const statusBadge = card.querySelector(".badge-status");
                if (t.status === "queued") {
                    card.classList.add("queued");
                    if (hintPill) hintPill.textContent = `⏳ Sırada #${t.queue_position || 1}`;
                } else if (t.status === "downloading") {
                    card.classList.remove("queued");
                    card.classList.add("downloading");
                    if (hintPill) hintPill.textContent = `⬇ %${Math.round(t.progress)}`;
                } else if (t.status === "completed") {
                    card.classList.remove("queued", "downloading");
                    card.classList.add("downloaded");
                    state.downloadedUrls.add(t.url);
                    if (statusBadge) statusBadge.classList.remove("hidden");
                    if (hintPill) hintPill.textContent = "✓ Tekrar İndir";
                } else if (t.status === "failed" || t.status === "cancelled") {
                    card.classList.remove("queued", "downloading");
                    if (hintPill) hintPill.textContent = "⬇ Tıkla & İndir";
                }
            }

            if (!state.notifiedTaskIds.has(t.id)) {
                if (t.status === "completed") {
                    state.notifiedTaskIds.add(t.id);
                    // Only show individual toast if not flooding from 50 items at once
                    if (activeOrQueued < 5) {
                        showToast(`✓ İndirildi: ${t.filename} (${formatSizeKB(t.size_kb)})`, false, t.saved_path);
                    }
                } else if (t.status === "failed") {
                    state.notifiedTaskIds.add(t.id);
                    showToast(`✕ İndirme Hatası (${t.filename}): ${t.error}`, true);
                }
            }
        });

        if (activeOrQueued > 0) {
            clearTimeout(state.queuePollTimer);
            state.queuePollTimer = setTimeout(pollQueueStatus, 650);
        }
    } catch (err) {
        console.error("Kuyruk durumu alınamadı:", err);
    }
}

function formatSizeKB(kb) {
    if (!kb || kb <= 0) return "0 KB";
    if (kb >= 1024) {
        return `${(kb / 1024).toFixed(2)} MB`;
    }
    return `${kb} KB`;
}

function formatBytes(bytes) {
    if (!bytes || bytes <= 0) return "0 KB";
    const mb = bytes / (1024 * 1024);
    if (mb >= 1) return `${mb.toFixed(2)} MB`;
    return `${(bytes / 1024).toFixed(1)} KB`;
}

function renderQueuePanelItems(tasks) {
    if (!tasks || tasks.length === 0) {
        queueItemsList.innerHTML = `<div class="queue-empty">Henüz kuyrukta indirme yok.</div>`;
        return;
    }

    const typeIcons = {
        image: "🖼️",
        video: "🎬",
        text: "📄",
        link_txt: "📝",
        link_content: "📥",
    };

    queueItemsList.innerHTML = "";
    tasks.forEach((t) => {
        const div = document.createElement("div");
        div.className = `queue-item status-${t.status}`;

        let statusBadgeHtml = "";
        if (t.status === "queued") {
            statusBadgeHtml = `<span class="q-badge q-badge-queued">⏳ Sırada #${t.queue_position || 1}</span>`;
        } else if (t.status === "downloading") {
            statusBadgeHtml = `<span class="q-badge q-badge-downloading">⬇ %${t.progress}</span>`;
        } else if (t.status === "completed") {
            statusBadgeHtml = `<span class="q-badge q-badge-completed">✓ Tamamlandı</span>`;
        } else if (t.status === "failed") {
            statusBadgeHtml = `<span class="q-badge q-badge-failed">✕ Hata</span>`;
        } else if (t.status === "cancelled") {
            statusBadgeHtml = `<span class="q-badge q-badge-queued">İptal</span>`;
        }

        const largeBadgeHtml = t.is_large
            ? `<span class="q-badge q-badge-large" title="Büyük dosya veya video akışı — sırayla indirilir">Büyük Dosya</span>`
            : "";

        const progressWidth = t.status === "completed" ? 100 : Math.max(0, Math.min(100, t.progress || 0));

        let bottomLeftText = "";
        if (t.status === "queued") {
            bottomLeftText = t.queue_reason || "Sırada bekliyor...";
        } else if (t.status === "downloading") {
            const totStr = t.total_bytes > 0 ? ` / ${formatBytes(t.total_bytes)}` : "";
            const speedStr = t.speed_kbps > 0 ? ` • ${formatSizeKB(t.speed_kbps)}/sn` : "";
            bottomLeftText = `${formatBytes(t.downloaded_bytes)}${totStr}${speedStr}`;
        } else if (t.status === "completed") {
            bottomLeftText = `Boyut: ${formatSizeKB(t.size_kb)}`;
        } else if (t.status === "failed") {
            bottomLeftText = t.error || "Başarısız";
        }

        div.innerHTML = `
            <div class="queue-item-top">
                <span class="queue-item-name" title="${escapeHtml(t.filename)}">
                    ${typeIcons[t.item_type] || "📦"} ${escapeHtml(t.filename)}
                </span>
                <div class="queue-item-badges">
                    ${largeBadgeHtml}
                    ${statusBadgeHtml}
                </div>
            </div>
            <div class="queue-progress-track">
                <div class="queue-progress-bar" style="width: ${progressWidth}%;"></div>
            </div>
            <div class="queue-item-bottom">
                <span>${escapeHtml(bottomLeftText)}</span>
                <div class="queue-item-actions">
                    ${t.status === "completed" && t.saved_path
                        ? `<button type="button" class="btn-xs open-item-btn">📂 Göster</button>`
                        : ""
                    }
                    ${t.status === "queued" || t.status === "downloading"
                        ? `<button type="button" class="btn-xs btn-danger-outline cancel-item-btn">✕ İptal</button>`
                        : ""
                    }
                </div>
            </div>
        `;

        const openBtn = div.querySelector(".open-item-btn");
        if (openBtn) {
            openBtn.addEventListener("click", () => {
                fetch("/api/open-folder", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ path: t.saved_path }),
                });
            });
        }

        const cancelBtn = div.querySelector(".cancel-item-btn");
        if (cancelBtn) {
            cancelBtn.addEventListener("click", async () => {
                await fetch("/api/queue/cancel", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ task_id: t.id }),
                });
                pollQueueStatus();
            });
        }

        queueItemsList.appendChild(div);
    });
}

toggleQueueBtn.addEventListener("click", () => {
    queuePanel.classList.toggle("hidden");
    pollQueueStatus();
});

queueCloseBtn.addEventListener("click", () => {
    queuePanel.classList.add("hidden");
});

queueClearBtn.addEventListener("click", async () => {
    await fetch("/api/queue/clear", { method: "POST" });
    pollQueueStatus();
});

queueCancelAllBtn.addEventListener("click", async () => {
    await fetch("/api/queue/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_id: "all" }),
    });
    pollQueueStatus();
});

// ============================================================================
// PAGINATION CONTROLS
// ============================================================================

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

// ============================================================================
// LIGHTBOX MODAL (IMAGE & VIDEO PREVIEW)
// ============================================================================

function openImageLightbox(item, cardEl) {
    state.activeLightboxItem = { type: "image", item, cardEl };
    lightboxTitle.textContent = `${item.filename} — ${item.full_url}`;
    lightboxVideo.pause();
    lightboxVideo.classList.add("hidden");
    lightboxImg.classList.remove("hidden");
    lightboxImg.src = buildProxyUrl(item.full_url, item.referer || state.currentUrl, item.thumb_url);
    lightboxModal.classList.remove("hidden");
}

function openVideoLightbox(vid, cardEl) {
    state.activeLightboxItem = { type: "video", item: vid, cardEl };
    lightboxTitle.textContent = `${vid.title} — ${vid.video_url}`;
    lightboxImg.classList.add("hidden");
    lightboxVideo.classList.remove("hidden");

    if (vid.source_type === "direct") {
        lightboxVideo.src = buildVideoProxyUrl(vid.video_url, vid.referer || state.currentUrl);
        lightboxVideo.play().catch(() => {});
    } else {
        lightboxVideo.src = "";
        showToast("Bu bir platform/embed videosudur. '⬇ İndir' butonuna basarak doğrudan MP4 olarak indirebilirsiniz.");
    }
    lightboxModal.classList.remove("hidden");
}

function closeLightbox() {
    lightboxModal.classList.add("hidden");
    lightboxImg.src = "";
    lightboxVideo.pause();
    lightboxVideo.src = "";
    state.activeLightboxItem = null;
}

lightboxCloseBtn.addEventListener("click", closeLightbox);
lightboxBackdrop.addEventListener("click", closeLightbox);
lightboxDownloadBtn.addEventListener("click", () => {
    if (!state.activeLightboxItem) return;
    const { type, item, cardEl } = state.activeLightboxItem;
    if (type === "image") {
        enqueueDownloads([
            {
                item_type: "image",
                url: item.full_url,
                thumb_url: item.thumb_url,
                referer: item.referer || state.currentUrl,
                filename: item.filename,
                site_title: state.pageTitle,
            },
        ], cardEl);
    } else if (type === "video") {
        enqueueDownloads([
            {
                item_type: "video",
                url: item.video_url,
                referer: item.referer || state.currentUrl,
                filename: item.filename,
                site_title: state.pageTitle,
                source_type: item.source_type,
                size_bytes: item.size_bytes || 0,
            },
        ], cardEl, true);
    }
});

window.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !lightboxModal.classList.contains("hidden")) {
        closeLightbox();
    }
});

// ============================================================================
// TOP-LEVEL & BULK EVENT LISTENERS
// ============================================================================

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

thresholdSelect.addEventListener("change", () => {
    const val = parseInt(thresholdSelect.value, 10) || 5;
    fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ large_file_threshold_mb: val }),
    });
    showToast(`Büyük dosya sıralama eşiği ≥ ${val} MB olarak ayarlandı.`);
});

subfolderCb.addEventListener("change", () => {
    fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ create_site_subfolder: subfolderCb.checked }),
    });
});

includeLinksTxtCb.addEventListener("change", () => {
    state.includeLinksInTxt = includeLinksTxtCb.checked;
    fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ include_links_in_txt: includeLinksTxtCb.checked }),
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

// Main Toolbar "Download All" Button (Context-Aware per Active Tab)
downloadAllBtn.addEventListener("click", () => {
    if (state.activeTab === "images") {
        const visibleItems = state.images.filter((item) => isItemVisible(item));
        if (visibleItems.length === 0) return;
        const batch = visibleItems.map((item) => ({
            item_type: "image",
            url: item.full_url,
            thumb_url: item.thumb_url,
            referer: item.referer || state.currentUrl,
            filename: item.filename,
            site_title: state.pageTitle,
        }));
        enqueueDownloads(batch, null, true);
    } else if (state.activeTab === "videos") {
        downloadAllVideosBtn.click();
    } else if (state.activeTab === "texts") {
        downloadFullTextBtn.click();
    } else if (state.activeTab === "links") {
        exportFilteredLinksTxtBtn.click();
    }
});

// Video Tab Bulk Download
downloadAllVideosBtn.addEventListener("click", () => {
    if (state.videos.length === 0) return;
    const batch = state.videos.map((vid) => ({
        item_type: "video",
        url: vid.video_url,
        referer: vid.referer || state.currentUrl,
        filename: vid.filename,
        site_title: state.pageTitle,
        source_type: vid.source_type,
        size_bytes: vid.size_bytes || 0,
    }));
    enqueueDownloads(batch, null, true);
});

// Text Tab Bulk Actions
downloadFullTextBtn.addEventListener("click", () => {
    if (state.texts.length === 0) return;
    const fullEntry = state.texts[0];
    enqueueDownloads([
        {
            item_type: "text",
            url: state.currentUrl,
            referer: state.currentUrl,
            filename: fullEntry.filename || "sayfa_tam_metin.txt",
            site_title: state.pageTitle,
            text_title: fullEntry.title,
            text_content: fullEntry.text,
            links_list: fullEntry.links || state.links,
            include_links: includeLinksTxtCb.checked,
        },
    ]);
});

downloadAllLinksTxtBtn.addEventListener("click", () => {
    if (state.links.length === 0) {
        showToast("Sayfada indirilecek bağlantı bulunamadı.", true);
        return;
    }
    const linksText = state.links
        .map((l, i) => `${i + 1}. [${l.category_label}] ${l.text}\n   URL: ${l.url}`)
        .join("\n\n");
    enqueueDownloads([
        {
            item_type: "text",
            url: state.currentUrl,
            referer: state.currentUrl,
            filename: `${state.pageTitle || "sayfa"}_tum_linkler.txt`,
            site_title: state.pageTitle,
            text_title: `${state.pageTitle} — Tüm Bağlantılar (${state.links.length} Adet)`,
            text_content: linksText,
            links_list: [],
            include_links: false,
        },
    ]);
});

// Links Tab Bulk Actions
exportFilteredLinksTxtBtn.addEventListener("click", () => {
    const filtered = getFilteredLinks();
    if (filtered.length === 0) return;
    const linksText = filtered
        .map((l, i) => `${i + 1}. [${l.category_label}] ${l.text}\n   URL: ${l.url}`)
        .join("\n\n");
    enqueueDownloads([
        {
            item_type: "text",
            url: state.currentUrl,
            referer: state.currentUrl,
            filename: `${state.pageTitle || "sayfa"}_secili_linkler.txt`,
            site_title: state.pageTitle,
            text_title: `${state.pageTitle} — Filtrelenen Bağlantılar (${filtered.length} Adet)`,
            text_content: linksText,
            links_list: [],
            include_links: false,
        },
    ]);
});

downloadFilteredLinksContentBtn.addEventListener("click", () => {
    const filtered = getFilteredLinks();
    if (filtered.length === 0) return;
    const batch = filtered.map((l, idx) => ({
        item_type: "link_content",
        url: l.url,
        referer: state.currentUrl,
        filename: l.text || l.domain || `baglanti_${idx + 1}`,
        site_title: state.pageTitle,
    }));
    enqueueDownloads(batch, null, true);
});

function escapeHtml(str) {
    return String(str || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

// ============================================================================
// GITHUB AUTO-UPDATER
// ============================================================================

const githubUpdateBtn = document.getElementById("github-update-btn");
const updateBtnLabel = document.getElementById("update-btn-label");
const updateDot = document.getElementById("update-dot");
const updateModal = document.getElementById("update-modal");
const updateBackdrop = document.getElementById("update-backdrop");
const updateCloseBtn = document.getElementById("update-close-btn");
const updateRepoName = document.getElementById("update-repo-name");
const updateLocalSha = document.getElementById("update-local-sha");
const updateRemoteSha = document.getElementById("update-remote-sha");
const updateStatusBanner = document.getElementById("update-status-banner");
const updateChangelogList = document.getElementById("update-changelog-list");
const updateCheckAgainBtn = document.getElementById("update-check-again-btn");
const updateApplyBtn = document.getElementById("update-apply-btn");

async function checkForGitHubUpdates(silent = false) {
    if (!silent) {
        updateStatusBanner.className = "update-banner";
        updateStatusBanner.textContent = "⏳ GitHub deposu (yogruce/threadsnap) kontrol ediliyor...";
        updateCheckAgainBtn.disabled = true;
    }

    try {
        const res = await fetch("/api/update/check", { method: "POST" });
        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(data.error || "Güncelleme kontrolü yapılamadı.");
        }

        updateRepoName.textContent = `${data.repo || "yogruce/threadsnap"} (${data.branch || "main"})`;
        updateLocalSha.textContent = `#${data.local_commit || "?"}`;
        updateRemoteSha.textContent = `#${data.remote_commit || "?"}`;

        updateChangelogList.innerHTML = "";
        (data.changelog || []).forEach((line) => {
            const li = document.createElement("li");
            li.textContent = `• ${line}`;
            updateChangelogList.appendChild(li);
        });
        if (!data.changelog || data.changelog.length === 0) {
            updateChangelogList.innerHTML = "<li>Değişiklik kaydı bulunamadı.</li>";
        }

        if (data.has_update) {
            updateDot.classList.remove("hidden");
            githubUpdateBtn.classList.add("update-available");
            updateBtnLabel.textContent = "Güncelleme Var!";
            updateStatusBanner.className = "update-banner has-new";
            updateStatusBanner.textContent = `✨ GitHub'da yeni bir sürüm mevcut! (${data.behind_count} yeni güncelleme). Tek tıkla güncelleyebilirsiniz.`;
            updateApplyBtn.textContent = "🚀 Şimdi Güncelle & Yeniden Başlat";
            if (silent) {
                showToast("✨ GitHub üzerinde yeni bir uygulama güncellemesi mevcut! Üstteki '🔄 Güncelle' butonuna tıklayın.");
            }
        } else {
            updateDot.classList.add("hidden");
            githubUpdateBtn.classList.remove("update-available");
            updateBtnLabel.textContent = "Güncelle";
            updateStatusBanner.className = "update-banner up-to-date";
            updateStatusBanner.textContent = "✓ Uygulamanız şu anda GitHub üzerindeki en güncel sürümde.";
            updateApplyBtn.textContent = "🔄 Yine de GitHub'dan Yenile & Başlat";
        }
    } catch (err) {
        if (!silent) {
            updateStatusBanner.className = "update-banner";
            updateStatusBanner.textContent = `⚠️ ${err.message}`;
        }
    } finally {
        updateCheckAgainBtn.disabled = false;
    }
}

async function applyGitHubUpdate() {
    updateApplyBtn.disabled = true;
    updateCheckAgainBtn.disabled = true;
    const origText = updateApplyBtn.textContent;
    updateApplyBtn.textContent = "⏳ GitHub'dan İndiriliyor ve Kuruluyor...";
    updateStatusBanner.className = "update-banner";
    updateStatusBanner.textContent = "⏳ Güncel kodlar ve paketler GitHub'dan çekiliyor, lütfen bekleyin...";

    try {
        const res = await fetch("/api/update/apply", { method: "POST" });
        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(data.error || "Güncelleme uygulanamadı.");
        }

        updateStatusBanner.className = "update-banner up-to-date";
        updateStatusBanner.textContent = `✓ ${data.message} Uygulama yeniden başlatılıyor...`;
        showToast("✓ Güncelleme tamamlandı! Uygulama yeniden başlatılıyor...");

        await fetch("/api/update/restart", { method: "POST" });
        setTimeout(() => {
            window.location.reload();
        }, 1500);
    } catch (err) {
        updateStatusBanner.className = "update-banner has-new";
        updateStatusBanner.textContent = `✕ Hata: ${err.message}`;
        showToast(`Güncelleme hatası: ${err.message}`, true);
        updateApplyBtn.disabled = false;
        updateCheckAgainBtn.disabled = false;
        updateApplyBtn.textContent = origText;
    }
}

githubUpdateBtn.addEventListener("click", () => {
    updateModal.classList.remove("hidden");
    checkForGitHubUpdates(false);
});

updateCheckAgainBtn.addEventListener("click", () => {
    checkForGitHubUpdates(false);
});

updateApplyBtn.addEventListener("click", () => {
    applyGitHubUpdate();
});

updateCloseBtn.addEventListener("click", () => {
    updateModal.classList.add("hidden");
});

updateBackdrop.addEventListener("click", () => {
    updateModal.classList.add("hidden");
});

initSettings();
// Silently check for GitHub updates 2 seconds after startup
setTimeout(() => checkForGitHubUpdates(true), 2000);

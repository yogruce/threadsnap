# 🚀 ThreadSnap / ImgCatcher Pro — Görsel, Video, Metin & Link İndirici

**ImgCatcher Pro**, verilen herhangi bir web sitesi veya forum konusundaki **yüksek çözünürlüklü görselleri (`full-res`)**, **videoları**, **metin bloklarını/forum mesajlarını** ve **sayfa içi bağlantıları (`link`)** otomatik yakalayan, kendi masaüstü arayüzünde sekme bazlı listeleyen ve **Akıllı İndirme Kuyruğu** ile bilgisayarınıza indiren gelişmiş bir masaüstü uygulamasıdır.

---

## ✨ Özellikler

- **🖼️ Akıllı Thumbnail → HD Görsel Eşleştirme:**
  - Sayfadaki `<img>`, `<picture>`, `srcset`, `data-src`, `data-full` ve etrafındaki `<a>` / Lightbox bağlantılarını analiz eder.
  - Popüler forum görsel servislerinin (`pixhost.to`, `imgbox.com`, `ibb.co`, `postimg.cc`, `imagebam.com`, `imx.to`, `imagetwist`, `vipr.im` vb.) HTML görüntüleyici sayfalarını otomatik çözümleyerek doğrudan orijinal yüksek çözünürlüklü görseli indirir.
- **🎬 Video Yakalayıcı & İndirici (Video Downloader):**
  - Sayfadaki `<video>`, `<source>`, doğrudan video bağlantılarını (`.mp4`, `.webm`, `.mkv`, `.mov`, `.m3u8` vb.), OpenGraph video etiketlerini ve gömülü platform videolarını (`YouTube`, `Vimeo`, `Dailymotion`, `Streamable`, `Redgifs`, `Twitter/X` vb.) otomatik tespit eder.
  - Doğrudan HTTP akışı ve entegre `yt-dlp` motoru ile videoları gerçek zamanlı ilerleme çubuğuyla indirir veya uygulama içi oynatıcıda önizler.
- **📝 Metin & Bağlantı (Link) Yakalayıcı:**
  - Forum mesajlarını, makaleleri veya tüm sayfa metnini temiz ve okunabilir bloklar halinde ayrıştırır.
  - **Link Belirtme:** Her metin bloğunun içinde geçen bağlantıları (`📦 Dosya/Arşiv`, `☁️ Bulut Host`, `🎬 Video`, `🖼️ Görsel`, `🌐 Web Sayfası` etiketleriyle) özel olarak vurgular ve listeler.
  - **Esnek İndirme Seçenekleri:**
    - Metni (ve istenirse içindeki link listesini) tek tıkla düzenli **`.txt`** dosyası olarak indirme.
    - Sadece tespit edilen linklerin listesini **`.txt`** olarak kaydetme.
    - **📥 Linkin İçeriğini İndir:** Belirtilen link bir dosyaya/görsele/videoya/arşive işaret ediyorsa doğrudan hedef dosyayı, bir web sayfasına işaret ediyorsa o sayfanın metin ve bağlantı içeriğini indirir veya uygulama içinde tarar.
- **📥 Akıllı İndirme Sırası & Büyük Dosya Kuyruğu (`DownloadQueueManager`):**
  - Çoklu indirmelerde ve belirlenen eşik değerinden (varsayılan `≥ 5 MB`, arayüzden değiştirilebilir) büyük dosyalarda veya videolarda indirmeleri **otomatik olarak sıraya (`Sırada #1, #2...`) alır**.
  - Sağ altta açılan **İndirme Sırası Paneli** üzerinden anlık yüzde (`%`), indirilen boyut (`MB`), hız (`KB/sn`) takip edilebilir; sıradaki indirmeler iptal edilebilir veya tamamlananlar klasörde gösterilebilir.
- **📄 Otomatik Forum & Sayfalama (Pagination) Gezgini:**
  - Forum ve galeri sitelerindeki **Önceki Sayfa**, **Sonraki Sayfa** ve **Sayfa Numaralarını (`1, 2, 3...`)** otomatik algılar ve **➕ Sonraki Sayfayı Altına Ekle** desteği sunar.

---

## 🚀 Kurulum ve Çalıştırma

### 1. Gereksinimleri Yükleyin
```bash
pip install -r requirements.txt
```

### 2. Uygulamayı Başlatın
Windows üzerinde doğrudan **`Baslat.bat`** dosyasına çift tıklayabilir veya terminalden çalıştırabilirsiniz:
```bash
python app.py
```

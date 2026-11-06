# 🖼️ ThreadSnap — Akıllı Forum & Web Görsel Yakalayıcı

**ThreadSnap**, verilen herhangi bir web sitesi veya forum konusundaki küçük önizleme görsellerini (`thumbnail`) ve bunların bağlı olduğu **yüksek çözünürlüklü orijinal görselleri (`full-res`)** otomatik yakalayan, kendi masaüstü arayüzünde ızgara olarak listeleyen ve tıklanan görseli **tek tıkla** belirlediğiniz klasöre indiren bir masaüstü uygulamasıdır.

---

## ✨ Özellikler

- **🎯 Akıllı Thumbnail → HD Görsel Eşleştirme:**
  - Sayfadaki `<img>`, `<picture>`, `srcset`, `data-src`, `data-full` ve etrafındaki `<a>` / Lightbox bağlantılarını analiz eder.
  - Popüler forum görsel servislerinin (`pixhost.to`, `imgbox.com`, `ibb.co`, `postimg.cc`, `imagebam.com`, `imx.to`, `imagetwist`, `vipr.im` vb.) HTML görüntüleyici sayfalarını otomatik çözümleyerek doğrudan orijinal yüksek çözünürlüklü görseli indirir.
- **⚡ Tek Tıkla Anında İndirme:**
  - Arayüzdeki herhangi bir thumbnail'e tıkladığınız anda "Farklı Kaydet" penceresiyle uğraşmadan görseli seçili klasörünüze (isteğe bağlı site alt klasörüyle) kaydeder.
- **📄 Otomatik Forum & Sayfalama (Pagination) Gezgini:**
  - Forum ve galeri sitelerindeki **Önceki Sayfa**, **Sonraki Sayfa** ve **Sayfa Numaralarını (`1, 2, 3...`)** otomatik algılar.
  - **➕ Sonraki Sayfayı Altına Ekle** özelliğiyle mevcut görselleri temizlemeden sonraki sayfanın görsellerini aynı ızgaraya ekleyebilir veya doğrudan istediğiniz sayfa numarasına atlayabilirsiniz.
- **🛡️ Dahili Proxy & Gerçek Görsel Doğrulaması (Pillow):**
  - Referer / Hotlink korumalı sitelerdeki görselleri dahili proxy katmanıyla sorunsuz görüntüler ve indirilen her dosyanın gerçek bir resim olduğunu `Pillow` ile doğrular.
- **🔍 Boyut Filtresi & Tam Ekran Önizleme (Lightbox):**
  - Küçük ikonları, emojileri ve avatarları tek tıkla gizleyebilir, indirmeden önce büyüteç ikonuyla tam ekran inceleyebilir veya görünen tüm görselleri toplu indirebilirsiniz.

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

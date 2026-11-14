# Philips TV Hızlandırıcı

Yavaşlayan ve donan eski Philips Smart TV'leri, aynı ağdaki bilgisayardan bağlanarak hızlandıran araç.

TV'nin türünü kendisi tanır:

| TV türü | Nasıl anlaşılır | Araç ne yapar |
|---|---|---|
| **Philips Android TV** (yaklaşık 2015 ve sonrası) | Ana ekranda Google Play / Android TV logosu | ADB ile bağlanır: animasyonları hızlandırır, önbelleği temizler, RAM yiyen gereksiz uygulamaları kapatır, arka planı temizler, yeniden başlatır |
| **Eski NetTV / Saphi** (yaklaşık 2015 öncesi, Linux) | "Smart TV" menüsü, Google Play yok | Sistem kapalı olduğu için dışarıdan ayar değiştirilemez; en etkili adımları sırayla gösterir |

Hiçbir şey **silinmez**. Uygulamalar yalnızca devre dışı bırakılır ve `geri-al` komutu her şeyi eski haline döndürür. TV'nin kanal, tuner ve ayar bileşenlerine (`org.droidtv.*`, `com.philips.*`), Android sistemine ve Google Play Hizmetleri'ne dokunulmaz.

## Gereksinimler

- Python 3.9 veya üzeri (ek paket gerekmez)
- Android TV için **ADB** (Android Platform Tools):
  - Windows: `winget install Google.PlatformTools`
  - macOS: `brew install android-platform-tools`
  - Linux: `sudo apt install adb`
- Bilgisayar ve TV aynı modeme/Wi-Fi'ye bağlı olmalı

## Android TV'de bağlantıyı açma (bir kerelik)

1. TV'de **Ayarlar > Tüm ayarlar > Genel ayarlar > Hakkında** (bazı modellerde *Ayarlar > Cihaz Tercihleri > Hakkında*) bölümüne girin.
2. **Yapı numarası** (Build) satırına art arda **7 kez** basın. "Artık bir geliştiricisiniz" mesajı çıkar.
3. Bir geri gidip **Geliştirici seçenekleri** menüsünü açın.
4. **USB hata ayıklama**yı açın. Menüde varsa **Ağ üzerinden hata ayıklama / ADB over network** seçeneğini de açın.
5. İlk bağlantıda TV ekranında "USB hata ayıklamaya izin verilsin mi?" sorusu çıkar. **Her zaman bu bilgisayardan izin ver** seçeneğini işaretleyip onaylayın.

TV'nin IP adresini **Ayarlar > Ağ > Ağ ayarlarını görüntüle** bölümünde görebilirsiniz.

## Kullanım

```bash
# Etkileşimli menü: TV'yi bulur, türünü tanır, ne yapılacağını sorar
python -m tvhiz

# Ya da komutlarla:
python -m tvhiz tara                       # ağdaki Philips TV'leri bul
python -m tvhiz durum 192.168.1.50         # RAM, depolama, en çok RAM yiyen uygulamalar
python -m tvhiz hizlandir 192.168.1.50     # her adımı sorarak hızlandır
python -m tvhiz hizlandir 192.168.1.50 -e  # sormadan önerilen ayarları uygula
python -m tvhiz geri-al 192.168.1.50       # tüm değişiklikleri geri al
python -m tvhiz yeniden-baslat 192.168.1.50
python -m tvhiz liste                      # kapatılabilecek uygulama listesi
python -m tvhiz ipuclari                   # eski NetTV modeller için rehber
```

Ek seçenekler:
- `--animasyon-kapat`: animasyonları 0.5x yerine tamamen kapatır.
- `--paket com.ornek.uygulama`: `durum` çıktısında RAM yediğini gördüğünüz başka bir uygulamayı da kapatır (tekrarlanabilir).

## `hizlandir` adımları

1. **Animasyonlar 0.5x**: menüler ve geçişler belirgin şekilde hızlanır.
2. **Önbellek temizliği** (`pm trim-caches`): depolama doluysa Android çok yavaşlar. Oturumlar ve uygulama verileri silinmez.
3. **Gereksiz uygulamaları kapatma**: özellikle *Öneriler* (`tvrecommendations`) ve *Backdrop* sürekli internetten içerik çekip RAM'i doldurur. "Önerilir" etiketli uygulamalar varsayılan olarak kapatılır. Chromecast, Netflix ve sesli arama gibi "isteğe bağlı" olanlar yalnızca siz onaylarsanız kapatılır.
4. **Arka plan uygulamalarını durdurma**.
5. **Yeniden başlatma**: önce/sonra boş RAM karşılaştırması gösterilir.

Yapılan değişiklikler `~/.tvhiz/<ip>.json` dosyasında saklanır. `geri-al` bu dosyayı kullanır.

## Ek öneriler (tüm modeller)

- TV'yi ara sıra **fişten çekip 2 dakika bekleyin**. Bekleme modu belleği temizlemez.
- **Yazılımı güncelleyin** (Ayarlar > Yazılımı güncelle).
- *Hızlı başlatma / Instant On*, *Wi-Fi ile aç*, *HbbTV* gibi kullanmadığınız özellikleri kapatın.
- Çok eski modellerde en büyük fark, HDMI'a takılan uygun fiyatlı bir Android TV / Google TV cihazıyla elde edilir.

## Geliştirme

```bash
python -m unittest discover -s tests -v
```

Testler sahte bir Philips TV (ADB ve JointSPACE) ile çalışır, gerçek TV gerektirmez.

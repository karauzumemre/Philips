"""Eski (Android olmayan) Philips NetTV / Saphi modeller için rehber.

Bu modellerin işletim sistemi kapalıdır; dışarıdan uygulama kapatmaya veya
önbellek silmeye izin verilmez. JointSPACE API yalnızca kumanda tuşu
göndermeye izin verir. Bu nedenle en etkili yöntemleri adım adım listeliyoruz
ve kumanda tuşlarıyla TV'yi uzaktan bekleme moduna alıp açabiliyoruz.
"""

from __future__ import annotations

import json
import urllib.request

TIPS = [
    ("İnternet belleğini temizleyin (en etkili adım)",
     "Kumanda: Ayarlar (dişli) > Genel ayarlar > İnternet belleğini sil.\n"
     "   Eski modellerde: Ev > Kurulum > Ağ ayarları > İnternet belleğini temizle.\n"
     "   Smart TV uygulamalarının biriktirdiği önbellek, çerez ve oturumları siler."),
    ("Tam güç döngüsü yapın",
     "TV'yi kapatın, fişten çekin, 2 dakika bekleyin, tekrar takın.\n"
     "   Bekleme modu belleği temizlemez; fişten çekmek temizler."),
    ("Yazılımı güncelleyin",
     "Ayarlar > Yazılımı güncelle > İnternetten ara.\n"
     "   İnternetten bulunamazsa philips.com.tr/support adresinden model numaranızla\n"
     "   güncellemeyi indirip FAT32 USB bellekle yükleyin."),
    ("Kullanmadığınız özellikleri kapatın",
     "- Ayarlar > Genel > Hızlı başlatma / Instant on: KAPALI (RAM'i boşaltır)\n"
     "   - Ayarlar > Ağ > Wi-Fi ile aç (WoWLAN) ve DMR/DLNA: KAPALI\n"
     "   - Ambilight+hue, HbbTV (Ayarlar > Kanallar > HbbTV): KAPALI\n"
     "   - Ses/Görüntü 'Akıllı' modları yerine 'Standart' kullanın."),
    ("Kanal listesini sadeleştirin",
     "Binlerce uydu kanalı yüklü ise menüler yavaşlar. Yalnızca izlediğiniz\n"
     "   uydu/paketleri yeniden kurun (Ayarlar > Kanallar > Uydu kurulumu)."),
    ("Son çare: Fabrika ayarlarına sıfırlama",
     "Ayarlar > Genel ayarlar > TV'yi yeniden kur. Tüm kanal ve ayarlar silinir\n"
     "   ama yıllar içinde biriken bozuk verileri de temizler."),
    ("Gerçek çözüm: Harici cihaz",
     "Eski NetTV'lerin işlemcisi bugünkü uygulamalar için yetersizdir. HDMI'a takılan\n"
     "   ucuz bir Android TV / Google TV kutusu veya stick ile TV'yi sadece ekran olarak\n"
     "   kullanmak, en büyük hız farkını yaratır."),
]


def print_tips() -> None:
    print("\nEski Philips NetTV / Saphi için hızlandırma adımları\n" + "=" * 52)
    for i, (title, body) in enumerate(TIPS, 1):
        print(f"\n{i}. {title}\n   {body}")
    print()


def send_key(ip: str, key: str, port: int = 1925, api: str = "1") -> bool:
    """JointSPACE ile kumanda tuşu gönderir (ör. 'Standby', 'Home', 'Back')."""
    req = urllib.request.Request(
        f"http://{ip}:{port}/{api}/input/key",
        data=json.dumps({"key": key}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=3) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False

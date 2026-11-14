"""Philips TV Hızlandırıcı - komut satırı arayüzü.

Kullanım:
  python -m tvhiz                  # etkileşimli menü
  python -m tvhiz tara             # ağdaki TV'leri bul
  python -m tvhiz durum IP         # RAM, depolama, RAM yiyen uygulamalar
  python -m tvhiz hizlandir IP     # adım adım hızlandırma
  python -m tvhiz geri-al IP       # tüm değişiklikleri geri al
  python -m tvhiz ipuclari         # eski NetTV modeller için rehber
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .android import BLOAT, AdbError, AndroidTV, is_protected
from .discovery import identify, scan
from .nettv import print_tips, send_key


def ask(question: str, default: bool = True, auto: bool = False) -> bool:
    if auto:
        return default
    hint = "E/h" if default else "e/H"
    try:
        ans = input(f"{question} [{hint}]: ").strip().lower()
    except EOFError:
        return default
    if not ans:
        return default
    return ans[0] in ("e", "y")


def header(text: str) -> None:
    print(f"\n{text}\n" + "-" * len(text))


# ---------------------------------------------------------------- komutlar

def cmd_scan(args) -> list:
    print("Ağ taranıyor (10-20 sn sürebilir)...")
    tvs = scan(args.ag)
    if not tvs:
        print(
            "TV bulunamadı. Kontrol edin:\n"
            "  - TV açık ve bilgisayarla aynı Wi-Fi/modemde mi?\n"
            "  - TV IP adresini biliyorsanız: python -m tvhiz durum 192.168.1.XX"
        )
        return []
    header(f"{len(tvs)} cihaz bulundu")
    for tv in tvs:
        print(" ", tv.summary())
    for tv in tvs:
        if tv.is_android and not tv.adb_ready:
            print(f"\n{tv.ip}: Android TV ama ADB kapalı. README'deki 'Geliştirici seçenekleri' adımlarını uygulayın.")
        elif tv.os_type == "nettv":
            print(f"\n{tv.ip}: Eski NetTV modeli. 'python -m tvhiz ipuclari' ile yapılacakları görün.")
    return tvs


def _connect(ip: str) -> AndroidTV:
    tv = AndroidTV(ip)
    print(f"{ip} adresindeki TV'ye bağlanılıyor... (TV ekranında izin sorusu çıkarsa onaylayın)")
    tv.connect()
    return tv


def _print_status(tv: AndroidTV) -> None:
    st = tv.status()
    header(f"{st.model or 'Philips Android TV'}  (Android {st.android})")
    ram_pct = 100 * st.ram_free_mb / st.ram_total_mb if st.ram_total_mb else 0
    print(f"  RAM       : {st.ram_free_mb} MB boş / {st.ram_total_mb} MB  (%{ram_pct:.0f} boş)")
    if st.storage_total_mb:
        print(f"  Depolama  : {st.storage_free_mb} MB boş / {st.storage_total_mb} MB")
    anim = ", ".join(f"{v if v not in ('', 'null') else '1'}" for v in st.animations.values())
    print(f"  Animasyon : {anim}")

    if st.top_memory:
        print("\n  En çok RAM kullanan uygulamalar:")
        for name, kb in st.top_memory:
            print(f"    {kb // 1024:>5} MB  {name}")

    header("Değerlendirme")
    problems = 0
    if st.ram_total_mb and ram_pct < 20:
        problems += 1
        print("  ! Boş RAM çok düşük -> donmaların ana sebebi. 'hizlandir' komutu RAM açar.")
    if st.storage_free_mb is not None and st.storage_free_mb < 500:
        problems += 1
        print("  ! Depolama neredeyse dolu (<500 MB). Android bu durumda ciddi yavaşlar.")
        print("    Önbellek temizliği ve kullanılmayan uygulamaları kaldırmak gerekir.")
    if any(v in ("", "null", "1", "1.0") for v in st.animations.values()):
        problems += 1
        print("  ! Animasyonlar tam hızda; düşürmek menüleri belirgin şekilde hızlandırır.")
    bloat = tv.present_bloat()
    if bloat:
        problems += 1
        print(f"  ! Kapatılabilecek {len(bloat)} gereksiz uygulama açık.")
    if not problems:
        print("  Belirgin bir sorun yok.")


def cmd_status(args) -> None:
    tv = _connect(args.ip)
    _print_status(tv)


def cmd_optimize(args) -> None:
    tv = _connect(args.ip)
    auto = args.evet
    before = tv.status()

    header("1) Animasyonlar")
    scale = 0 if args.animasyon_kapat else 0.5
    if ask(f"Menü animasyonları {scale}x yapılsın mı? (menüler daha hızlı açılır)", True, auto):
        tv.set_animations(scale)
        print("  Tamam.")

    header("2) Önbellek temizliği")
    if ask("Tüm uygulamaların önbelleği temizlensin mi? (oturumlar/veriler silinmez)", True, auto):
        tv.trim_caches()
        print("  Tamam.")

    header("3) Gereksiz uygulamalar")
    bloat = tv.present_bloat()
    if not bloat:
        print("  Kapatılacak bilinen gereksiz uygulama yok.")
    for b in bloat:
        tag = "önerilir" if b.safe else "isteğe bağlı"
        print(f"\n  {b.title}  ({b.package})  [{tag}]\n    {b.note}")
        if ask("    Devre dışı bırakılsın mı?", b.safe, auto):
            ok = tv.disable_package(b.package)
            print("    Kapatıldı." if ok else "    Kapatılamadı (bu modelde izin verilmiyor olabilir).")

    for pkg in args.paket or []:
        if is_protected(pkg):
            print(f"  {pkg}: korumalı sistem paketi, atlandı.")
            continue
        ok = tv.disable_package(pkg)
        print(f"  {pkg}: {'kapatıldı' if ok else 'kapatılamadı'}")

    header("4) Arka plan uygulamaları")
    if ask("Arka planda çalışan uygulamalar durdurulsun mu?", True, auto):
        tv.kill_background()
        print("  Tamam.")

    after = tv.status()
    header("Sonuç")
    print(f"  Boş RAM    : {before.ram_free_mb} MB -> {after.ram_free_mb} MB")
    if before.storage_free_mb is not None and after.storage_free_mb is not None:
        print(f"  Boş alan   : {before.storage_free_mb} MB -> {after.storage_free_mb} MB")
    print("  Tüm değişiklikler 'python -m tvhiz geri-al " + args.ip + "' ile geri alınabilir.")

    if ask("\nEn iyi sonuç için TV şimdi yeniden başlatılsın mı?", True, auto):
        tv.reboot()
        print("TV yeniden başlatılıyor.")


def cmd_undo(args) -> None:
    tv = _connect(args.ip)
    restored = tv.undo_all()
    print(f"Animasyonlar eski haline döndü. Yeniden açılan uygulamalar: {', '.join(restored) or 'yok'}")


def cmd_reboot(args) -> None:
    info = identify(args.ip)
    if info.adb_ready:
        _connect(args.ip).reboot()
        print("TV yeniden başlatılıyor.")
    elif send_key(args.ip, "Standby", api=info.api_version or "1"):
        print("Bekleme komutu gönderildi. (Eski modellerde tam temizlik için fişten çekip 2 dk bekleyin.)")
    else:
        print("TV'ye komut gönderilemedi.")


def cmd_list(args) -> None:
    header("Bilinen gereksiz uygulamalar")
    for b in BLOAT:
        print(f"  [{'önerilir' if b.safe else 'isteğe bağlı':^12}] {b.package:<42} {b.title}")


# ---------------------------------------------------------------- menü

def interactive() -> None:
    print(f"Philips TV Hızlandırıcı v{__version__}")
    ns = argparse.Namespace(ag=None, evet=False, animasyon_kapat=False, paket=None)
    tvs = cmd_scan(ns)
    if tvs:
        ip = tvs[0].ip if len(tvs) == 1 else input("\nHangi TV (IP): ").strip()
    else:
        ip = input("\nTV'nin IP adresini girin (boş bırakırsanız çıkış): ").strip()
        if not ip:
            return
    info = next((t for t in tvs if t.ip == ip), None) or identify(ip)
    ns.ip = ip

    if not info.is_android:
        print_tips()
        return
    if not info.adb_ready:
        print("\nBu bir Android TV ama ADB bağlantısı kapalı. README.md'deki adımlarla açın ve tekrar çalıştırın.")
        return

    while True:
        print("\n1) Durum / teşhis   2) Hızlandır   3) Geri al   4) Yeniden başlat   0) Çıkış")
        choice = input("Seçim: ").strip()
        try:
            if choice == "1":
                cmd_status(ns)
            elif choice == "2":
                cmd_optimize(ns)
            elif choice == "3":
                cmd_undo(ns)
            elif choice == "4":
                cmd_reboot(ns)
            elif choice in ("0", "q", ""):
                return
        except AdbError as e:
            print(f"\nHata: {e}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tvhiz", description="Yavaş Philips Smart TV'leri hızlandırma aracı")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("tara", help="Ağdaki Philips TV'leri bul")
    s.add_argument("--ag", help="Taranacak ağ, ör. 192.168.1.0/24")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("durum", help="TV'nin RAM/depolama durumu ve teşhis")
    s.add_argument("ip")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("hizlandir", help="Adım adım hızlandırma (Android TV)")
    s.add_argument("ip")
    s.add_argument("-e", "--evet", action="store_true", help="Soru sormadan önerilen ayarları uygula")
    s.add_argument("--animasyon-kapat", action="store_true", help="Animasyonları tamamen kapat (0x)")
    s.add_argument("--paket", action="append", help="Ek olarak kapatılacak paket adı (tekrarlanabilir)")
    s.set_defaults(func=cmd_optimize)

    s = sub.add_parser("geri-al", help="Bu araçla yapılan tüm değişiklikleri geri al")
    s.add_argument("ip")
    s.set_defaults(func=cmd_undo)

    s = sub.add_parser("yeniden-baslat", help="TV'yi yeniden başlat")
    s.add_argument("ip")
    s.set_defaults(func=cmd_reboot)

    s = sub.add_parser("liste", help="Bilinen gereksiz uygulama listesi")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("ipuclari", help="Eski NetTV modeller için hızlandırma rehberi")
    s.set_defaults(func=lambda a: print_tips())
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not args.cmd:
            interactive()
        else:
            args.func(args)
    except AdbError as e:
        print(f"\nHata: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nİptal edildi.")
        return 130
    return 0

"""Philips Android TV'ler için ADB üzerinden hızlandırma işlemleri.

Yapılan her değişiklik geri alınabilir:
  - Uygulamalar silinmez, yalnızca "pm disable-user" ile devre dışı bırakılır.
  - Eski animasyon değerleri kaydedilir.
Kayıtlar ~/.tvhiz/<ip>.json dosyasında tutulur.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

STATE_DIR = Path.home() / ".tvhiz"

ANIMATION_KEYS = (
    "window_animation_scale",
    "transition_animation_scale",
    "animator_duration_scale",
)

# Asla dokunulmayacak paketler: TV'nin kendisi, kanal/tuner, Google servisleri, launcher.
PROTECTED_PREFIXES = (
    "org.droidtv.",            # Philips TV çekirdeği (kanallar, ayarlar, kaynaklar)
    "com.philips.",            # Philips sistem bileşenleri
    "com.android.",            # Android sistemi ve Play Store (printspooler hariç)
    "com.google.android.gms",  # Google Play Hizmetleri
    "com.google.android.gsf",
    "com.google.android.tvlauncher",
    "com.google.android.leanbacklauncher",
)
PROTECTED_EXACT = {"android"}
ALLOWED_EXCEPTIONS = {"com.android.printspooler"}


@dataclass(frozen=True)
class Bloat:
    package: str
    title: str
    note: str
    safe: bool  # True: neredeyse herkes için güvenle kapatılabilir


# Philips Android TV'lerde (2015-2020) sık görülen, RAM ve işlemci yiyen,
# kapatıldığında TV'nin temel işlevini bozmayan paketler.
BLOAT: tuple[Bloat, ...] = (
    Bloat("com.google.android.tvrecommendations", "Öneriler (ana ekran önerileri)",
          "Ana ekrandaki öneri satırlarını sürekli günceller; en büyük yavaşlık kaynaklarından.", True),
    Bloat("com.google.android.backdrop", "Backdrop ekran koruyucu",
          "Ekran koruyucuda internetten fotoğraf indirir.", True),
    Bloat("com.google.android.play.games", "Google Play Oyunlar", "TV'de nadiren kullanılır.", True),
    Bloat("com.google.android.videos", "Google Play Filmler", "Kullanmıyorsanız kapatın.", True),
    Bloat("com.google.android.music", "Google Play Müzik", "Hizmet kapandı, gereksiz.", True),
    Bloat("com.google.android.youtube.tvmusic", "YouTube Music", "Kullanmıyorsanız kapatın.", True),
    Bloat("com.google.android.feedback", "Google Geri Bildirim", "Gereksiz arka plan servisi.", True),
    Bloat("com.android.printspooler", "Yazdırma servisi", "TV'de yazıcı kullanılmaz.", True),
    Bloat("com.google.android.apps.mediashell", "Chromecast (yerleşik)",
          "Telefondan TV'ye yayın (cast) yapmıyorsanız kapatın; çok RAM kullanır.", False),
    Bloat("com.google.android.katniss", "Google sesli arama",
          "Kapatırsanız kumandadan sesli arama çalışmaz.", False),
    Bloat("com.google.android.tts", "Google metin okuma", "Erişilebilirlik okuyucu kullanmıyorsanız kapatılabilir.", False),
    Bloat("com.amazon.amazonvideo.livingroom", "Prime Video", "Kullanmıyorsanız kapatın.", False),
    Bloat("com.netflix.ninja", "Netflix", "Kullanmıyorsanız kapatın.", False),
    Bloat("com.spotify.tv.android", "Spotify", "Kullanmıyorsanız kapatın.", False),
    Bloat("com.facebook.katana", "Facebook", "Kullanmıyorsanız kapatın.", False),
)


class AdbError(RuntimeError):
    pass


def is_protected(package: str) -> bool:
    if package in ALLOWED_EXCEPTIONS:
        return False
    return package in PROTECTED_EXACT or any(package.startswith(p) for p in PROTECTED_PREFIXES)


Runner = Callable[[list[str]], str]


def _default_runner(args: list[str]) -> str:
    adb = shutil.which("adb")
    if not adb:
        raise AdbError(
            "'adb' bulunamadı. Android Platform Tools'u kurun:\n"
            "  Windows: winget install Google.PlatformTools\n"
            "  macOS:   brew install android-platform-tools\n"
            "  Linux:   sudo apt install adb"
        )
    proc = subprocess.run([adb, *args], capture_output=True, text=True, timeout=120)
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise AdbError(out.strip() or f"adb {' '.join(args)} başarısız oldu")
    return out


# ---------------------------------------------------------------- ayrıştırıcılar

def parse_meminfo(text: str) -> dict[str, int]:
    """/proc/meminfo -> {anahtar: kB}"""
    out = {}
    for line in text.splitlines():
        m = re.match(r"(\w+):\s+(\d+)", line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def parse_df(text: str) -> tuple[int, int] | None:
    """'df /data' çıktısından (toplam_kB, boş_kB) döndürür."""
    for line in text.splitlines()[1:]:
        cols = line.split()
        if len(cols) >= 4:
            try:
                return _to_kb(cols[1]), _to_kb(cols[3])
            except ValueError:
                continue
    return None


def _to_kb(value: str) -> int:
    units = {"K": 1, "M": 1024, "G": 1024 ** 2, "T": 1024 ** 3}
    v = value.strip().upper()
    if v and v[-1] in units:
        return int(float(v[:-1]) * units[v[-1]])
    return int(v)  # toybox df varsayılan olarak 1K blok verir


def parse_top_memory(text: str, limit: int = 10) -> list[tuple[str, int]]:
    """'dumpsys meminfo' çıktısından en çok RAM kullanan süreçleri çıkarır: [(ad, kB)]"""
    procs: list[tuple[str, int]] = []
    in_section = False
    for line in text.splitlines():
        if re.match(r"\s*Total PSS by process", line) or re.match(r"\s*Total RSS by process", line):
            in_section = True
            continue
        if in_section:
            if not line.strip():
                if procs:
                    break
                continue
            m = re.match(r"\s*([\d,]+)K:\s+(\S+)", line)
            if m:
                procs.append((m.group(2), int(m.group(1).replace(",", ""))))
            elif procs:
                break
    return procs[:limit]


def parse_packages(text: str) -> set[str]:
    return {line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith("package:")}


# ---------------------------------------------------------------- TV sınıfı

@dataclass
class Status:
    model: str
    android: str
    ram_total_mb: int
    ram_free_mb: int
    storage_total_mb: int | None
    storage_free_mb: int | None
    top_memory: list[tuple[str, int]]
    animations: dict[str, str]


class AndroidTV:
    def __init__(self, ip: str, port: int = 5555, runner: Runner | None = None):
        self.ip = ip
        self.serial = f"{ip}:{port}"
        self._run = runner or _default_runner

    # -- temel
    def connect(self) -> None:
        out = self._run(["connect", self.serial])
        if "connected" not in out or "cannot" in out or "failed" in out:
            raise AdbError(
                f"TV'ye bağlanılamadı: {out.strip()}\n"
                "TV ekranında 'USB hata ayıklamaya izin verilsin mi?' sorusu çıktıysa "
                "'Her zaman izin ver' seçip tekrar deneyin."
            )
        state = self._run(["-s", self.serial, "get-state"]).strip()
        if "unauthorized" in state:
            raise AdbError("TV bağlantıyı onaylamadı. TV ekranındaki izin sorusunu onaylayın.")

    def shell(self, cmd: str) -> str:
        return self._run(["-s", self.serial, "shell", cmd])

    # -- bilgi
    def status(self) -> Status:
        mem = parse_meminfo(self.shell("cat /proc/meminfo"))
        free_kb = mem.get("MemAvailable", mem.get("MemFree", 0) + mem.get("Cached", 0))
        df = parse_df(self.shell("df /data"))
        try:
            top = parse_top_memory(self.shell("dumpsys meminfo"))
        except AdbError:
            top = []
        return Status(
            model=self.shell("getprop ro.product.model").strip(),
            android=self.shell("getprop ro.build.version.release").strip(),
            ram_total_mb=mem.get("MemTotal", 0) // 1024,
            ram_free_mb=free_kb // 1024,
            storage_total_mb=df[0] // 1024 if df else None,
            storage_free_mb=df[1] // 1024 if df else None,
            top_memory=top,
            animations={k: self.shell(f"settings get global {k}").strip() for k in ANIMATION_KEYS},
        )

    def installed_packages(self) -> set[str]:
        return parse_packages(self.shell("pm list packages"))

    def enabled_packages(self) -> set[str]:
        return parse_packages(self.shell("pm list packages -e"))

    def present_bloat(self) -> list[Bloat]:
        enabled = self.enabled_packages()
        return [b for b in BLOAT if b.package in enabled]

    # -- kayıt (geri alma için)
    @property
    def state_file(self) -> Path:
        return STATE_DIR / f"{self.ip.replace(':', '_')}.json"

    def load_state(self) -> dict:
        if self.state_file.exists():
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        return {"disabled": [], "animations": {}}

    def save_state(self, state: dict) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

    # -- işlemler
    def set_animations(self, scale: float) -> None:
        state = self.load_state()
        if not state.get("animations"):
            state["animations"] = {
                k: self.shell(f"settings get global {k}").strip() for k in ANIMATION_KEYS
            }
            self.save_state(state)
        for k in ANIMATION_KEYS:
            self.shell(f"settings put global {k} {scale}")

    def trim_caches(self) -> None:
        # Tüm uygulamaların önbelleğini temizler (veriler/oturumlar silinmez).
        self.shell("pm trim-caches 999G")

    def kill_background(self) -> None:
        self.shell("am kill-all")

    def disable_package(self, package: str) -> bool:
        if is_protected(package):
            raise AdbError(f"{package} korumalı bir sistem paketi, kapatılmayacak.")
        out = self.shell(f"pm disable-user --user 0 {package}")
        ok = "disabled" in out.lower()
        if ok:
            state = self.load_state()
            if package not in state["disabled"]:
                state["disabled"].append(package)
            self.save_state(state)
        return ok

    def enable_package(self, package: str) -> bool:
        out = self.shell(f"pm enable {package}")
        ok = "enabled" in out.lower()
        if ok:
            state = self.load_state()
            if package in state["disabled"]:
                state["disabled"].remove(package)
            self.save_state(state)
        return ok

    def undo_all(self) -> list[str]:
        """Bu araçla yapılan tüm değişiklikleri geri alır."""
        state = self.load_state()
        restored = []
        for pkg in list(state.get("disabled", [])):
            if self.enable_package(pkg):
                restored.append(pkg)
        anims = state.get("animations") or {}
        for k in ANIMATION_KEYS:
            v = anims.get(k, "null")
            if v in ("", "null"):
                self.shell(f"settings delete global {k}")
            else:
                self.shell(f"settings put global {k} {v}")
        state = self.load_state()
        state["animations"] = {}
        self.save_state(state)
        return restored

    def reboot(self) -> None:
        try:
            self._run(["-s", self.serial, "reboot"])
        except AdbError:
            pass  # TV yeniden başlarken bağlantı kopar, normaldir.

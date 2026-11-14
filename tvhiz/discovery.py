"""Yerel ağdaki Philips TV'leri bulma ve tanıma.

Philips TV'ler "JointSPACE" adlı bir HTTP API sunar:
  - Eski NetTV (Linux) modeller: http://IP:1925/1/system
  - Android TV modeller:        https://IP:1926/6/system (bazıları http://IP:1925/6/system)
Android TV'lerde ağ üzerinden hata ayıklama açıksa 5555 (ADB) portu da açıktır.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import ssl
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

JOINTSPACE_HTTP = 1925
JOINTSPACE_HTTPS = 1926
ADB_PORT = 5555


@dataclass
class TVInfo:
    ip: str
    open_ports: list[int] = field(default_factory=list)
    name: str = ""
    model: str = ""
    software: str = ""
    api_version: str = ""
    os_type: str = ""  # "android", "nettv" veya "bilinmiyor"

    @property
    def is_android(self) -> bool:
        return self.os_type == "android"

    @property
    def adb_ready(self) -> bool:
        return ADB_PORT in self.open_ports

    def summary(self) -> str:
        label = {
            "android": "Android TV",
            "nettv": "NetTV / Saphi (Linux)",
        }.get(self.os_type, "Bilinmiyor")
        parts = [f"{self.ip:<15}", label]
        if self.name or self.model:
            parts.append(f"{self.name} {self.model}".strip())
        if self.api_version:
            parts.append(f"API v{self.api_version}")
        if self.is_android:
            parts.append("ADB: açık" if self.adb_ready else "ADB: kapalı")
        return "  |  ".join(parts)


def local_ipv4() -> str | None:
    """Bilgisayarın yerel ağdaki IP adresini bulur (paket göndermez)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.1.1", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def port_open(ip: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def _get_json(url: str, timeout: float = 2.0) -> dict | None:
    # TV'nin HTTPS sertifikası kendinden imzalıdır; yalnızca yerel TV'ye
    # bağlanırken doğrulama kapatılır.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    # Ev ağındaki TV'ye doğrudan bağlan, sistem proxy'sini kullanma.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx)
    )
    try:
        with opener.open(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None


def parse_system(info: TVInfo, data: dict) -> None:
    """JointSPACE /system yanıtını TVInfo içine işler."""
    info.name = str(data.get("name", "") or info.name)
    info.model = str(data.get("model", "") or data.get("ctn", "") or info.model)
    info.software = str(data.get("softwareversion", "") or info.software)
    api = data.get("api_version")
    if isinstance(api, dict):
        info.api_version = str(api.get("Major", ""))
    elif api:
        info.api_version = str(api)

    blob = json.dumps(data).lower()
    if "android" in blob:
        info.os_type = "android"
    elif info.api_version and info.api_version.isdigit() and int(info.api_version) >= 5:
        # API v5+ yalnızca Android tabanlı Philips TV'lerde bulunur
        info.os_type = "android"
    elif not info.os_type:
        info.os_type = "nettv"


def identify(ip: str, ports: list[int] | None = None) -> TVInfo:
    """Verilen IP'deki TV'yi tanımlar."""
    if ports is None:
        ports = [p for p in (JOINTSPACE_HTTP, JOINTSPACE_HTTPS, ADB_PORT) if port_open(ip, p)]
    info = TVInfo(ip=ip, open_ports=sorted(ports))

    candidates = []
    if JOINTSPACE_HTTPS in ports:
        candidates.append(f"https://{ip}:{JOINTSPACE_HTTPS}/6/system")
    if JOINTSPACE_HTTP in ports:
        candidates += [
            f"http://{ip}:{JOINTSPACE_HTTP}/6/system",
            f"http://{ip}:{JOINTSPACE_HTTP}/5/system",
            f"http://{ip}:{JOINTSPACE_HTTP}/1/system",
        ]
    for url in candidates:
        data = _get_json(url)
        if data:
            parse_system(info, data)
            if "/1/system" in url and not info.api_version:
                info.api_version = "1"
            break

    if ADB_PORT in ports:
        info.os_type = "android"
    if not info.os_type:
        info.os_type = "bilinmiyor"
    return info


def scan(subnet: str | None = None, timeout: float = 0.4, workers: int = 128) -> list[TVInfo]:
    """Ağı tarar, JointSPACE veya ADB portu açık cihazları döndürür."""
    if subnet is None:
        ip = local_ipv4()
        if not ip:
            raise RuntimeError("Yerel IP bulunamadı. --ag 192.168.1.0/24 şeklinde belirtin.")
        subnet = str(ipaddress.ip_network(f"{ip}/24", strict=False))
    hosts = [str(h) for h in ipaddress.ip_network(subnet, strict=False).hosts()]

    def probe(host: str) -> tuple[str, list[int]]:
        return host, [p for p in (JOINTSPACE_HTTP, JOINTSPACE_HTTPS) if port_open(host, p, timeout)]

    found: list[tuple[str, list[int]]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for host, ports in ex.map(probe, hosts):
            if ports:
                found.append((host, ports))

    results = []
    for host, ports in found:
        if port_open(host, ADB_PORT, timeout):
            ports.append(ADB_PORT)
        results.append(identify(host, ports))
    return results

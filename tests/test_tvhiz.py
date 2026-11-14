import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from tvhiz import android, discovery
from tvhiz.android import AdbError, AndroidTV, is_protected, parse_df, parse_meminfo, parse_top_memory

MEMINFO = "MemTotal:        1530000 kB\nMemFree:          40000 kB\nMemAvailable:     150000 kB\n"
DF = "Filesystem     1K-blocks    Used Available Use% Mounted on\n/dev/block/dm-0  4000000 3700000    300000  93% /data\n"
DUMPSYS = """Applications Memory Usage (in Kilobytes):

Total PSS by process:
    210,456K: org.droidtv.playtv (pid 1234)
    150,000K: com.google.android.tvrecommendations (pid 2345)
     90,001K: com.google.android.apps.mediashell (pid 3456)

Total PSS by OOM adjustment:
    500,000K: Native
"""


class FakeTV:
    """ADB komutlarını taklit eden sahte Philips Android TV."""

    def __init__(self):
        self.settings = {}
        self.enabled = {
            "org.droidtv.playtv",
            "com.google.android.tvrecommendations",
            "com.google.android.backdrop",
            "com.google.android.apps.mediashell",
            "com.netflix.ninja",
        }
        self.log = []

    def __call__(self, args):
        self.log.append(args)
        if args[0] == "connect":
            return f"connected to {args[1]}\n"
        if args[2] == "get-state":
            return "device\n"
        if args[2] == "reboot":
            return ""
        cmd = args[3]
        if cmd == "cat /proc/meminfo":
            return MEMINFO
        if cmd == "df /data":
            return DF
        if cmd == "dumpsys meminfo":
            return DUMPSYS
        if cmd.startswith("getprop ro.product.model"):
            return "65PUS6262/12\n"
        if cmd.startswith("getprop"):
            return "8.0.0\n"
        if cmd.startswith("settings get global "):
            return self.settings.get(cmd.split()[-1], "null") + "\n"
        if cmd.startswith("settings put global "):
            _, _, _, k, v = cmd.split()
            self.settings[k] = v
            return ""
        if cmd.startswith("settings delete global "):
            self.settings.pop(cmd.split()[-1], None)
            return ""
        if cmd == "pm list packages -e":
            return "".join(f"package:{p}\n" for p in sorted(self.enabled))
        if cmd.startswith("pm disable-user"):
            pkg = cmd.split()[-1]
            self.enabled.discard(pkg)
            return f"Package {pkg} new state: disabled-user\n"
        if cmd.startswith("pm enable"):
            pkg = cmd.split()[-1]
            self.enabled.add(pkg)
            return f"Package {pkg} new state: enabled\n"
        if cmd in ("pm trim-caches 999G", "am kill-all"):
            return ""
        raise AssertionError(f"beklenmeyen komut: {args}")


class ParserTests(unittest.TestCase):
    def test_meminfo(self):
        self.assertEqual(parse_meminfo(MEMINFO)["MemAvailable"], 150000)

    def test_df(self):
        self.assertEqual(parse_df(DF), (4000000, 300000))
        self.assertEqual(parse_df("Filesystem Size Used Avail\n/data 3.7G 3.4G 300M /data\n")[1], 300 * 1024)

    def test_top_memory(self):
        top = parse_top_memory(DUMPSYS)
        self.assertEqual(top[0], ("org.droidtv.playtv", 210456))
        self.assertEqual(len(top), 3)

    def test_protected(self):
        self.assertTrue(is_protected("org.droidtv.playtv"))
        self.assertTrue(is_protected("com.google.android.gms"))
        self.assertTrue(is_protected("android"))
        self.assertFalse(is_protected("com.android.printspooler"))
        self.assertFalse(is_protected("com.google.android.backdrop"))
        for b in android.BLOAT:
            self.assertFalse(is_protected(b.package), b.package)


class AndroidTVTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        patcher = mock.patch.object(android, "STATE_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.fake = FakeTV()
        self.tv = AndroidTV("192.168.1.50", runner=self.fake)
        self.tv.connect()

    def test_status(self):
        st = self.tv.status()
        self.assertEqual(st.model, "65PUS6262/12")
        self.assertEqual(st.ram_free_mb, 146)
        self.assertEqual(st.storage_free_mb, 292)

    def test_present_bloat(self):
        names = {b.package for b in self.tv.present_bloat()}
        self.assertIn("com.google.android.tvrecommendations", names)
        self.assertNotIn("org.droidtv.playtv", names)

    def test_disable_and_undo(self):
        self.fake.settings["window_animation_scale"] = "1.0"
        self.tv.set_animations(0.5)
        self.tv.set_animations(0)  # ikinci çağrı orijinal değeri ezmemeli
        self.assertTrue(self.tv.disable_package("com.google.android.backdrop"))
        self.assertNotIn("com.google.android.backdrop", self.fake.enabled)
        self.assertEqual(self.fake.settings["window_animation_scale"], "0")

        restored = self.tv.undo_all()
        self.assertEqual(restored, ["com.google.android.backdrop"])
        self.assertIn("com.google.android.backdrop", self.fake.enabled)
        self.assertEqual(self.fake.settings["window_animation_scale"], "1.0")
        self.assertNotIn("transition_animation_scale", self.fake.settings)

    def test_refuses_protected(self):
        with self.assertRaises(AdbError):
            self.tv.disable_package("org.droidtv.playtv")
        self.assertIn("org.droidtv.playtv", self.fake.enabled)

    def test_cli_optimize_auto(self):
        from tvhiz import cli
        with mock.patch.object(cli, "AndroidTV", lambda ip: self.tv), mock.patch("builtins.print"):
            rc = cli.main(["hizlandir", "192.168.1.50", "--evet"])
        self.assertEqual(rc, 0)
        # Güvenli olanlar kapatılmalı, isteğe bağlı olanlar (Netflix, Chromecast) dokunulmamalı
        self.assertNotIn("com.google.android.tvrecommendations", self.fake.enabled)
        self.assertNotIn("com.google.android.backdrop", self.fake.enabled)
        self.assertIn("com.netflix.ninja", self.fake.enabled)
        self.assertIn("com.google.android.apps.mediashell", self.fake.enabled)
        self.assertIn(["-s", "192.168.1.50:5555", "reboot"], self.fake.log)


class FakeJointSpace(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/1/system":
            body = json.dumps({"name": "Philips TV", "model": "42PFL6008", "softwareversion": "QF2EU-1.2"})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass


class DiscoveryTests(unittest.TestCase):
    def test_parse_android_v6(self):
        info = discovery.TVInfo(ip="x")
        discovery.parse_system(info, {"name": "TV", "api_version": {"Major": 6}, "featuring": {}})
        self.assertTrue(info.is_android)

    def test_identify_nettv(self):
        srv = HTTPServer(("127.0.0.1", 0), FakeJointSpace)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        with mock.patch.object(discovery, "JOINTSPACE_HTTP", port):
            info = discovery.identify("127.0.0.1", [port])
        self.assertEqual(info.model, "42PFL6008")
        self.assertEqual(info.os_type, "nettv")
        self.assertEqual(info.api_version, "1")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VLESS (tls / reality) collector + TCP tester + xray tester
برای Termux و GitHub Actions.

مراحل:
 1) دانلود کانفیگ‌ها از منابع
 2) فیلتر: فقط vless با security=tls یا reality
 3) حذف تکراری‌ها
 4) تست TCP و حذف مرده‌ها (بدون ذخیره فایل)
 5) تست واقعی با xray (یک درخواست HTTPS از داخل پروکسی)
    فقط کانفیگ‌هایی که جواب بدن می‌مونن -> final_alive.txt

خروجی:
  - Termux: پوشه Download
  - GitHub Actions: ریشه‌ی repo

نصب در ترموکس:
    termux-setup-storage
    pkg update && pkg install -y python ca-certificates xray
    python vless_tester.py
(پیشنهاد: قبل از اجرا   termux-wake-lock   بزن تا گوشی خوابش نبره)
"""

import base64
import concurrent.futures as cf
import html
import json
import os
import platform
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from urllib.parse import parse_qs, unquote, urlsplit

try:
    import resource
except ImportError:  # ویندوز
    resource = None

# ----------------------------- تنظیمات -----------------------------
FETCH_TIMEOUT = 15          # ثانیه، دانلود هر منبع
TCP_TIMEOUT = 2.0           # ثانیه
TCP_ATTEMPTS = 1            # تعداد دفعات تست TCP (فقط پیش‌فیلتر؛ تست اصلی با xray انجام می‌شود)
TCP_WORKERS = 1000          # خودکار با محدودیت فایل‌های باز سیستم هماهنگ می‌شود

XRAY_TEST = True            # تست واقعی با xray
FINAL_OUT_NAME = "final_alive.txt"
XRAY_PROCS = max(4, (os.cpu_count() or 2) * 2)   # تعداد پروسه‌ی xray موازی (کارشون I/O هست)
BATCH_SIZE = 300            # کانفیگ در هر پروسه‌ی xray
TEST_WORKERS = 300          # ترد تست در هر دسته (هم‌اندازه‌ی دسته = کل دسته هم‌زمان)
BASE_PORT = 20000
SITE_TIMEOUT = 4            # ثانیه برای تست xray
SITE_TRIES = 1              # تعداد تلاش برای تست (برای دقت بیشتر 2 بذار)

URLS = [
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_VLESS_RUS_mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-checked.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/BLACK_SS+All_RUS.txt",
    "https://raw.githubusercontent.com/Mosifree/-FREE2CONFIG/refs/heads/main/FRAGMENT",
    "https://raw.githubusercontent.com/ShadowException/VPN/refs/heads/main/configs/VPN-cat",
    "https://raw.githubusercontent.com/F0rc3Run/F0rc3Run/main/splitted-by-protocol/vless.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-config/main/Sub1.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Sub2.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/Sub3.txt",
    "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/V2Ray-Config-By-EbraSha.txt",
    "https://raw.githubusercontent.com/ALIILAPRO/v2rayNG-Config/main/sub.txt",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt",
    "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub",
    "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt",
    "https://empty-mouse-fbb7.alizareh4024.workers.dev/sync?sub=%D8%B3%D9%88%D8%B3%D9%8D%D8%A7%D8%B1%F0%9F%A6%8E",
    "https://raw.githubusercontent.com/pytimusprime/FreeV2ray/refs/heads/main/all_servers.txt",
    "https://raw.githubusercontent.com/ThomasJasperthecat/sub/main/sublist1.txt",
    "https://raw.githubusercontent.com/masir-sefid/Sub/main/@Masir_Sefid.txt",
    "https://sub.iampedi5.live/sub/base64.txt",
    "https://raw.githubusercontent.com/masir-sefid/Sub/main/Telegram-Channel-@Masir_Sefid.txt",
    "https://raw.githubusercontent.com/AmyraxVPN-Main/AmyraxVPN/refs/heads/main/AmyraxVPN.txt",
    "https://raw.githubusercontent.com/arshiacomplus/v2rayExtractor/refs/heads/main/mix/sub.html",
    "https://raw.githubusercontent.com/10ium/free-config/refs/heads/main/free-mihomo-sub/freedom_house_countries__NoRule.yaml",
    "https://raw.githubusercontent.com/hamedp-71/clash_new/refs/heads/main/hp.yaml",
    "https://link.gridpointgo.com/asanet/fa5e7de2d56085f6068eea0334e366ab",
    "https://raw.githubusercontent.com/shaoyouvip/free/refs/heads/main/base64.txt",
    "https://raw.githubusercontent.com/shuaidaoya/FreeNodes/refs/heads/main/nodes/base64.txt",
    "https://raw.githubusercontent.com/penhandev/AutoAiVPN/refs/heads/main/allConfigs.txt",
    "https://raw.githubusercontent.com/crackbest/V2ray-Config/refs/heads/main/config.txt",
    "https://raw.githubusercontent.com/mohamadfg-dev/telegram-v2ray-configs-collector/refs/heads/main/category/vless.txt",
    "https://raw.githubusercontent.com/Matin-RK0/ConfigCollector/refs/heads/main/subscription.txt",
    "https://raw.githubusercontent.com/Argh73/VpnConfigCollector/refs/heads/main/All_Configs_Sub.txt",
    "https://raw.githubusercontent.com/3yed-61/configs-collector/refs/heads/main/classified_output/vless.txt",
    "https://raw.githubusercontent.com/Leon406/SubCrawler/refs/heads/main/sub/share/vless",
    "https://raw.githubusercontent.com/MhdiTaheri/V2rayCollector_Py/refs/heads/main/sub/Mix/mix.txt",
    "https://raw.githubusercontent.com/T3stAcc/V2Ray/refs/heads/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/F0rc3Run/F0rc3Run/refs/heads/main/splitted-by-protocol/vless.txt",
    "https://raw.githubusercontent.com/V2RayRoot/V2RayConfig/refs/heads/main/Config/vless.txt",
    "https://raw.githubusercontent.com/LalatinaHub/Mineral/refs/heads/master/result/nodes",
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/refs/heads/main/All_Configs_Sub.txt",
    "https://raw.githubusercontent.com/hamedcode/port-based-v2ray-configs/refs/heads/main/sub/vless.txt",
    "https://raw.githubusercontent.com/iboxz/free-v2ray-collector/refs/heads/main/main/vless",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/refs/heads/main/Splitted-By-Protocol/vless.txt",
    "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/vless_configs.txt",
    "https://raw.githubusercontent.com/Pasimand/v2ray-config-agg/refs/heads/main/config.txt",
    "https://raw.githubusercontent.com/arshiacomplus/v2rayExtractor/refs/heads/main/vless.html",
    "https://raw.githubusercontent.com/AvenCores/goida-vpn-configs/refs/heads/main/githubmirror/14.txt",
    "https://raw.githubusercontent.com/SoliSpirit/v2ray-configs/refs/heads/main/Protocols/vless.txt",
    "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/all/configs.txt",
]
# -------------------------------------------------------------------

UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"}
LINK_RE = re.compile(r"vless://[^\s\"'<>`]+", re.I)
print_lock = threading.Lock()


def log(*a):
    with print_lock:
        print(*a, flush=True)


def tune_limits():
    """محدودیت فایل‌های باز رو بالا می‌بره و تعداد ترد‌ها رو باهاش هماهنگ می‌کنه."""
    global TCP_WORKERS, TEST_WORKERS
    threading.stack_size(512 * 1024)   # رم کمتر برای هزاران ترد
    fd = 1024
    if resource:
        try:
            soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            want = 65535 if hard == resource.RLIM_INFINITY else min(hard, 65535)
            if soft < want:
                resource.setrlimit(resource.RLIMIT_NOFILE, (want, hard))
            fd = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
        except Exception:
            pass
    TCP_WORKERS = min(TCP_WORKERS, max(50, fd // 4))
    TEST_WORKERS = min(TEST_WORKERS, max(20, fd // (3 * XRAY_PROCS)))


# ----------------------------- مسیر خروجی -----------------------------
def download_dir():
    # GitHub Actions: توی ریشه‌ی repo (پوشه‌ی جاری) ذخیره کن
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return os.getcwd()

    # Termux
    for p in (os.path.expanduser("~/storage/downloads"),
              "/storage/emulated/0/Download",
              "/sdcard/Download"):
        if os.path.isdir(p) and os.access(p, os.W_OK):
            return p
    log("⚠️ به پوشه Download دسترسی نیست. اول بزن: termux-setup-storage")
    log("   فعلاً در پوشه خانه ذخیره می‌شود.")
    return os.path.expanduser("~")


# ----------------------------- دانلود و استخراج -----------------------------
def b64_decode(s):
    s = re.sub(r"\s+", "", s)
    s += "=" * (-len(s) % 4)
    for fn in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            return fn(s).decode("utf-8", "ignore")
        except Exception:
            pass
    return ""


def extract_links(text):
    text = html.unescape(text)
    links = LINK_RE.findall(text)
    if not links:  # شاید base64 باشد
        links = LINK_RE.findall(b64_decode(text))
    return links


def fetch(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
            data = r.read().decode("utf-8", "ignore")
        return url, extract_links(data)
    except Exception as e:
        return url, e


# ----------------------------- پارس کانفیگ -----------------------------
def parse_vless(link):
    """برمی‌گرداند dict یا None. فقط tls/reality."""
    try:
        u = urlsplit(link.strip().rstrip(",;)"))
        if u.scheme.lower() != "vless" or not u.username or not u.hostname or not u.port:
            return None
        q = {k: unquote(v[0]) for k, v in parse_qs(u.query, keep_blank_values=True).items()}
        sec = q.get("security", "").lower()
        if sec not in ("tls", "reality"):
            return None
        net = q.get("type", "tcp").lower()
        if net == "splithttp":
            net = "xhttp"
        if net not in ("tcp", "ws", "grpc", "httpupgrade", "xhttp"):
            return None
        if sec == "reality" and not q.get("pbk"):
            return None
        return {
            "link": link.strip().rstrip(",;)"),
            "uuid": unquote(u.username),
            "host": u.hostname,
            "port": u.port,
            "sec": sec,
            "net": net,
            "q": q,
        }
    except Exception:
        return None


def dedup_key(c):
    q = c["q"]
    return (c["uuid"].lower(), c["host"].lower(), c["port"], c["sec"], c["net"],
            q.get("sni", "").lower(), q.get("host", "").lower(), q.get("path", ""),
            q.get("serviceName", ""), q.get("pbk", ""), q.get("sid", ""),
            q.get("flow", ""), q.get("fp", ""))


# ----------------------------- تست TCP -----------------------------
def tcp_ping(host, port):
    """TCP_ATTEMPTS بار تست می‌گیره؛ با اولین شکست None برمی‌گردونه، وگرنه میانگین پینگ (ms)."""
    total = 0
    for _ in range(TCP_ATTEMPTS):
        t = time.time()
        try:
            with socket.create_connection((host, port), timeout=TCP_TIMEOUT):
                total += time.time() - t
        except Exception:
            return None
    return int(total / TCP_ATTEMPTS * 1000)


# ----------------------------- تست واقعی با xray -----------------------------
def ensure_xray():
    p = shutil.which("xray")          # در ترموکس: pkg install xray
    if p:
        return p
    d = os.path.join(tempfile.gettempdir(), "xray_bin")
    local = os.path.join(d, "xray")
    if os.path.isfile(local):
        return local
    os.makedirs(d, exist_ok=True)
    m = platform.machine().lower()
    name = "Xray-linux-arm64-v8a.zip" if m in ("aarch64", "arm64") else "Xray-linux-64.zip"
    url = f"https://github.com/XTLS/Xray-core/releases/latest/download/{name}"
    zp = os.path.join(d, name)
    log(f"⬇️  دانلود xray: {name}")
    urllib.request.urlretrieve(url, zp)
    with zipfile.ZipFile(zp) as z:
        z.extract("xray", d)
    os.chmod(local, 0o755)
    return local


def build_outbound(c, tag):
    q, net, sec = c["q"], c["net"], c["sec"]
    user = {"id": c["uuid"], "encryption": q.get("encryption") or "none"}
    if q.get("flow"):
        user["flow"] = q["flow"]
    sni = q.get("sni") or q.get("host") or c["host"]
    ss = {"network": net, "security": sec}

    if sec == "tls":
        t = {"serverName": sni, "fingerprint": q.get("fp") or "chrome"}
        if q.get("alpn"):
            t["alpn"] = q["alpn"].split(",")
        ss["tlsSettings"] = t
    else:
        ss["realitySettings"] = {
            "serverName": sni, "fingerprint": q.get("fp") or "chrome",
            "publicKey": q["pbk"], "shortId": q.get("sid", ""),
            "spiderX": q.get("spx", ""),
        }

    path, host = q.get("path", "/"), q.get("host", "")
    if net == "tcp" and q.get("headerType") == "http":
        hdr = {"type": "http", "request": {"path": [path]}}
        if host:
            hdr["request"]["headers"] = {"Host": host.split(",")}
        ss["tcpSettings"] = {"header": hdr}
    elif net == "ws":
        w = {"path": path}
        if host:
            w["headers"] = {"Host": host}
        ss["wsSettings"] = w
    elif net == "grpc":
        g = {"serviceName": q.get("serviceName", ""), "multiMode": q.get("mode") == "multi"}
        if q.get("authority"):
            g["authority"] = q["authority"]
        ss["grpcSettings"] = g
    elif net == "httpupgrade":
        ss["httpupgradeSettings"] = {"path": path, "host": host}
    elif net == "xhttp":
        x = {"path": path, "host": host, "mode": q.get("mode") or "auto"}
        if q.get("extra"):
            try:
                x["extra"] = json.loads(q["extra"])
            except Exception:
                pass
        ss["xhttpSettings"] = x

    return {"tag": tag, "protocol": "vless",
            "settings": {"vnext": [{"address": c["host"], "port": c["port"], "users": [user]}]},
            "streamSettings": ss}


def build_config(batch, base):
    inb, outb, rules = [], [], []
    for i, c in enumerate(batch):
        inb.append({"tag": f"i{i}", "listen": "127.0.0.1", "port": base + i,
                    "protocol": "socks", "settings": {"auth": "noauth", "udp": False}})
        outb.append(build_outbound(c, f"o{i}"))
        rules.append({"type": "field", "inboundTag": [f"i{i}"], "outboundTag": f"o{i}"})
    return {"log": {"loglevel": "none"}, "inbounds": inb, "outbounds": outb,
            "routing": {"domainStrategy": "AsIs", "rules": rules}}


def start_xray(xray, batch, base, tmp):
    cfg = os.path.join(tmp, f"c{base}_{len(batch)}_{time.time_ns()}.json")
    with open(cfg, "w") as f:
        json.dump(build_config(batch, base), f)
    p = subprocess.Popen([xray, "run", "-c", cfg],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    last = base + len(batch) - 1
    end = time.time() + 20
    while time.time() < end:
        if p.poll() is not None:
            return None
        try:
            socket.create_connection(("127.0.0.1", last), timeout=0.3).close()
            return p
        except OSError:
            time.sleep(0.1)
    p.kill()
    return None


# --- چکر ---
def chk_ok(st, loc, body):
    return 200 <= st < 400


# تست ساده‌ی اتصال از داخل پروکسی. HTTP ساده روی پورت 80 (بدون TLS در پایتون = CPU کمتر)
TEST_HOST, TEST_PORT, TEST_PATH = "cp.cloudflare.com", 80, "/generate_204"


def _recvn(s, n):
    b = b""
    while len(b) < n:
        d = s.recv(n - len(b))
        if not d:
            raise OSError("closed")
        b += d
    return b


def http_check(port):
    s = None
    try:
        end = time.time() + SITE_TIMEOUT
        s = socket.create_connection(("127.0.0.1", port), timeout=SITE_TIMEOUT)
        s.settimeout(SITE_TIMEOUT)
        s.sendall(b"\x05\x01\x00")
        if _recvn(s, 2) != b"\x05\x00":
            return False
        h = TEST_HOST.encode()
        s.sendall(b"\x05\x01\x00\x03" + bytes([len(h)]) + h + TEST_PORT.to_bytes(2, "big"))
        r = _recvn(s, 4)
        if r[1] != 0:
            return False
        if r[3] == 1:
            _recvn(s, 6)
        elif r[3] == 4:
            _recvn(s, 18)
        else:
            _recvn(s, _recvn(s, 1)[0] + 2)
        s.sendall((f"GET {TEST_PATH} HTTP/1.1\r\nHost: {TEST_HOST}\r\n"
                   f"User-Agent: {UA['User-Agent']}\r\nAccept: */*\r\n"
                   f"Connection: close\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf and len(buf) < 8192:   # به محض رسیدن هدر تمام
            left = end - time.time()
            if left <= 0:
                return False
            s.settimeout(left)
            d = s.recv(2048)
            if not d:
                break
            buf += d
        if not buf.startswith(b"HTTP/"):
            return False
        st = int(buf.split(b" ", 2)[1])
        return chk_ok(st, "", "")
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def site_test(c, port):  # تست ساده‌ی اتصال
    for _ in range(SITE_TRIES):
        t = time.time()
        if http_check(port):
            c["site_ms"] = int((time.time() - t) * 1000)
            return c
    return None


def run_batch(xray, batch, base, tmp):
    if not batch:
        return []
    p = start_xray(xray, batch, base, tmp)
    if p is None:  # یک کانفیگ خراب کل دسته رو می‌اندازد → نصف‌کردن تا پیدا شود
        if len(batch) == 1:
            return []
        mid = len(batch) // 2
        return (run_batch(xray, batch[:mid], base, tmp) +
                run_batch(xray, batch[mid:], base + mid, tmp))
    try:
        with cf.ThreadPoolExecutor(min(TEST_WORKERS, len(batch))) as ex:
            res = list(ex.map(lambda ic: site_test(ic[1], base + ic[0]), enumerate(batch)))
        return [r for r in res if r]
    finally:
        p.terminate()
        try:
            p.wait(5)
        except Exception:
            p.kill()


def save_final(good, path):
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        if good:
            f.write("\n".join(c["link"] for c in sorted(good, key=lambda c: c["site_ms"])) + "\n")
    os.replace(tmp_path, path)


class SiteStage:
    """تست xray به‌صورت پایپ‌لاین: هر ۳۰۰ کانفیگ زنده‌ی TCP بلافاصله وارد تست xray می‌شه،
    بدون اینکه منتظر تموم‌شدن تست TCP بقیه بمونه."""

    def __init__(self, final_path):
        self.final_path = final_path
        self.xray = ensure_xray()
        self.tmp = tempfile.mkdtemp()
        self.slots = queue.Queue()
        for k in range(XRAY_PROCS):
            self.slots.put(BASE_PORT + k * BATCH_SIZE)
        self.ex = cf.ThreadPoolExecutor(XRAY_PROCS)
        self.futs, self.pending, self.good = [], [], []
        self.plock, self.lock = threading.Lock(), threading.Lock()
        self.queued = 0
        self.tested = 0

    def _submit(self, batch):
        self.queued += len(batch)
        self.futs.append(self.ex.submit(self._job, batch))

    def add(self, cs):
        with self.plock:
            self.pending.extend(cs)
            while len(self.pending) >= BATCH_SIZE:
                batch, self.pending = self.pending[:BATCH_SIZE], self.pending[BATCH_SIZE:]
                self._submit(batch)

    def _job(self, batch):
        base = self.slots.get()
        try:
            res = run_batch(self.xray, batch, base, self.tmp)
        except Exception as e:
            log(f"   ⚠️ خطا در یک دسته: {type(e).__name__}: {e}")
            res = []
        finally:
            self.slots.put(base)
        with self.lock:
            self.good.extend(res)
            self.tested += len(batch)
            if res:
                save_final(self.good, self.final_path)
            log(f"   xray: {self.tested}/{self.queued} تست‌شده  سالم: {len(self.good)}")

    def finish(self):
        with self.plock:
            if self.pending:
                batch, self.pending = self.pending, []
                self._submit(batch)
        for f in list(self.futs):
            f.result()
        self.ex.shutdown()
        shutil.rmtree(self.tmp, ignore_errors=True)
        return self.good


# ----------------------------- اصلی -----------------------------
def main():
    tune_limits()
    out_dir = download_dir()
    final_path = os.path.join(out_dir, FINAL_OUT_NAME)
    save_final([], final_path)   # فایل از همین اول ساخته می‌شود (حتی خالی)

    # آماده‌سازی xray قبل از همه (اگه مشکل داشت زود بفهمیم)
    stage = None
    if XRAY_TEST:
        try:
            stage = SiteStage(final_path)
        except Exception as e:
            import traceback
            log(f"❌ آماده‌سازی xray خطا داد: {type(e).__name__}: {e}")
            log(traceback.format_exc())

    # 1) دانلود
    log(f"⬇️  دانلود از {len(URLS)} منبع ...")
    raw = []
    with cf.ThreadPoolExecutor(len(URLS)) as ex:
        for url, res in ex.map(fetch, URLS):
            if isinstance(res, Exception):
                log(f"  ✗ {url.split('/')[2]}/…{url[-25:]}  ({type(res).__name__})")
            else:
                raw.extend(res)
    log(f"   {len(raw)} لینک vless خام")

    # 2) فیلتر tls/reality + 3) حذف تکراری
    uniq, seen = [], set()
    for l in raw:
        c = parse_vless(l)
        if not c:
            continue
        k = dedup_key(c)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(c)
    log(f"🔎 tls/reality یکتا: {len(uniq)}")

    # 4) تست TCP (هر host:port یک بار) + همزمان تحویل به تست xray
    groups = {}
    for c in uniq:
        groups.setdefault((c["host"].lower(), c["port"]), []).append(c)
    log(f"📡 تست TCP روی {len(groups)} مقصد یکتا ({len(uniq)} کانفیگ) | ورکر: {TCP_WORKERS}")
    collected = []
    lock = threading.Lock()
    st = {"n": 0, "alive": 0}

    def tcp_job(item):
        (host, port), cs = item
        ms = tcp_ping(host, port)
        if ms is not None:
            for c in cs:
                c["tcp_ms"] = ms
            if stage:
                stage.add(cs)
        with lock:
            st["n"] += 1
            if ms is not None:
                st["alive"] += len(cs)
                if not XRAY_TEST:
                    collected.extend(cs)
            if st["n"] % 2000 == 0:
                log(f"   TCP: {st['n']}/{len(groups)}  کانفیگ زنده: {st['alive']}")

    with cf.ThreadPoolExecutor(min(TCP_WORKERS, len(groups) or 1)) as tp:
        list(tp.map(tcp_job, groups.items()))
    log(f"🎉 TCP زنده: {st['alive']} از {len(uniq)}")

    # 5) پایان تست xray
    if stage:
        good = stage.finish()
        log(f"✅ سالم: {len(good)} از {st['alive']}")
    elif not XRAY_TEST:
        for c in collected:
            c["site_ms"] = c["tcp_ms"]
        save_final(collected, final_path)
    log(f"📁 {final_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\nمتوقف شد.")

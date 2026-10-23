#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VLESS (tls / reality) collector + TCP tester + site tester (gemini/youtube/x)
برای Termux و GitHub Actions.

مراحل:
 1) دانلود کانفیگ‌ها از منابع
 2) فیلتر: فقط vless با security=tls یا reality
 3) حذف تکراری‌ها
 4) تست TCP و حذف مرده‌ها (بدون ذخیره فایل)
 5) تست واقعی با xray روی gemini، youtube و x
    فقط کانفیگ‌هایی که هر سه رو باز کنن می‌مونن -> final_alive.txt

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
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from urllib.parse import parse_qs, unquote, urlsplit

# ----------------------------- تنظیمات -----------------------------
FETCH_TIMEOUT = 25          # ثانیه، دانلود هر منبع
TCP_TIMEOUT = 2.0           # ثانیه
TCP_ATTEMPTS = 2            # تعداد دفعات تست TCP (یک شکست = حذف). چون تست واقعی داریم، کم است
TCP_WORKERS = 500           # اگر خطای Too many open files دیدی کمترش کن (مثلاً 250)

XRAY_TEST = True            # تست gemini/youtube/x
FINAL_OUT_NAME = "final_alive.txt"
XRAY_PROCS = max(4, (os.cpu_count() or 2) * 2)   # تعداد پروسه‌ی xray موازی (کارشون I/O هست)
BATCH_SIZE = 300            # کانفیگ در هر پروسه‌ی xray
TEST_WORKERS = 150          # ترد تست در هر دسته
BASE_PORT = 20000
SITE_TIMEOUT = 6            # ثانیه برای هر سایت
SITE_TRIES = 1              # هر سایت تا این تعداد بار تلاش می‌شود (برای دقت بیشتر 2 بذار)

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
CTX = ssl.create_default_context()
BAD_GEMINI = ("isn't available in your", "not available in your country",
              "isn\u2019t available in your", "isn't supported in your",
              "isn\u2019t supported in your", "not supported in your")


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


# --- چکرها ---
def chk_gemini(st, loc, body):
    if st == 200:
        b = body.lower()
        return not any(m in b for m in BAD_GEMINI)
    if 300 <= st < 400:  # ریدایرکت به لاگین گوگل = منطقه‌ی پشتیبانی‌شده
        l = loc.lower()
        return "accounts.google.com" in l or "servicelogin" in l
    return False


def chk_ok(st, loc, body):
    return 200 <= st < 400


SITES = [  # gemini اول، چون شرط اصلیه و زودتر کانفیگ‌های بد رو حذف می‌کنه
    ("gemini", "gemini.google.com", "/app", chk_gemini),
    ("youtube", "www.youtube.com", "/generate_204", chk_ok),
    ("x", "x.com", "/", chk_ok),
]


def _recvn(s, n):
    b = b""
    while len(b) < n:
        d = s.recv(n - len(b))
        if not d:
            raise OSError("closed")
        b += d
    return b


def http_check(port, host, path, check):
    s = None
    try:
        end = time.time() + SITE_TIMEOUT
        s = socket.create_connection(("127.0.0.1", port), timeout=SITE_TIMEOUT)
        s.settimeout(SITE_TIMEOUT)
        s.sendall(b"\x05\x01\x00")
        if _recvn(s, 2) != b"\x05\x00":
            return False
        h = host.encode()
        s.sendall(b"\x05\x01\x00\x03" + bytes([len(h)]) + h + (443).to_bytes(2, "big"))
        r = _recvn(s, 4)
        if r[1] != 0:
            return False
        if r[3] == 1:
            _recvn(s, 6)
        elif r[3] == 4:
            _recvn(s, 18)
        else:
            _recvn(s, _recvn(s, 1)[0] + 2)
        s = CTX.wrap_socket(s, server_hostname=host)
        s.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
                   f"User-Agent: {UA['User-Agent']}\r\nAccept: */*\r\n"
                   f"Connection: close\r\n\r\n").encode())
        buf = b""
        while len(buf) < 16000:
            left = end - time.time()
            if left <= 0:
                break
            s.settimeout(left)
            try:
                d = s.recv(8192)
            except socket.timeout:
                break
            if not d:
                break
            buf += d
        head, _, body = buf.partition(b"\r\n\r\n")
        if not head.startswith(b"HTTP/"):
            return False
        st = int(head.split(b" ", 2)[1])
        m = re.search(rb"(?im)^location:\s*(.+)$", head)
        loc = m.group(1).decode("utf-8", "ignore").strip() if m else ""
        return check(st, loc, body.decode("utf-8", "ignore"))
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def site_test(c, port):
    total = 0.0
    for _name, host, path, check in SITES:
        ok = False
        for _ in range(SITE_TRIES):
            t = time.time()
            if http_check(port, host, path, check):
                total += time.time() - t
                ok = True
                break
        if not ok:
            return None
    c["site_ms"] = int(total * 1000)
    return c


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
        with cf.ThreadPoolExecutor(TEST_WORKERS) as ex:
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


def run_site_stage(alive, final_path):
    xray = ensure_xray()
    log(f"   xray: {xray}")
    tmp = tempfile.mkdtemp()
    batches = [alive[i:i + BATCH_SIZE] for i in range(0, len(alive), BATCH_SIZE)]
    slots = queue.Queue()
    for k in range(XRAY_PROCS):
        slots.put(BASE_PORT + k * BATCH_SIZE)
    good, lock, done = [], threading.Lock(), {"n": 0}

    def job(batch):
        base = slots.get()
        try:
            res = run_batch(xray, batch, base, tmp)
        finally:
            slots.put(base)
        with lock:
            good.extend(res)
            save_final(good, final_path)
            done["n"] += len(batch)
            log(f"   سایت‌تست: {done['n']}/{len(alive)}  سالم: {len(good)}")

    with cf.ThreadPoolExecutor(XRAY_PROCS) as ex:
        list(ex.map(job, batches))
    shutil.rmtree(tmp, ignore_errors=True)
    return good


# ----------------------------- اصلی -----------------------------
def main():
    out_dir = download_dir()
    final_path = os.path.join(out_dir, FINAL_OUT_NAME)

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

    # 4) تست TCP: کانفیگ‌هایی که host:port مشترک دارن فقط یک بار تست می‌شن
    groups = {}
    for c in uniq:
        groups.setdefault((c["host"].lower(), c["port"]), []).append(c)
    log(f"📡 تست TCP روی {len(groups)} مقصد یکتا ({len(uniq)} کانفیگ) ...")
    alive = []
    lock = threading.Lock()
    done = {"n": 0}

    def tcp_job(item):
        (host, port), cs = item
        ms = tcp_ping(host, port)
        with lock:
            done["n"] += 1
            if ms is not None:
                for c in cs:
                    c["tcp_ms"] = ms
                alive.extend(cs)
            if done["n"] % 1000 == 0:
                log(f"   TCP: {done['n']}/{len(groups)}  کانفیگ زنده: {len(alive)}")

    with cf.ThreadPoolExecutor(min(TCP_WORKERS, len(groups) or 1)) as tp:
        list(tp.map(tcp_job, groups.items()))

    alive.sort(key=lambda c: c["tcp_ms"])
    log(f"\n🎉 TCP زنده: {len(alive)} از {len(uniq)}")

    # 5) تست gemini / youtube / x با xray -> فقط final_alive.txt
    save_final([], final_path)   # فایل از همین اول ساخته می‌شود (حتی خالی)
    if XRAY_TEST:
        if alive:
            log(f"\n🌐 تست gemini / youtube / x روی {len(alive)} کانفیگ ...")
            try:
                good = run_site_stage(alive, final_path)
                log(f"✅ سالم در هر سه سایت: {len(good)} از {len(alive)}")
            except Exception as e:
                import traceback
                log(f"❌ مرحله‌ی سایت‌تست خطا داد: {type(e).__name__}: {e}")
                log(traceback.format_exc())
    else:
        for c in alive:
            c["site_ms"] = c["tcp_ms"]
        save_final(alive, final_path)
    log(f"📁 {final_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\nمتوقف شد.")

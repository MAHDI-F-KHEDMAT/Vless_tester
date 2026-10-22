#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VLESS (tls / reality) collector + TCP tester for Termux and GitHub Actions.

مراحل:
 1) دانلود کانفیگ‌ها از منابع
 2) فیلتر: فقط vless با security=tls یا reality
 3) حذف تکراری‌ها
 4) تست TCP و حذف مرده‌ها
    خروجی: tcp_alive.txt (مرتب بر اساس پینگ)
      - Termux: در پوشه Download
      - GitHub Actions: در ریشه‌ی repo

نصب در ترموکس:
    termux-setup-storage
    pkg update && pkg install -y python ca-certificates
    python vless_tester.py
(پیشنهاد: قبل از اجرا   termux-wake-lock   بزن تا گوشی خوابش نبره)
"""

import base64
import concurrent.futures as cf
import html
import os
import re
import socket
import sys
import threading
import time
import urllib.request
from urllib.parse import parse_qs, unquote, urlsplit

# ----------------------------- تنظیمات -----------------------------
FETCH_TIMEOUT = 25          # ثانیه، دانلود هر منبع
TCP_TIMEOUT = 3.0           # ثانیه
TCP_ATTEMPTS = 10           # تعداد دفعات تست TCP برای هر کانفیگ (یک شکست = حذف)
TCP_WORKERS = 500           # اگر خطای Too many open files دیدی کمترش کن (مثلاً 250)
TCP_OUT_NAME = "tcp_alive.txt"

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
def tcp_test(c):
    """TCP_ATTEMPTS بار تست می‌گیره؛ اگه حتی یک بار تایم‌اوت/خطا داد حذف می‌شه."""
    total = 0
    for _ in range(TCP_ATTEMPTS):
        t = time.time()
        try:
            with socket.create_connection((c["host"], c["port"]), timeout=TCP_TIMEOUT):
                total += time.time() - t
        except Exception:
            return None  # با اولین شکست فوراً حذف
    c["tcp_ms"] = int(total / TCP_ATTEMPTS * 1000)
    return c


# ----------------------------- اصلی -----------------------------
def main():
    out_dir = download_dir()
    tcp_path = os.path.join(out_dir, TCP_OUT_NAME)

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

    # 4) تست TCP
    log(f"📡 تست TCP روی {len(uniq)} کانفیگ (ورکر: {TCP_WORKERS}) ...")
    alive = []
    lock = threading.Lock()
    done = {"n": 0}

    def tcp_job(c):
        r = tcp_test(c)
        with lock:
            done["n"] += 1
            if r:
                alive.append(r)
            if done["n"] % 1000 == 0:
                log(f"   TCP: {done['n']}/{len(uniq)}  زنده: {len(alive)}")

    with cf.ThreadPoolExecutor(TCP_WORKERS) as tp:
        list(tp.map(tcp_job, uniq))

    # ذخیره نتایج (مرتب بر اساس پینگ). فایل همیشه ساخته می‌شود، حتی اگر خالی باشد.
    alive.sort(key=lambda c: c["tcp_ms"])
    with open(tcp_path, "w", encoding="utf-8") as f:
        if alive:
            f.write("\n".join(c["link"] for c in alive) + "\n")

    log(f"\n🎉 تمام شد. TCP زنده: {len(alive)} از {len(uniq)}")
    log(f"📁 {tcp_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\nمتوقف شد.")

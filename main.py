import os
import sys
import time
import requests

CODE = os.getenv("CODE", "tgmember")
TARGET_LINK = os.getenv("TARGET_LINK", "https://t.me/YOUR_CHANNEL")
API_BASE = "https://telegramadviser.com/api/"
SITE_PAGE = os.getenv("SITE_URL", "https://smm8.com/free-telegram-members")
EXTRA_WAIT = int(os.getenv("EXTRA_WAIT", "10"))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
    "Origin": "https://smm8.com",
    "Referer": "https://smm8.com/free-telegram-members",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def api_post(endpoint: str, payload: dict, retries: int = 3):
    url = API_BASE + endpoint
    last_err = None
    for i in range(1, retries + 1):
        try:
            r = requests.post(url, json=payload, headers=HEADERS, timeout=30)
            log(f"POST {endpoint} -> {r.status_code} (تلاش {i})")
            if r.status_code >= 500:
                log(f"خطای سرور {r.status_code}، تلاش مجدد...")
                time.sleep(5 * i)
                continue
            try:
                data = r.json()
            except Exception:
                return None, r.status_code, r.text
            return data, r.status_code, r.text
        except Exception as e:
            last_err = e
            log(f"خطا در {endpoint} (تلاش {i}/{retries}): {e}")
            time.sleep(5 * i)
    return None, -1, ""

def main():
    if "YOUR_CHANNEL" in TARGET_LINK:
        log("TARGET_LINK ست نشده! مثال: https://t.me/mychannel")
        sys.exit(1)
    log(f"گرفتن مشخصات (code={CODE})")
    cfg, status, _ = api_post("get", {"code": CODE})
    if not cfg or "time" not in cfg:
        log(f"گرفتن config شکست خورد: {cfg}")
        sys.exit(1)
    wait_time = int(cfg.get("time", 600))
    log(f"عنوان: {cfg.get('title')}")
    log(f"تایمر: {wait_time} + {EXTRA_WAIT} = {wait_time + EXTRA_WAIT}")
    total = wait_time + EXTRA_WAIT
    log(f"انتظار {total} ثانیه...")
    start = time.time()
    while True:
        elapsed = time.time() - start
        if total - elapsed <= 0:
            break
        time.sleep(min(60, total - elapsed))
        log(f"{int(time.time()-start)} ثانیه گذشت")
    log(f"ثبت سفارش برای {TARGET_LINK}")
    data, status, raw = api_post("api", {"code": CODE, "link": TARGET_LINK}, retries=4)
    if data is None:
        sys.exit(1)
    log(f"جواب سرور: {data}")
    if isinstance(data, dict) and data.get("error"):
        log(f"سرور خطا داد: {data['error']}")
        sys.exit(1)
    log("سفارش ثبت شد!")

if __name__ == "__main__":
    main()

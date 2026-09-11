import os
import sys
import time
import requests
from bs4 import BeautifulSoup

SITE_URL = os.getenv("SITE_URL", "https://SITE-MORDE-NAZAR.COM/PATH")
TARGET_LINK = os.getenv("TARGET_LINK", "https://LINK-SABET-SHOMA.COM/xxx")
FIELD_NAME = os.getenv("FIELD_NAME", "url")
WAIT_SECONDS = int(os.getenv("WAIT_SECONDS", "610"))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
}

def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def find_form_info(html: str, base_url: str):
    soup = BeautifulSoup(html, "html.parser")
    inputs = soup.find_all("input")
    log(f"تعداد input پیدا شده: {len(inputs)}")
    for form in soup.find_all("form"):
        names = [inp.get("name") for inp in form.find_all("input")]
        if FIELD_NAME in names:
            action = form.get("action") or base_url
            method = (form.get("method") or "post").lower()
            post_url = requests.compat.urljoin(base_url, action)
            hidden = {}
            for inp in form.find_all("input", type="hidden"):
                if inp.get("name"):
                    hidden[inp.get("name")] = inp.get("value", "")
            return post_url, method, hidden
    return base_url, "post", {}

def main():
    log(f"باز کردن سایت: {SITE_URL}")
    s = requests.Session()
    s.headers.update(HEADERS)
    r = s.get(SITE_URL, timeout=30)
    log(f"GET status: {r.status_code}")
    r.raise_for_status()
    post_url, method, hidden_fields = find_form_info(r.text, SITE_URL)
    payload = dict(hidden_fields)
    payload[FIELD_NAME] = TARGET_LINK
    log(f"ارسال لینک به {post_url}")
    if method == "get":
        r2 = s.get(post_url, params=payload, timeout=30)
    else:
        r2 = s.post(post_url, data=payload, timeout=30)
    log(f"POST status: {r2.status_code}")
    log(f"انتظار {WAIT_SECONDS} ثانیه...")
    start = time.time()
    while True:
        elapsed = time.time() - start
        remaining = WAIT_SECONDS - elapsed
        if remaining <= 0:
            break
        time.sleep(min(60, remaining))
        log(f"{int(time.time()-start)} ثانیه گذشت")
    log("تایمر تموم شد.")

if __name__ == "__main__":
    main()

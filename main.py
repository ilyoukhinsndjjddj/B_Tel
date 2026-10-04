"""
ربات smm8.com/free-telegram-members

سایت اسکریپتش رو عوض کرده (ravin.js) و دیگه با requests کار نمیکنه.
جریان جدید:
  1) باز کردن صفحه
  2) زدن لینک + کلیک روی "Get It Now"
  3) حل چک امنیتی Cloudflare Turnstile (روی چک‌باکسش کلیک میکنیم)
  4) صبر کردن تا تایمر تموم شه (تا 20 دقیقه)
  5) صفحه Thanks = سفارش ثبت شد

اگه Turnstile رد کنه، کل فلو رو از نو تلاش میکنیم (ATTEMPTS بار).
"""

import os
import random
import re
import sys
import time

from playwright.sync_api import sync_playwright

# ================= تنظیمات =================
SITE = os.getenv("SITE_URL", "https://smm8.com/free-telegram-members")
TARGET_LINK = os.getenv("TARGET_LINK", "").strip()
ATTEMPTS = int(os.getenv("ATTEMPTS", "3"))          # چند بار کل فلو رو تکرار کنیم
CAPTCHA_WAIT = int(os.getenv("CAPTCHA_WAIT", "75"))  # حداکثر صبر برای Turnstile (ثانیه)
TIMER_MAX = int(os.getenv("TIMER_MAX", "1500"))      # حداکثر صبر برای تایمر (ثانیه)
HEADLESS = os.getenv("HEADLESS", "0") == "1"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def human_click(page, x: float, y: float) -> None:
    """حرکت موس مثل انسان، بعد کلیک."""
    page.mouse.move(x - 180, y - 100)
    time.sleep(random.uniform(0.2, 0.4))
    for i in range(14):
        f = (i + 1) / 14
        page.mouse.move(
            x - 180 + 180 * f + random.uniform(-3, 3),
            y - 100 + 100 * f + random.uniform(-3, 3),
        )
        time.sleep(random.uniform(0.02, 0.06))
    time.sleep(random.uniform(0.2, 0.4))
    page.mouse.down()
    time.sleep(random.uniform(0.06, 0.13))
    page.mouse.up()


def turnstile_box(page):
    """جعبه ویجت Turnstile روی صفحه (بعد از اسکرول به داخل دید)، یا None."""
    # اول ویجت رو بیار توی دید
    try:
        page.locator(".fsc-turnstile").scroll_into_view_if_needed(timeout=3000)
        time.sleep(0.4)
    except Exception:
        pass
    for frame in page.frames:
        if "challenges.cloudflare.com" not in frame.url:
            continue
        try:
            box = frame.frame_element().bounding_box()
        except Exception:
            box = None
        if not box or box["width"] <= 50 or box["height"] <= 20:
            continue
        # اگه از دید خارجه، اسکرول کن تا بیاد داخل
        vp = page.viewport_size or {"height": 900}
        top = box["y"]
        if top < 0 or top + box["height"] > vp["height"] - 10:
            page.evaluate(
                "y => window.scrollBy(0, y)",
                top - vp["height"] / 2,
            )
            time.sleep(0.5)
            try:
                box = frame.frame_element().bounding_box()
            except Exception:
                box = None
            if not box:
                continue
        if box["y"] < 0 or box["y"] + box["height"] > vp["height"]:
            continue  # هنوز جاش درست نیست، دفعه بعد دوباره
        return box
    return None


def page_status(page) -> dict:
    """وضعیت فعلی ویجت رو جمع میکنه."""
    def vis(sel: str) -> bool:
        loc = page.locator(sel)
        return bool(loc.count()) and loc.first.is_visible()

    st = {
        "timer": vis(".timer-page"),
        "thanks": vis(".thanks-page"),
        "error": vis(".fsc-inline-error"),
        "input": vis("#inputOptinLinkLoggedIn"),
    }
    st["error_text"] = page.locator(".fsc-inline-error").inner_text() if st["error"] else ""
    if st["thanks"]:
        err_box = page.locator(".thanks-page.fsc-error")
        st["thanks_error"] = err_box.count() > 0
        st["thanks_text"] = page.locator(".thanks-page").inner_text().replace("\n", " ")[:300]
    else:
        st["thanks_error"] = False
        st["thanks_text"] = ""
    return st


def wait_for_submit(page, timeout: int) -> str:
    """بعد از تایمر، صبر میکنه تا پاسخ /api/api بیاد و صفحه Thanks دیده بشه."""
    end = time.time() + timeout
    while time.time() < end:
        st = page_status(page)
        if st["thanks"]:
            return "error" if st["thanks_error"] else "success"
        time.sleep(1)
    return "timeout"


def save_shot(page, attempt: int, tag: str) -> None:
    """اسکرین‌شات برای دیباگ (روی گیتهاب آپلود میشه)."""
    try:
        os.makedirs("debug", exist_ok=True)
        path = os.path.join("debug", f"attempt{attempt}_{tag}.png")
        page.screenshot(path=path, full_page=False)
        log(f"اسکرین‌شات ذخیره شد: {path}")
    except Exception:
        pass


def run_attempt(browser, attempt: int) -> tuple:
    """
    یکبار کل فلو. خروجی:
      ("retry", دلیل)     -> کل فلو رو دوباره بزن
      ("done", دلیل)      -> تموم شد (موفق یا خطای سروری که تکرارش بی‌فایده‌ست)
    """
    ctx = browser.new_context(
        user_agent=UA,
        viewport={"width": 1366, "height": 900},
        locale="en-US",
        timezone_id="UTC",
    )
    page = ctx.new_page()
    api_log = []

    def on_resp(resp):
        if "/api/" in resp.url and not resp.url.endswith(("style.css", ".js")):
            try:
                body = resp.text()[:200]
            except Exception:
                body = "?"
            api_log.append((resp.status, resp.url.rsplit("/api/", 1)[-1], body))

    page.on("response", on_resp)

    try:
        log(f"تلاش {attempt}/{ATTEMPTS}: باز کردن صفحه...")
        page.goto(SITE, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("#inputOptinLinkLoggedIn", timeout=40000)
        log(f"لینک رو میذارم: {TARGET_LINK}")
        page.fill("#inputOptinLinkLoggedIn", TARGET_LINK)
        page.bring_to_front()
        time.sleep(0.3)
        page.click("#btnOptinLoggedIn")
        log("دکمه Get It Now زده شد، منتظر چک امنیتی...")

        # ---- مرحله Turnstile ----
        clicked_ts = False
        flow_start = time.time()
        end = time.time() + CAPTCHA_WAIT
        while time.time() < end:
            st = page_status(page)
            if st["timer"]:
                log

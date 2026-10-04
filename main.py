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
                log("چک امنیتی رد شد! تایمر شروع شد.")
                break
            if st["error"]:
                log(f"خطای ویجت: {st['error_text']}")
                save_shot(page, attempt, "captcha")
                return "retry", st["error_text"]
            box = turnstile_box(page)
            # ویجت اول حدود 12 ثانیه مخفیه، بعد میگه "Verify you are human"
            if box and not clicked_ts and time.time() - flow_start > 12:
                x = box["x"] + 24
                y = box["y"] + box["height"] / 2
                page.bring_to_front()
                human_click(page, x, y)
                log(f"روی چک‌باکس Turnstile کلیک شد ({int(x)},{int(y)})")
                clicked_ts = True
            time.sleep(1)
        else:
            log("چک امنیتی در زمان مقرر تموم نشد.")
            save_shot(page, attempt, "captcha-timeout")
            return "retry", "captcha timeout"

        st = page_status(page)
        if not st["timer"]:
            return "retry", "timer did not start"

        # ---- مرحله تایمر ----
        raw = page.locator("#timeTimer").inner_text().strip()
        total = 0
        if re.match(r"^\d+:\d+:\d+$", raw):
            h, m, s = (int(v) for v in raw.split(":"))
            total = h * 3600 + m * 60 + s
        elif re.match(r"^\d+:\d+$", raw):
            m, s = (int(v) for v in raw.split(":"))
            total = m * 60 + s
        if total <= 0:
            total = TIMER_MAX
        # بافر کوچیک تا پست شدن
        wait_sec = min(total + 5, TIMER_MAX)
        log(f"تایمر {raw} = {total} ثانیه. تا {wait_sec} ثانیه صبر میکنم...")

        end = time.time() + wait_sec
        last = -1
        while time.time() < end:
            left = int(end - time.time())
            if left != last and left % 60 == 0:
                log(f"... {left} ثانیه مونده")
                last = left
            st = page_status(page)
            if st["thanks"]:
                break
            if st["error"]:
                log(f"خطا وسط تایمر: {st['error_text']}")
                return "retry", st["error_text"]
            time.sleep(1)

        # ---- مرحله ثبت سفارش ----
        result = wait_for_submit(page, timeout=60)
        st = page_status(page)
        for item in api_log[-4:]:
            log(f"  api: {item[0]} {item[1]} -> {item[2]}")
        if result == "success":
            log(f"ثبت سفارش موفق: {st['thanks_text']}")
            return "done", "success"
        if result == "error":
            msg = st["thanks_text"] or "unknown"
            log(f"سرور خطا داد: {msg}")
            save_shot(page, attempt, "submit")
            # خطاهایی که با تلاش فوری درست نمیشن
            if any(k in msg for k in ("Daily", "funds", "balance", "30 Minutes", "Completed", "rate")):
                return "done", msg
            return "retry", msg
        log("پاسخ ثبت سفارش نیومد.")
        save_shot(page, attempt, "no-submit")
        return "retry", "submit timeout"

    except Exception as exc:
        log(f"استثناء: {exc}")
        try:
            save_shot(page, attempt, "exception")
        except Exception:
            pass
        return "retry", str(exc)
    finally:
        try:
            ctx.close()
        except Exception:
            pass


def main() -> int:
    if not TARGET_LINK or "YOUR" in TARGET_LINK.upper():
        log("TARGET_LINK ست نشده! مثال: TARGET_LINK=https://t.me/mychannel")
        return 1
    if not TARGET_LINK.startswith("http"):
        log(f"TARGET_LINK باید لینک باشه: {TARGET_LINK}")
        return 1

    log(f"هدف: {SITE}")
    log(f"لینک: {TARGET_LINK}")

    last_reason = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-background-timer-throttling",
                "--window-size=1366,900",
            ],
        )
        try:
            for attempt in range(1, ATTEMPTS + 1):
                outcome, reason = run_attempt(browser, attempt)
                last_reason = reason
                if outcome == "done":
                    if reason == "success":
                        log("✅ همه‌چیز موفق بود.")
                        return 0
                    log(f"⛔ تلاش متوقف شد: {reason}")
                    return 1
                if attempt < ATTEMPTS:
                    wait = 10 * attempt
                    log(f"تلاش بعدی بعد از {wait} ثانیه...")
                    time.sleep(wait)
        finally:
            try:
                browser.close()
            except Exception:
                pass

    log(f"❌ بعد از {ATTEMPTS} تلاش موفق نشدیم. آخرین دلیل: {last_reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

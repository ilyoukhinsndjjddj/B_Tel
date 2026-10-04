import os
import random
import re
import sys
import time

from patchright.sync_api import sync_playwright

SITE = os.getenv("SITE_URL", "https://smm8.com/free-telegram-members")
TARGET_LINK = os.getenv("TARGET_LINK", "").strip()
ATTEMPTS = int(os.getenv("ATTEMPTS", "3"))
CAPTCHA_WAIT = int(os.getenv("CAPTCHA_WAIT", "75"))
TIMER_MAX = int(os.getenv("TIMER_MAX", "1500"))
HEADLESS = os.getenv("HEADLESS", "0") == "1"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def shot(page, n, tag):
    try:
        os.makedirs("debug", exist_ok=True)
        page.screenshot(path=f"debug/a{n}_{tag}.png")
        log(f"اسکرین‌شات: debug/a{n}_{tag}.png")
    except Exception:
        pass


def click_human(page, x, y):
    page.mouse.move(x - 180, y - 100)
    time.sleep(random.uniform(0.2, 0.4))
    for i in range(14):
        f = (i + 1) / 14
        page.mouse.move(x - 180 + 180 * f + random.uniform(-3, 3),
                        y - 100 + 100 * f + random.uniform(-3, 3))
        time.sleep(random.uniform(0.02, 0.06))
    time.sleep(random.uniform(0.2, 0.4))
    page.mouse.down()
    time.sleep(random.uniform(0.06, 0.13))
    page.mouse.up()


def widget_box(page, timeout=45):
    """صبر میکنه تا ویجت Turnstile واقعاً رندر بشه (نه iframe 1x1)."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            fr = page.locator(".fsc-turnstile iframe")
            if fr.count():
                b = fr.first.bounding_box()
                if b and b["width"] > 250 and b["height"] > 50:
                    return b
        except Exception:
            pass
        time.sleep(0.5)
    return None


def click_widget(page):
    """کلیک روی چک‌باکس ویجت: اول روی المنت واقعی، بعد با مختصات انسانی."""
    b = widget_box(page)
    if not b:
        return False
    try:
        page.locator(".fsc-turnstile").scroll_into_view_if_needed(timeout=3000)
        time.sleep(0.5)
        b = page.locator(".fsc-turnstile iframe").first.bounding_box()
    except Exception:
        pass
    if not b:
        return False
    vp = page.viewport_size or {"height": 900}
    if b["y"] < 0 or b["y"] + b["height"] > vp["height"] - 10:
        try:
            page.mouse.wheel(0, b["y"] - vp["height"] / 2)
            time.sleep(0.6)
            b = page.locator(".fsc-turnstile iframe").first.bounding_box()
        except Exception:
            pass
        if not b:
            return False
    try:
        inp = page.frame_locator(".fsc-turnstile iframe").locator("input")
        if inp.count() > 0 and inp.first.is_visible():
            inp.first.click(timeout=4000)
            log("روی چک‌باکس واقعی (input) کلیک شد")
            return True
    except Exception as exc:
        log(f"کلیک روی input جواب نداد ({str(exc)[:60]})، میام سراغ مختصات")
    x = b["x"] + 21
    y = b["y"] + b["height"] / 2
    page.bring_to_front()
    click_human(page, x, y)
    log(f"روی چک‌باکس کلیک شد ({int(x)},{int(y)})")
    return True


def status(page):
    def vis(sel):
        loc = page.locator(sel)
        return bool(loc.count()) and loc.first.is_visible()

    st = {"timer": vis(".timer-page"), "thanks": vis(".thanks-page"),
          "err": vis(".fsc-inline-error")}
    st["err_text"] = page.locator(".fsc-inline-error").inner_text() if st["err"] else ""
    if st["thanks"]:
        st["bad"] = page.locator(".thanks-page.fsc-error").count() > 0
        st["msg"] = page.locator(".thanks-page").inner_text().replace("\n", " ")[:300]
    else:
        st["bad"] = False
        st["msg"] = ""
    return st


def attempt(browser, n):
    ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 900},
                              locale="en-US", timezone_id="UTC")
    page = ctx.new_page()
    api = []

    def on_resp(resp):
        if "/api/" in resp.url and not resp.url.endswith(("style.css", ".js")):
            try:
                body = resp.text()[:200]
            except Exception:
                body = "?"
            api.append((resp.status, resp.url.rsplit("/api/", 1)[-1], body))

    page.on("response", on_resp)
    try:
        log(f"تلاش {n}/{ATTEMPTS}: باز کردن صفحه...")
        page.goto(SITE, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("#inputOptinLinkLoggedIn", timeout=40000)
        log(f"لینک: {TARGET_LINK}")
        page.fill("#inputOptinLinkLoggedIn", TARGET_LINK)
        page.bring_to_front()
        time.sleep(0.3)
        page.click("#btnOptinLoggedIn")
        log("دکمه Get It Now زده شد، منتظر چک امنیتی...")

        clicked = False
        start = time.time()
        end = start + CAPTCHA_WAIT
        while time.time() < end:
            st = status(page)
            if st["timer"]:
                log("چک امنیتی رد شد، تایمر شروع شد.")
                break
            if st["err"]:
                log(f"خطای ویجت: {st['err_text']}")
                shot(page, n, "captcha")
                return "retry", st["err_text"]
            if not clicked and widget_box(page, timeout=5):
                log("ویجت آماده شد، دارم کلیک میکنم...")
                clicked = click_widget(page)
                time.sleep(1)
                continue
            time.sleep(1)
        else:
            log("چک امنیتی در زمان مقرر تموم نشد.")
            shot(page, n, "captcha-timeout")
            return "retry", "captcha timeout"

        if not status(page)["timer"]:
            return "retry", "timer did not start"

        raw = page.locator("#timeTimer").inner_text().strip()
        if re.match(r"^\d+:\d+:\d+$", raw):
            h, m, s = (int(v) for v in raw.split(":"))
            total = h * 3600 + m * 60 + s
        elif re.match(r"^\d+:\d+$", raw):
            m, s = (int(v) for v in raw.split(":"))
            total = m * 60 + s
        else:
            total = 0
        if total <= 0:
            total = TIMER_MAX
        wait = min(total + 5, TIMER_MAX)
        log(f"تایمر {raw} = {total} ثانیه. تا {wait} ثانیه صبر میکنم...")

        end = time.time() + wait
        last = -1
        while time.time() < end:
            left = int(end - time.time())
            if left != last and left % 60 == 0:
                log(f"... {left} ثانیه مونده")
                last = left
            st = status(page)
            if st["thanks"]:
                break
            if st["err"]:
                log(f"خطا وسط تایمر: {st['err_text']}")
                shot(page, n, "timer")
                return "retry", st["err_text"]
            time.sleep(1)

        res = "timeout"
        end = time.time() + 60
        while time.time() < end:
            st = status(page)
            if st["thanks"]:
                res = "error" if st["bad"] else "success"
                break
            time.sleep(1)
        st = status(page)
        for item in api[-4:]:
            log(f"  api: {item[0]} {item[1]} -> {item[2]}")
        if res == "success":
            log(f"ثبت سفارش موفق: {st['msg']}")
            return "done", "success"
        if res == "error":
            log(f"سرور خطا داد: {st['msg']}")
            shot(page, n, "submit")
            if any(k in st["msg"] for k in
                   ("Daily", "funds", "balance", "30 Minutes", "Completed", "rate")):
                return "done", st["msg"]
            return "retry", st["msg"]
        log("پاسخ ثبت سفارش نیومد.")
        shot(page, n, "no-submit")
        return "retry", "submit timeout"
    except Exception as exc:
        log(f"استثناء: {exc}")
        shot(page, n, "exception")
        return "retry", str(exc)
    finally:
        try:
            ctx.close()
        except Exception:
            pass


def main():
    if not TARGET_LINK or "YOUR" in TARGET_LINK.upper():
        log("TARGET_LINK ست نشده! مثال: TARGET_LINK=https://t.me/mychannel")
        return 1
    if not TARGET_LINK.startswith("http"):
        log(f"TARGET_LINK باید لینک باشه: {TARGET_LINK}")
        return 1
    log(f"هدف: {SITE}")
    log(f"لینک: {TARGET_LINK}")
    last = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chromium", headless=HEADLESS, args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling",
            "--window-size=1366,900",
        ])
        try:
            for n in range(1, ATTEMPTS + 1):
                out, why = attempt(browser, n)
                last = why
                if out == "done":
                    if why == "success":
                        log("همه‌چیز موفق بود.")
                        return 0
                    log(f"تلاش متوقف شد: {why}")
                        return 1
                if n < ATTEMPTS:
                    wait = 10 * n
                    log(f"تلاش بعدی بعد از {wait} ثانیه...")
                    time.sleep(wait)
        finally:
            try:
                browser.close()
            except Exception:
                pass
    log(f"بعد از {ATTEMPTS} تلاش موفق نشدیم. آخرین دلیل: {last}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

"""Keeps the Streamlit dashboard from going to sleep.

Streamlit Community Cloud puts an app to sleep after a stretch with no visitors. A sleeping
app shows a page with a "get this app back up" button instead of the dashboard, and a plain
HTTP ping doesn't count as a visit. So GitHub Actions runs this every 4 hours: it opens the
app in a headless browser, clicks that button if it's there, and then checks that the
dashboard itself really shows up before staying long enough to count as a visitor.

  python scripts/keep_awake.py [url]

It drives the Google Chrome that GitHub's Ubuntu runners already have, so a run has nothing
to download. Anywhere without Chrome, it falls back to Playwright's own Chromium, which
python -m playwright install chromium puts in place.

It doesn't trust the absence of a button. The run passes only when the dashboard's own
"Risk flags" tab appears, and otherwise it fails, which makes GitHub email you. Either way
it saves keep_awake.png, which the workflow keeps with the run, to show what it saw.
"""
import re
import sys
import time

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

URL = "https://shortagesignal.streamlit.app"
WAKE_TEXT = re.compile(r"get this app back up", re.IGNORECASE)
APP_TEXT = re.compile(r"Risk flags")       # a tab label on the dashboard itself
SCREENSHOT = "keep_awake.png"


def visible_in_any_frame(page, pattern):
    """The first visible element matching pattern, in the page or any iframe, or None.
    Streamlit Cloud shows the app inside an iframe, so the top page alone isn't enough."""
    for frame in page.frames:
        try:
            match = frame.get_by_text(pattern).first
            if match.count() and match.is_visible():
                return match
        except PlaywrightError:
            continue      # a frame can go away while the page loads
    return None


def wait_for_app(page, seconds):
    """True once the dashboard's own content shows, within seconds."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if visible_in_any_frame(page, APP_TEXT):
            return True
        page.wait_for_timeout(3_000)
    return False


def launch(p):
    """The Chrome already installed on the machine, or Playwright's own Chromium."""
    try:
        return p.chromium.launch(channel="chrome")
    except PlaywrightError:
        return p.chromium.launch()


def main(url=URL):
    with sync_playwright() as p:
        browser = launch(p)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(15_000)   # give Streamlit time to show either the app or the sleep page

        button = visible_in_any_frame(page, WAKE_TEXT)
        if button:
            print("The app was asleep, so the wake button was clicked.")
            button.click()
            loaded = wait_for_app(page, 300)      # waking can take a few minutes
        else:
            loaded = wait_for_app(page, 120)
            print("The app was awake." if loaded else
                  "There was no wake button, and the dashboard didn't load either.")

        page.screenshot(path=SCREENSHOT, full_page=True)
        if not loaded:
            browser.close()
            sys.exit("The dashboard didn't load. The screenshot saved with this run shows what "
                     "the page looked like.")
        page.wait_for_timeout(30_000)   # stay a while, so the visit counts as traffic
        browser.close()
        print("Visited", url, "and the dashboard loaded.")


if __name__ == "__main__":
    main(*sys.argv[1:2])

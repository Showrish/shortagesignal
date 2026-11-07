"""Keeps the Streamlit dashboard from going to sleep.

Streamlit Community Cloud puts an app to sleep after a stretch with no visitors. A sleeping
app shows a "Yes, get this app back up!" button instead of the dashboard, and a plain HTTP
ping doesn't count as a visit. So GitHub Actions runs this every 6 hours: it opens the app in
a headless browser, clicks that button if it's there, and stays long enough to be a visitor.

  python scripts/keep_awake.py [url]

It fails, and GitHub emails you, only when the app is asleep and won't wake up.
"""
import sys

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

URL = "https://shortagesignal.streamlit.app"
WAKE_BUTTON = "Yes, get this app back up!"


def main(url=URL):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        button = page.get_by_role("button", name=WAKE_BUTTON)
        try:
            button.wait_for(state="visible", timeout=20_000)
        except PlaywrightTimeout:
            print("The app was awake.")
        else:
            button.click()
            print("The app was asleep, so the wake button was clicked.")
            try:
                button.wait_for(state="hidden", timeout=120_000)
            except PlaywrightTimeout:
                browser.close()
                sys.exit("The app is still asleep two minutes after clicking the wake button.")
        # stay a while, so the visit opens a real session and counts as traffic
        page.wait_for_timeout(30_000)
        browser.close()
        print("Visited", url)


if __name__ == "__main__":
    main(*sys.argv[1:2])

"""Adds the live dashboard link and status badges under the README's title. Safe to run twice."""
from pathlib import Path

BLOCK = """
[![Daily pipeline](https://github.com/Showrish/shortagesignal/actions/workflows/daily.yml/badge.svg)](https://github.com/Showrish/shortagesignal/actions/workflows/daily.yml)
[![CI](https://github.com/Showrish/shortagesignal/actions/workflows/ci.yml/badge.svg)](https://github.com/Showrish/shortagesignal/actions/workflows/ci.yml)
[![Weekly digest](https://github.com/Showrish/shortagesignal/actions/workflows/weekly.yml/badge.svg)](https://github.com/Showrish/shortagesignal/actions/workflows/weekly.yml)

**Live dashboard:** [shortagesignal.streamlit.app](https://shortagesignal.streamlit.app)
"""

readme = Path("README.md")
lines = readme.read_text(encoding="utf-8").splitlines(keepends=True)
text = "".join(lines)
if "shortagesignal.streamlit.app" in text:
    print("README.md: already has the dashboard link")
else:
    title = next((i for i, line in enumerate(lines) if line.startswith("# ")), None)
    if title is None:
        readme.write_text(BLOCK.lstrip("\n") + "\n" + text, encoding="utf-8")
    else:
        lines.insert(title + 1, BLOCK)
        readme.write_text("".join(lines), encoding="utf-8")
    print("README.md: updated")

"""Screenshot an HTML page at desktop/phone widths in light/dark for visual review.

uv run python scripts/screenshot.py site/2026-09-25/index.html --out screenshots/ --full

Uses Playwright's Chromium when installed. On WSL without it, falls back to the Windows Chrome in
headless mode (DECISIONS D-11): phone width is then 512px (Chrome's minimum) and dark mode is skipped.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

VIEWPORTS = {"desktop": (1280, 900), "phone": (390, 844)}
WIN_CHROME = Path("/mnt/c/Program Files/Google/Chrome/Application/chrome.exe")


def with_playwright(html: Path, out: Path, schemes: list[str], full: bool) -> bool:
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for vp, (w, h) in VIEWPORTS.items():
                for scheme in schemes:
                    page = browser.new_page(viewport={"width": w, "height": h}, color_scheme=scheme)  # type: ignore[arg-type]
                    page.goto(html.resolve().as_uri(), wait_until="networkidle")
                    overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
                    path = out / f"{html.parent.name}-{vp}-{scheme}.png"
                    page.screenshot(path=str(path), full_page=full)
                    print(f"{path}{'  [horizontal overflow!]' if overflow else ''}")
                    page.close()
            browser.close()
    except Error as e:
        if "Executable doesn't exist" in str(e):
            return False
        raise
    return True


def _winpath(p: Path) -> str:
    return subprocess.run(
        ["wslpath", "-w", str(p.resolve())], capture_output=True, text=True, check=True
    ).stdout.strip()


def with_windows_chrome(html: Path, out: Path, full: bool) -> None:
    if not WIN_CHROME.exists() or not shutil.which("wslpath"):
        raise SystemExit("No browser available: install Playwright Chromium or run on WSL with Chrome")
    url = "file:///" + _winpath(html).replace("\\", "/")
    for vp, (w, h) in {"desktop": (1280, 900), "phone": (512, 900)}.items():
        path = out / f"{html.parent.name}-{vp}-light.png"
        height = 6000 if full else h
        subprocess.run(
            [
                str(WIN_CHROME),
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                f"--window-size={w},{height}",
                "--virtual-time-budget=8000",
                f"--screenshot={_winpath(out.resolve())}\\{path.name}",
                url,
            ],
            capture_output=True,
            check=True,
            timeout=120,
        )
        print(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("html", type=Path)
    ap.add_argument("--out", type=Path, default=Path("screenshots"))
    ap.add_argument("--schemes", default="light,dark")
    ap.add_argument("--full", action="store_true", help="full-page screenshots")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if not with_playwright(args.html, args.out, args.schemes.split(","), args.full):
        print("Playwright Chromium not installed; using Windows Chrome fallback")
        with_windows_chrome(args.html, args.out, args.full)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Verify the production/development split.

Development shows the full operator manual and demo credentials.
Production shows only end-user content: no setup, settings or troubleshooting
chapters, no demo account passwords anywhere in the served HTML.

Usage:
    python tests/prod_mode.py [dev_url] [prod_url]
Defaults: http://127.0.0.1:8000  http://127.0.0.1:8100
"""
from __future__ import annotations

import sys
import urllib.request

from playwright.sync_api import sync_playwright

DEV = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
PROD = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8100"

OPERATOR_CHAPTERS = ["Getting started", "Settings & configuration", "Troubleshooting"]
SECRETS = ["supervisor123", "intern123", "admin123", "viewer123"]

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"

passed = failed = 0
console_errors: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  {GREEN}[PASS]{RESET} {name} {DIM}{detail}{RESET}")
    else:
        failed += 1
        print(f"  {RED}[FAIL]{RESET} {name} {DIM}{detail}{RESET}")


def http_status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def nav(page, url: str):
    page.goto(url, wait_until="networkidle", timeout=45_000)
    # the manual gates on /api/config; give the fetch a beat to settle
    page.wait_for_timeout(600)


def chapter_titles(page) -> list[str]:
    return page.eval_on_selector_all(
        "section[id] > div + h2, section[id] h2",
        "els => els.map(e => e.textContent.trim())",
    )



CHIP_JS = """els => els
    .filter(e => e.children.length === 0 && /screenshots/i.test(e.textContent))
    .map(e => e.parentElement.textContent.replace(/\\s+/g, ''))"""


def screenshot_chip(page) -> str:
    hits = page.eval_on_selector_all("*", CHIP_JS)
    return hits[0] if hits else ""


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()

        def fresh():
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            pg = ctx.new_page()
            pg.on(
                "console",
                lambda m: console_errors.append(f"{m.type}: {m.text}")
                if m.type == "error"
                else None,
            )
            return ctx, pg

        # ---------------- API ----------------
        print("\n-- api --")
        import json

        dev_cfg = json.loads(urllib.request.urlopen(f"{DEV}/api/config", timeout=10).read())
        prod_cfg = json.loads(urllib.request.urlopen(f"{PROD}/api/config", timeout=10).read())
        check("dev reports is_production=false", dev_cfg.get("is_production") is False,
              f"environment={dev_cfg.get('environment')!r}")
        check("prod reports is_production=true", prod_cfg.get("is_production") is True,
              f"environment={prod_cfg.get('environment')!r}")

        dev_demo = http_status(f"{DEV}/api/auth/demo-accounts")
        prod_demo = http_status(f"{PROD}/api/auth/demo-accounts")
        check("demo accounts served in dev", dev_demo == 200, f"HTTP {dev_demo}")
        check("demo accounts hidden in prod", prod_demo == 404, f"HTTP {prod_demo}")

        # ---------------- manual: development ----------------
        print("\n-- manual (development) --")
        ctx, page = fresh()
        nav(page, f"{DEV}/manual")
        dev_titles = chapter_titles(page)
        dev_nav = page.eval_on_selector_all(
            "aside a[href^='#']", "els => els.map(e => e.textContent.trim())"
        )
        check("all 16 chapters render", len(dev_titles) == 16, f"{len(dev_titles)} sections")
        check("sidebar lists 16 chapters", len(dev_nav) == 16, f"{len(dev_nav)} links")
        missing = [c for c in OPERATOR_CHAPTERS if not any(c in t for t in dev_titles)]
        check("operator chapters present", not missing, f"missing={missing}" if missing else "")
        body = page.inner_text("body")
        check("demo passwords documented", any(s in body for s in SECRETS))
        dev_shots = len(page.eval_on_selector_all(
            "img", "els => els.map(e => e.getAttribute('src') || '').filter(s => s.includes('/manual/'))"))
        chip = screenshot_chip(page)
        check("hero counts match reality",
              dev_shots == 16 and chip == "16screenshots",
              f"{len(dev_titles)} chapters, {dev_shots} screenshots, chip={chip!r}")
        ctx.close()

        # ---------------- manual: production ----------------
        print("\n-- manual (production) --")
        ctx, page = fresh()
        nav(page, f"{PROD}/manual")
        prod_titles = chapter_titles(page)
        prod_nav = page.eval_on_selector_all(
            "aside a[href^='#']", "els => els.map(e => e.textContent.trim())"
        )
        check("12 chapters render", len(prod_titles) == 12, f"{len(prod_titles)} sections")
        check("sidebar lists 12 chapters", len(prod_nav) == 12, f"{len(prod_nav)} links")
        leaked = [c for c in OPERATOR_CHAPTERS if any(c in t for t in prod_titles)]
        check("operator chapters hidden", not leaked, f"leaked={leaked}" if leaked else "")

        body = page.inner_text("body")
        leaked_secrets = [s for s in SECRETS if s in body]
        check("no demo passwords in text", not leaked_secrets,
              f"leaked={leaked_secrets}" if leaked_secrets else "")
        leaked_env = [t for t in ["ATLAS_SECRET_KEY", "ATLAS_SEED_DEMO_DATA",
                                  "ATLAS_PUBLIC_BASE_URL", "ATLAS_GITHUB_TOKEN"] if t in body]
        check("no env-var config in text", not leaked_env,
              f"leaked={leaked_env}" if leaked_env else "")

        # numbering must stay contiguous 01..12
        eyebrows = page.eval_on_selector_all(
            "section[id] .eyebrow", "els => els.map(e => e.textContent.trim())"
        )
        chapters_only = [e for e in eyebrows if e.startswith("Chapter ")]
        expected = [f"Chapter {i:02d}" for i in range(1, 13)]
        check("chapter numbers are contiguous", chapters_only == expected,
              f"{chapters_only[:3]}...{chapters_only[-1:]}" if chapters_only else "none")

        # figures must follow their chapter
        figs = page.eval_on_selector_all(
            "figcaption", "els => els.map(e => e.textContent.trim())"
        )
        bad_figs = [f for f in figs if f.startswith("Fig. 12") or f.startswith("Fig. 13")]
        check("figure numbers stay in range", not bad_figs, f"{len(figs)} figures")

        prod_shots = len(page.eval_on_selector_all(
            "img", "els => els.map(e => e.getAttribute('src') || '').filter(s => s.includes('/manual/'))"))
        chip = screenshot_chip(page)
        check("hero screenshot count matches the page",
              prod_shots == 15 and chip == "15screenshots",
              f"{prod_shots} screenshots rendered, chip={chip!r}")
        broken_shots = page.eval_on_selector_all(
            "img", "els => els.filter(e => (e.getAttribute('src')||'').includes('/manual/') && e.complete && e.naturalWidth === 0).length")
        check("no broken screenshots", broken_shots == 0)

        anchors = page.eval_on_selector_all(
            "aside a[href^='#']", "els => els.map(e => e.getAttribute('href').slice(1))"
        )
        broken = [a for a in anchors if page.query_selector(f"#{a}") is None]
        check("every sidebar link resolves", not broken, f"broken={broken}" if broken else "")
        ctx.close()

        # ---------------- shipped bundle ----------------
        # The manual and login page render credentials conditionally, but a
        # static export ships BOTH branches. Fetching them keeps the passwords
        # out of the JavaScript entirely - assert that stays true.
        print("\n-- shipped javascript --")
        ctx, page = fresh()
        nav(page, f"{PROD}/manual")
        scripts = page.eval_on_selector_all(
            "script[src]", "els => els.map(e => e.getAttribute('src'))")
        nav(page, f"{PROD}/login")
        scripts += page.eval_on_selector_all(
            "script[src]", "els => els.map(e => e.getAttribute('src'))")
        ctx.close()

        leaks: list[str] = []
        for src in sorted(set(scripts)):
            url = src if src.startswith("http") else f"{PROD}{src}"
            try:
                body = urllib.request.urlopen(url, timeout=15).read().decode("utf-8", "ignore")
            except Exception:
                continue
            for secret in SECRETS:
                if secret in body:
                    leaks.append(f"{secret} in {src.split('/')[-1]}")
        check("no passwords compiled into the JS", not leaks,
              f"{len(set(scripts))} scripts scanned" if not leaks else f"leaks={leaks}")

        # ---------------- login page ----------------
        print("\n-- login page --")
        ctx, page = fresh()
        nav(page, f"{DEV}/login")
        dev_login = page.inner_text("body")
        check("dev shows demo accounts", "DEMO ACCOUNTS" in dev_login)
        check("dev prefills the form",
              page.input_value("input[type=email]") == "supervisor@atlas.id")
        ctx.close()

        ctx, page = fresh()
        nav(page, f"{PROD}/login")
        prod_login = page.inner_text("body")
        check("prod hides demo accounts", "DEMO ACCOUNTS" not in prod_login)
        leaked_secrets = [s for s in SECRETS if s in prod_login]
        check("prod leaks no passwords", not leaked_secrets,
              f"leaked={leaked_secrets}" if leaked_secrets else "")
        check("prod leaves the form empty",
              page.input_value("input[type=email]") == "" and
              page.input_value("input[type=password]") == "")
        check("prod still links to the manual", page.query_selector("a[href='/manual']") is not None)
        ctx.close()

        browser.close()

    print()
    real_errors = [e for e in console_errors if "404" not in e and "demo-accounts" not in e]
    total = passed + failed
    if failed:
        print(f"{RED}=== {passed}/{total} checks passed, {failed} failed ==={RESET}")
    else:
        print(f"{GREEN}=== {passed}/{total} checks passed ==={RESET}")
    print(f"console errors: {'none' if not real_errors else real_errors}")
    return 1 if failed or real_errors else 0


if __name__ == "__main__":
    sys.exit(main())

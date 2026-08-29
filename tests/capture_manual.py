#!/usr/bin/env python
"""
Recapture every screenshot used by the user manual.

    ../.venv/bin/python tests/capture_manual.py [base_url]

Drives a running ATLAS instance, photographs each page, then downsamples the
2x captures to optimised JPEGs in frontend/public/manual/.

Run this after any visual change so the manual never shows a stale interface.
Then rebuild:  python run.py --build
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip('/') if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'frontend' / 'public' / 'manual'

SUPERVISOR = ('supervisor@atlas.id', 'supervisor123')
INTERN = ('intern@atlas.id', 'intern123')

# page captures: (path, filename, settle_ms)
PAGES = [
    ('/curriculum', '03-curriculum', 2200),
    ('/curriculum/view?slug=predictive-maintenance', '04-topic-detail', 2500),
    ('/playground', '08-playground', 2600),
    ('/playground?topic=6', '09-playground-gpu', 2800),
    ('/datasets', '10-datasets', 2400),
    ('/datasets?tab=decks', '11-decks', 2200),
    ('/deployment', '12-deployment', 2600),
    ('/portal', '13-portal', 2200),
    ('/leaderboard', '14-leaderboard', 2000),
    ('/settings', '15-settings', 2000),
]


def sign_in(pg, creds) -> None:
    pg.goto(f'{BASE}/login', wait_until='networkidle')
    pg.wait_for_timeout(1200)
    pg.fill('input[name=email]', creds[0])
    pg.fill('input[name=password]', creds[1])
    pg.click('button[type=submit]')
    pg.wait_for_url('**/dashboard', timeout=20000)
    pg.wait_for_timeout(2500)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    taken: list[str] = []

    def shot(pg, name: str) -> None:
        pg.screenshot(path=str(OUT / f'{name}.png'))
        taken.append(name)
        print(f'  captured {name}')

    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--force-color-profile=srgb'])
        # wide viewport so right-hand rails are never clipped
        ctx = browser.new_context(viewport={'width': 1680, 'height': 1000},
                                  device_scale_factor=2)
        pg = ctx.new_page()
        errors: list[str] = []
        pg.on('console', lambda m: errors.append(m.text[:90]) if m.type == 'error' else None)

        print('capturing desktop pages...')
        pg.goto(f'{BASE}/login', wait_until='networkidle'); pg.wait_for_timeout(1600)
        shot(pg, '01-login')

        sign_in(pg, SUPERVISOR)
        shot(pg, '02-dashboard')

        for path, name, settle in PAGES:
            pg.goto(f'{BASE}{path}', wait_until='networkidle')
            pg.wait_for_timeout(settle)
            shot(pg, name)

        # architecture block lives inside the Blueprint stage
        pg.goto(f'{BASE}/curriculum/view?slug=corrosion-segmentation', wait_until='networkidle')
        pg.wait_for_timeout(2400)
        stage = pg.locator("button:has-text('Read the Blueprint')").first
        if stage.count():
            stage.click(); pg.wait_for_timeout(1800)
        shot(pg, '05-architecture')

        # lesson editor, on an existing lesson so it shows real blocks
        ctx2 = browser.new_context(viewport={'width': 1440, 'height': 900}, device_scale_factor=2)
        pg2 = ctx2.new_page()
        sign_in(pg2, SUPERVISOR)
        pg2.goto(f'{BASE}/curriculum/view?slug=predictive-maintenance', wait_until='networkidle')
        pg2.wait_for_timeout(2400)
        for sel in ("button[title*='Edit']", "button[aria-label*='Edit']"):
            el = pg2.locator(sel).first
            if el.count():
                el.click(); pg2.wait_for_timeout(1700)
                if pg2.locator('text=Content blocks').count():
                    break
        if pg2.locator('text=Content blocks').count():
            shot(pg2, '06-cms-editor')
            ab = pg2.locator("button:has-text('Add block')").first
            if ab.count():
                ab.click(); pg2.wait_for_timeout(1500)
                shot(pg2, '07-block-palette')
        else:
            print('  WARNING: lesson editor did not open; keeping previous shots')
        ctx2.close()

        print('  console errors:', errors[:3] if errors else 'none')
        ctx.close()

        # mobile
        print('capturing mobile...')
        m = browser.new_context(viewport={'width': 390, 'height': 844},
                                device_scale_factor=3, is_mobile=True, has_touch=True)
        mp = m.new_page()
        sign_in(mp, INTERN)
        shot(mp, '16-mobile')
        m.close()
        browser.close()

    # optimise
    print('\noptimising...')
    try:
        from PIL import Image
    except ImportError:
        print('  Pillow not installed - leaving PNGs in place')
        print('  pip install pillow, then rerun to shrink them')
        return 0

    before = after = 0
    for name in taken:
        png = OUT / f'{name}.png'
        if not png.exists():
            continue
        before += png.stat().st_size
        im = Image.open(png).convert('RGB')
        im = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)
        jpg = OUT / f'{name}.jpg'
        im.save(jpg, 'JPEG', quality=86, optimize=True, progressive=True)
        after += jpg.stat().st_size
        png.unlink()

    if before:
        print(f'  {before // 1024} KB -> {after // 1024} KB '
              f'({100 - after * 100 // before}% smaller)')
    print(f'\n{len(taken)} screenshots written to {OUT.relative_to(ROOT)}')
    print('rebuild with:  python run.py --build')
    return 0


if __name__ == '__main__':
    sys.exit(main())

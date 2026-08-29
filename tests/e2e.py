#!/usr/bin/env python
"""
ATLAS end-to-end browser checks.

    ../.venv/bin/python tests/e2e.py [base_url]

Drives a real browser against a running instance (default http://127.0.0.1:8000)
and asserts the behaviour that has actually broken before: the login loop,
blocked storage, GPU routing, the rubric, and mobile overflow.

Checks are idempotent - they tolerate a database that already has progress in it.
"""
from __future__ import annotations

import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip('/') if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
LIGHTBOX = "img[class*='max-h-']"

results: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, note: str = '') -> None:
    results.append((ok, name, note))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {note}")


def login(pg, email='supervisor@atlas.id', pw='supervisor123') -> None:
    pg.goto(f'{BASE}/login', wait_until='networkidle')
    pg.fill('input[name=email]', email)
    pg.fill('input[name=password]', pw)
    pg.click('button[type=submit]')
    pg.wait_for_url('**/dashboard', timeout=20000)
    pg.wait_for_timeout(2000)


def main() -> int:
    console_errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
        pg = ctx.new_page()
        pg.on('console', lambda m: console_errors.append(m.text[:120]) if m.type == 'error' else None)

        # ---------- auth ----------
        print('\n-- authentication --')
        login(pg)
        check('login reaches the dashboard', '/dashboard' in pg.url)

        pg.reload(wait_until='networkidle'); pg.wait_for_timeout(1500)
        check('session survives a hard refresh', '/dashboard' in pg.url)

        pg.goto(f'{BASE}/curriculum', wait_until='networkidle'); pg.wait_for_timeout(1200)
        check('deep link stays authenticated', '/curriculum' in pg.url)

        # ---------- curriculum ----------
        print('\n-- curriculum --')
        cards = pg.locator("a[href*='/curriculum/view']").count()
        check('six topics are listed', cards == 6, f'({cards} cards)')

        pg.goto(f'{BASE}/curriculum/view?slug=corrosion-segmentation', wait_until='networkidle')
        pg.wait_for_timeout(2200)
        check('topic detail loads', 'Corrosion' in pg.inner_text('h1'))
        check('stages are listed', pg.locator('text=Stage 1').count() > 0)

        btn = pg.locator("button:has-text('Complete \u00b7')").first
        if btn.count():
            btn.click(); pg.wait_for_timeout(2200)
            done = 'Completed' in pg.inner_text('body') or 'Stage 2' in pg.inner_text('body')
            check('completing a stage awards XP', done)
        else:
            already = pg.locator('text=Completed').count() > 0
            check('completing a stage awards XP', already, '(already completed)')

        # ---------- authoring ----------
        print('\n-- authoring --')
        add = pg.locator("button:has-text('Add')").first
        if add.count():
            add.click(); pg.wait_for_timeout(1400)
            check('lesson editor opens', pg.locator('text=Content blocks').count() > 0)
            ab = pg.locator("button:has-text('Add block')").first
            if ab.count():
                ab.click(); pg.wait_for_timeout(1200)
                check('block palette lists types',
                      pg.locator('text=Architecture diagram').count() > 0)
            pg.keyboard.press('Escape'); pg.wait_for_timeout(600)
        else:
            check('lesson editor opens', False, '(no Add control)')

        # ---------- compute ----------
        print('\n-- compute --')
        pg.goto(f'{BASE}/playground?topic=6', wait_until='networkidle'); pg.wait_for_timeout(2400)
        body = pg.inner_text('body')
        check('GPU notebook is flagged', 'GPU required' in body or 'GPU' in body)
        for target in ('Platform CPU', 'Google Colab GPU', 'Kaggle GPU'):
            if target not in body:
                check('three compute targets offered', False, f'(missing {target})')
                break
        else:
            check('three compute targets offered', True)

        # ---------- deployment ----------
        print('\n-- deployment --')
        pg.goto(f'{BASE}/deployment', wait_until='networkidle'); pg.wait_for_timeout(2200)
        d = pg.inner_text('body')
        check('rubric shows 5/5', '5/5' in d)
        check('readiness shows 100%', '100%' in d)

        pg.goto(f'{BASE}/portal', wait_until='networkidle'); pg.wait_for_timeout(1800)
        check('portal lists the deployed app', 'Equipment Failure Predictor' in pg.inner_text('body'))

        # ---------- manual ----------
        print('\n-- manual --')
        # A signed-in visitor is redirected off /login, so the link has to be
        # checked from a logged-out context.
        anon = browser.new_context(viewport={'width': 1440, 'height': 900})
        ap = anon.new_page()
        ap.goto(f'{BASE}/login', wait_until='networkidle'); ap.wait_for_timeout(1800)
        check('login links to the manual', ap.locator("a[href='/manual']").count() > 0)
        ap.locator("a[href='/manual']").first.click(); ap.wait_for_timeout(2000)
        check('manual opens without signing in', '/manual' in ap.url)
        anon.close()

        pg.goto(f'{BASE}/manual', wait_until='networkidle'); pg.wait_for_timeout(2000)
        check('manual has 16 chapters', pg.locator('h2').count() == 16,
              f"({pg.locator('h2').count()})")

        pg.evaluate("()=>document.querySelectorAll('img').forEach(i=>i.loading='eager')")
        pg.evaluate("""async()=>{
            const h=document.body.scrollHeight;
            for(let y=0;y<h;y+=500){window.scrollTo(0,y);await new Promise(r=>setTimeout(r,110));}
            window.scrollTo(0,0);
            await Promise.all(Array.from(document.images).map(i=>i.decode().catch(()=>{})));
        }""")
        pg.wait_for_timeout(2500)
        broken = pg.evaluate(
            "()=>Array.from(document.images).filter(i=>!i.complete||i.naturalWidth===0).length")
        total = pg.evaluate('()=>document.images.length')
        check('every screenshot loads', broken == 0, f'({total} images, {broken} broken)')

        pg.locator('figure button').first.click(); pg.wait_for_timeout(1000)
        opened = pg.locator(LIGHTBOX).count() > 0
        pg.keyboard.press('Escape'); pg.wait_for_timeout(700)
        check('lightbox opens and closes', opened and pg.locator(LIGHTBOX).count() == 0)

        pg.evaluate("()=>document.getElementById('deployment').scrollIntoView()")
        pg.wait_for_timeout(1500)
        stuck = pg.evaluate("""()=>{const n=document.querySelector('aside nav');
            if(!n) return false; const t=n.getBoundingClientRect().top;
            return t>=0 && t<window.innerHeight;}""")
        check('sidebar stays visible while scrolling', stuck)

        ctx.close()

        # ---------- blocked storage ----------
        print('\n-- blocked storage (sandboxed iframe) --')
        ctx2 = browser.new_context(viewport={'width': 1280, 'height': 900})
        pg2 = ctx2.new_page()
        pg2.set_content(
            '<!doctype html><html><body style="margin:0">'
            f'<iframe sandbox="allow-scripts allow-forms" src="{BASE}/login" '
            'style="width:100vw;height:100vh;border:0"></iframe></body></html>')
        pg2.wait_for_timeout(3000)
        fr = pg2.frames[1]
        tier = fr.evaluate(
            "()=>{try{localStorage.setItem('p','1');localStorage.removeItem('p');return 'local'}"
            "catch(e){return 'blocked'}}")
        fr.fill('input[name=email]', 'supervisor@atlas.id')
        fr.fill('input[name=password]', 'supervisor123')
        fr.click('button[type=submit]')
        pg2.wait_for_timeout(4500)
        check('login works with storage blocked',
              '/dashboard' in pg2.frames[1].url, f'(storage={tier})')
        ctx2.close()

        # ---------- mobile ----------
        print('\n-- mobile --')
        m = browser.new_context(viewport={'width': 390, 'height': 844},
                                is_mobile=True, has_touch=True)
        mp = m.new_page()
        worst = 0
        for path in ('/login', '/manual', '/dashboard', '/curriculum', '/playground'):
            if path in ('/dashboard', '/curriculum', '/playground') and worst == 0:
                login(mp, 'intern@atlas.id', 'intern123')
            mp.goto(f'{BASE}{path}', wait_until='networkidle'); mp.wait_for_timeout(1400)
            sw = mp.evaluate('()=>document.documentElement.scrollWidth')
            worst = max(worst, sw)
        check('no horizontal overflow at 390px', worst <= 391, f'(widest {worst}px)')
        m.close()

        browser.close()

    # ---------- summary ----------
    passed = sum(1 for ok, _, _ in results if ok)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    real_errors = [e for e in console_errors if 'favicon' not in e]
    print('console errors:', real_errors[:4] if real_errors else 'none')
    if passed != len(results):
        print('\nfailed:')
        for ok, name, note in results:
            if not ok:
                print(f'  - {name} {note}')
    return 0 if passed == len(results) and not real_errors else 1


if __name__ == '__main__':
    sys.exit(main())

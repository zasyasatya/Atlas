#!/usr/bin/env python
"""Branding has one owner: the server's configuration.

A rename that lives in four files is a rename that ships three of them. These
checks hold the line on that: the defaults in `app.core.config` must be what the
launcher and the frontend fall back to, the brand must be published through
`/api/config`, the frontend must not keep its own copy of the wordmark in a
component, and no string from the previous positioning may survive outside the two
documents that record the change.

    python tests/branding.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import settings  # noqa: E402

_results: list[tuple[bool, str]] = []


def check(name: str, ok: bool) -> None:
    _results.append((ok, name))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")


# The old positioning. Allowed to appear only where the rename is *recorded*.
LEGACY = ("AI Internship Operating System", "INTERNSHIP OS", "AI INTERNSHIP OS")
EXEMPT = {"tests/branding.py", "docs/PRD.md", "README.md"}


def source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_config_is_the_source() -> None:
    brand = settings.brand
    check("the brand exposes name, tagline, short label, subtitle and docs link",
          set(brand) == {"name", "tagline", "label", "subtitle", "docs_url"})
    check("the product is positioned as applied AI and data work, not as an internship OS",
          "Applied AI" in brand["tagline"] and "Research" in brand["tagline"])
    check("every brand field is a string", all(isinstance(v, str) for v in brand.values()))
    check("the fields that must never be blank are not (docs_url may be)",
          all(brand[k].strip() for k in ("name", "tagline", "label", "subtitle")))
    check("the short label is short enough for a sidebar rail",
          len(brand["label"]) <= 26)
    check("the tagline never repeats the product name (both render side by side)",
          brand["name"].lower() not in brand["tagline"].lower())


def test_api_publishes_it() -> None:
    from app.main import public_config

    cfg = public_config()
    check("/api/config carries the brand object",
          isinstance(cfg.get("brand"), dict) and set(cfg["brand"]) ==
          {"name", "tagline", "label", "subtitle", "docs_url"})
    check("/api/config keeps app_name and tagline for existing consumers",
          cfg["app_name"] == settings.app_name and cfg["tagline"] == settings.app_tagline)
    check("/api/config publishes the app path prefix so the UI never hardcodes it",
          cfg["app_prefix"] == settings.deploy_prefix)

    from app.main import app

    check("the OpenAPI title and description are the brand, not literals",
          app.title == settings.app_name and app.description == settings.app_tagline)


def test_frontend_fallbacks_agree() -> None:
    """The UI's defaults must be the server's defaults.

    They are a first-paint fallback, not a second source of truth: a mismatch is
    visible to users as the text changing under them, and is otherwise invisible
    to review.
    """
    ts = source("frontend/lib/brand-defaults.ts")
    block = re.search(r"BRAND_DEFAULTS:\s*Brand\s*=\s*\{(.*?)\n\};", ts, re.S)
    fields = dict(re.findall(r"(\w+):\s*'([^']*)'", block.group(1))) if block else {}
    check("the frontend declares a fallback for every brand field",
          set(fields) == {"name", "tagline", "label", "subtitle", "docs_url"})
    check("each frontend fallback equals the server default",
          all(fields.get(k) == settings.brand[k] for k in
              ("name", "tagline", "label", "subtitle")))
    hook = source("frontend/lib/brand.ts")
    check("the UI reads the brand from the API rather than a literal",
          "/api/config" in hook and "useBrand" in hook)
    check("the hook shares the fallbacks instead of redefining them",
          "from './brand-defaults'" in hook and "BRAND_DEFAULTS" in hook)
    check("the UI's brand type carries docs_url so an external manual can replace it",
          "docs_url" in ts)
    # The defaults are importable by BOTH sides of the app. `next build` fails with
    # "You cannot dot into a client module from a server component" the moment
    # someone puts them behind 'use client' again, so the rule is asserted, not
    # remembered.
    check("the shared fallbacks are not a client module",
          not ts.lstrip().startswith("'use client'"))
    layout = source("frontend/app/layout.tsx")
    check("the server renderer imports the shared module, not the client hook",
          "from '@/lib/brand-defaults'" in layout
          and "from '@/lib/brand'" not in layout)


def test_components_do_not_hardcode_the_wordmark() -> None:
    for name in ("frontend/app/components/Shell.tsx", "frontend/app/login/page.tsx"):
        text = source(name)
        check(f"{Path(name).parent.name}/{Path(name).name} renders the brand, not a literal",
              "brand.name" in text and ">ATLAS<" not in text)
    shell = source("frontend/app/components/Shell.tsx")
    check("the sidebar label is configurable too (it used to say INTERNSHIP OS)",
          "brand.label" in shell and "INTERNSHIP OS" not in shell)
    manual = source("frontend/app/manual/page.tsx")
    check("the manual footer reads the brand", "brand.tagline" in manual)


def test_launcher_agrees() -> None:
    """`run.py` prints the identity before the app is importable, so it keeps its
    own copy of the defaults - which means it needs a check that they match."""
    text = source("run.py")
    block = re.search(r"BRAND_DEFAULTS\s*=\s*\{(.*?)\}", text, re.S)
    fields = dict(re.findall(r'"(ATLAS_APP_\w+)":\s*"([^"]*)"', block.group(1))) if block else {}
    check("the launcher's fallback name matches the server default",
          fields.get("ATLAS_APP_NAME") == settings.app_name)
    check("the launcher's fallback tagline matches the server default",
          fields.get("ATLAS_APP_TAGLINE") == settings.app_tagline)
    check("the banner is built from configuration, not a literal string",
          'say("  " + brand(), B)' in text)
    check("the launcher reads .env so a local rebrand shows up in the banner",
          'ROOT / ".env"' in text)


def test_documented_everywhere() -> None:
    env = source(".env.example")
    for var in ("ATLAS_APP_NAME", "ATLAS_APP_TAGLINE", "ATLAS_APP_TAGLINE_SHORT",
                "ATLAS_APP_SUBTITLE", "ATLAS_DOCS_URL"):
        field = var[len("ATLAS_"):].lower()
        check(f"{var} is documented and is a real setting",
              var in env and hasattr(settings, field))
    compose = source("docker-compose.yml")
    check("compose forwards the brand, so a container can be rebranded by env alone",
          "ATLAS_APP_NAME:" in compose and "ATLAS_APP_TAGLINE:" in compose)
    readme = source("README.md")
    check("the README tells an operator how to rebrand",
          "## Branding & white-labelling" in readme
          and "ATLAS_APP_TAGLINE" in readme)


def test_no_legacy_branding_survives() -> None:
    offenders: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel in EXEMPT:
            continue
        if any(part in rel for part in ("/.git/", "node_modules", "/.next/", "/storage/",
                                        "/static/", "__pycache__")):
            continue
        if path.suffix not in {".py", ".tsx", ".ts", ".md", ".sh", ".bat", ".yml",
                               ".yaml", ".example", ".json", ".html"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(legacy in text for legacy in LEGACY):
            offenders.append(rel)
    check("no file outside the rename notes still carries the old positioning",
          not offenders)
    if offenders:
        print("    offenders:", ", ".join(offenders[:8]))


def main() -> int:
    print("config is the single source:")
    test_config_is_the_source()
    print("published to clients:")
    test_api_publishes_it()
    print("frontend fallbacks:")
    test_frontend_fallbacks_agree()
    print("components:")
    test_components_do_not_hardcode_the_wordmark()
    print("launcher:")
    test_launcher_agrees()
    print("documented:")
    test_documented_everywhere()
    print("no leftovers:")
    test_no_legacy_branding_survives()

    failed = [n for ok, n in _results if not ok]
    print(f"\n{len(_results) - len(failed)}/{len(_results)} checks passed")
    if failed:
        print("FAILED:")
        for n in failed:
            print("  -", n)
        return 1
    print("ALL BRANDING CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

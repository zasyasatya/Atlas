#!/usr/bin/env python3
"""Validate seeded lesson blocks against what BlockRenderer.tsx actually reads.

A block whose payload uses the wrong key names renders as a silent blank in the
UI - no error, no crash, just missing teaching material. This checks every
seeded block carries the fields its renderer consumes.

The expected contract is read from the component itself where possible, so this
test notices if the two drift apart.

    ./.venv/bin/python tests/lesson_contract.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m")
_passed = _failed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global _passed, _failed
    if ok:
        _passed += 1
        print(f"  {GREEN}[PASS]{RESET} {name} {DIM}{detail}{RESET}")
    else:
        _failed += 1
        print(f"  {RED}[FAIL]{RESET} {name} {DIM}{detail}{RESET}")


# What each block type must provide for the renderer to show anything.
REQUIRED = {
    "text": ["body"],
    "callout": ["title", "body"],
    "architecture": ["nodes"],
    "quiz": ["question", "options", "answer"],
    "flashcard": ["cards"],
    "code": ["code"],
    "image": ["url"],
    "video": ["url"],
}
VALID_TONES = {"quest", "warning", "info", "success"}


def main() -> int:
    print(f"{BOLD}Lesson block contract{RESET}")
    print("=" * 74)

    # ---- the renderer's switch must still cover the enum -------------------
    renderer = (ROOT / "frontend/app/components/BlockRenderer.tsx").read_text()
    handled = set(re.findall(r"case '([a-z]+)':", renderer))

    from app.domain.enums import LessonBlockType

    enum_values = {m.value for m in LessonBlockType}
    check("renderer handles every block type in the enum",
          enum_values <= handled,
          f"unhandled: {sorted(enum_values - handled) or 'none'}")

    # Tones referenced by CalloutBlock
    tones = set(re.findall(r"^\s{4}(quest|warning|info|success):", renderer, re.M))
    check("callout tones match the renderer", tones == VALID_TONES,
          f"renderer knows {sorted(tones)}")

    # ---- every seeded lesson block --------------------------------------
    from app.services.corrosion_lessons import corrosion_lessons

    lessons = corrosion_lessons()
    check("six lessons are defined", len(lessons) == 6, f"{len(lessons)} lessons")

    slugs = [l["slug"] for l in lessons]
    check("lesson slugs are unique", len(set(slugs)) == len(slugs), ", ".join(slugs))
    check("order_index is 0..n with no gaps",
          [l["order_index"] for l in lessons] == list(range(len(lessons))))

    problems: list[str] = []
    counts: dict[str, int] = {}
    total_blocks = 0

    for lesson in lessons:
        for i, block in enumerate(lesson["blocks"]):
            total_blocks += 1
            kind = block.block_type.value
            counts[kind] = counts.get(kind, 0) + 1
            where = f"{lesson['slug']}[{i}] {kind}"

            try:
                payload = json.loads(block.payload_json)
            except json.JSONDecodeError as exc:
                problems.append(f"{where}: payload is not valid JSON - {exc}")
                continue

            for field in REQUIRED.get(kind, []):
                if field not in payload:
                    problems.append(f"{where}: missing '{field}' "
                                    f"(has {sorted(payload)})")
                elif payload[field] in ("", [], None):
                    problems.append(f"{where}: '{field}' is empty")

            if kind == "callout":
                tone = payload.get("tone")
                if tone not in VALID_TONES:
                    problems.append(f"{where}: tone {tone!r} is not one of "
                                    f"{sorted(VALID_TONES)}")

            if kind == "quiz":
                opts, ans = payload.get("options", []), payload.get("answer")
                if len(opts) < 2:
                    problems.append(f"{where}: needs at least 2 options")
                if not isinstance(ans, int) or not (0 <= ans < len(opts)):
                    problems.append(f"{where}: answer {ans} is out of range")
                if not payload.get("explanation"):
                    problems.append(f"{where}: no explanation")

            if kind == "flashcard":
                for j, card in enumerate(payload.get("cards", [])):
                    if not card.get("front") or not card.get("back"):
                        problems.append(f"{where}: card {j} missing front/back")

            if kind == "architecture":
                nodes = payload.get("nodes", [])
                if len(nodes) < 2:
                    problems.append(f"{where}: needs at least 2 nodes")
                for n in nodes:
                    if not n.get("label"):
                        problems.append(f"{where}: a node has no label")
                    # note is optional but the whole point of a tappable diagram
                    if not n.get("note"):
                        problems.append(f"{where}: node {n.get('id')} has no note, "
                                        f"so tapping it shows filler text")

            # The renderer treats text bodies as markdown-ish, NOT html.
            if kind in ("text", "callout"):
                body = str(payload.get("body", ""))
                if re.search(r"</?(p|ul|li|h[1-6]|table|tr|td|strong|em)\b", body):
                    problems.append(f"{where}: body contains raw HTML tags, which "
                                    f"render as literal text")

    check("every block satisfies its renderer contract", not problems,
          f"{total_blocks} blocks checked")
    for p in problems[:25]:
        print(f"      {YELLOW}-{RESET} {p}")
    if len(problems) > 25:
        print(f"      {DIM}... and {len(problems) - 25} more{RESET}")

    # ---- teaching-quality guards ------------------------------------------
    check("every lesson ends with a checkpoint or recap",
          all(any(b.block_type.value in ("quiz", "flashcard") for b in l["blocks"])
              for l in lessons),
          "each lesson has a quiz or flashcards")

    check("code is taught, not just described",
          counts.get("code", 0) >= 8, f"{counts.get('code', 0)} code blocks")

    check("the architecture diagram is present",
          counts.get("architecture", 0) >= 1)

    check("difficulty ramps up", 
          [l["xp_reward"] for l in lessons] == sorted(l["xp_reward"] for l in lessons),
          " -> ".join(str(l["xp_reward"]) for l in lessons) + " XP")

    print(f"\n  {DIM}block mix: " +
          ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + RESET)

    # ---- the stale taxonomy must be gone ----------------------------------
    seed_src = (ROOT / "backend/app/services/seed.py").read_text()
    check("seed no longer advertises the old 5-class taxonomy",
          "uniform, pitting, crevice, galvanic and scaling" not in seed_src)
    check("seed mentions the real class count",
          "15 corrosion classes" in seed_src)
    check("corrosion topic uses its own lessons",
          '"lessons": corrosion_lessons' in seed_src)

    total = _passed + _failed
    print()
    if _failed:
        print(f"{RED}{BOLD}=== {_passed}/{total} passed, {_failed} failed ==={RESET}")
    else:
        print(f"{GREEN}{BOLD}=== {_passed}/{total} passed ==={RESET}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Generate a small synthetic dataset shaped like the CorroVision export.

This exists so the pipeline can be run and tested without the real 3129-image
set. It mimics the structure, not the physics: same directory layout, same 15
class names, same mask encoding, same background dominance. A model trained on
it will learn the synthetic texture cues, which is enough to prove the code path
works end to end.

    python make_sample_data.py --out data/sample --count 60

Layout produced:

    <out>/classes.txt
    <out>/train/images/*.jpg   <out>/train/masks/*.png
    <out>/val/images/*.jpg     <out>/val/masks/*.png
    <out>/test/images/*.jpg    <out>/test/masks/*.png
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

CLASSES = [
    "crevice_corrosion_mild", "crevice_corrosion_moderate", "crevice_corrosion_severe",
    "galvanic_corrosion_mild", "galvanic_corrosion_moderate", "galvanic_corrosion_severe",
    "general_corrosion_mild", "general_corrosion_moderate", "general_corrosion_severe",
    "pitting_corrosion_mild", "pitting_corrosion_moderate", "pitting_corrosion_severe",
    "preferential_weld_attack_corrosion_mild",
    "preferential_weld_attack_corrosion_moderate",
    "preferential_weld_attack_corrosion_severe",
]

# Each family gets a rust hue; severity darkens and saturates it. Giving the
# families visually distinct signatures lets a small model actually learn
# something, so the smoke test produces a non-trivial mIoU.
FAMILY_HUE = {
    "crevice": (120, 70, 55),
    "galvanic": (150, 110, 60),
    "general": (140, 85, 50),
    "pitting": (95, 60, 48),
    "preferential": (125, 95, 70),
}
SEVERITY = {"mild": 0.55, "moderate": 0.8, "severe": 1.0}


def _family(name: str) -> str:
    return name.split("_")[0]


def _severity(name: str) -> str:
    return name.rsplit("_", 1)[-1]


def _metal_background(rng: np.random.Generator, size: int) -> np.ndarray:
    """Grey steel with mild banding and noise."""
    base = rng.uniform(140, 190)
    img = np.full((size, size, 3), base, dtype=np.float32)
    rows = np.linspace(0, np.pi * rng.uniform(1, 3), size)
    img += (np.sin(rows)[:, None, None] * rng.uniform(4, 10))
    img += rng.normal(0, 5, (size, size, 3))
    return img


def _blob(rng, size, cx, cy, radius, roughness=0.45):
    """An irregular filled region - a corrosion patch."""
    yy, xx = np.mgrid[0:size, 0:size]
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    angle = np.arctan2(yy - cy, xx - cx)
    wobble = sum(
        rng.uniform(0.5, 1.0) * np.sin(k * angle + rng.uniform(0, 6.28))
        for k in rng.choice([3, 4, 5, 6, 7], size=3, replace=False)
    )
    return d < radius * (1 + roughness * wobble / 3)


def make_one(rng: np.random.Generator, size: int, num_bg: int = 1):
    """One (image, mask) pair. Mask index 0 is background, 1..15 are classes."""
    img = _metal_background(rng, size)
    mask = np.zeros((size, size), dtype=np.uint8)

    for _ in range(int(rng.integers(1, 4))):
        idx = int(rng.integers(0, len(CLASSES)))
        name = CLASSES[idx]
        hue = np.array(FAMILY_HUE[_family(name)], dtype=np.float32)
        strength = SEVERITY[_severity(name)]

        cx, cy = rng.integers(size // 5, size - size // 5, size=2)
        radius = rng.uniform(size * 0.10, size * 0.22) * (0.7 + 0.5 * strength)
        region = _blob(rng, size, cx, cy, radius)

        colour = hue * (1.25 - 0.45 * strength)
        img[region] = img[region] * (1 - 0.75 * strength) + colour * (0.75 * strength)

        fam = _family(name)
        if fam == "pitting":
            # Scattered dark dots inside the patch.
            pit = (rng.random((size, size)) < 0.10 * strength) & region
            img[pit] *= 0.45
        elif fam == "general":
            img[region] += rng.normal(0, 16 * strength, img[region].shape)
        elif fam == "crevice":
            # Concentrated along one edge, as crevice attack tends to be.
            yy, xx = np.mgrid[0:size, 0:size]
            edge = region & (xx > cx)
            img[edge] *= 0.72
        elif fam == "preferential":
            # A weld line running through the patch.
            yy, xx = np.mgrid[0:size, 0:size]
            line = region & (np.abs((yy - cy) - 0.3 * (xx - cx)) < size * 0.02)
            img[line] *= 0.55

        mask[region] = idx + num_bg  # shift past background

    img = np.clip(img, 0, 255).astype(np.uint8)
    return img, mask


def generate(out: Path, count: int, size: int, seed: int) -> dict[str, int]:
    rng = np.random.default_rng(seed)
    counts = {"train": int(count * 0.7), "val": int(count * 0.15)}
    counts["test"] = max(count - counts["train"] - counts["val"], 1)

    out.mkdir(parents=True, exist_ok=True)
    (out / "classes.txt").write_text("\n".join(CLASSES) + "\n")

    n = 0
    for split, k in counts.items():
        (out / split / "images").mkdir(parents=True, exist_ok=True)
        (out / split / "masks").mkdir(parents=True, exist_ok=True)
        for i in range(k):
            img, mask = make_one(rng, size)
            stem = f"20260113_data_{split}_{i:04d}"
            Image.fromarray(img).save(out / split / "images" / f"{stem}.jpg", quality=88)
            Image.fromarray(mask).save(out / split / "masks" / f"{stem}.png")
            n += 1
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/sample", help="output directory")
    ap.add_argument("--count", type=int, default=60, help="total images")
    ap.add_argument("--size", type=int, default=192, help="image side in pixels")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    out = Path(args.out)
    counts = generate(out, args.count, args.size, args.seed)
    print(f"wrote {sum(counts.values())} pairs to {out}")
    for split, k in counts.items():
        print(f"  {split:<6} {k:>4}")
    print(f"  {len(CLASSES)} classes + background, masks are single-channel PNG")


if __name__ == "__main__":
    main()

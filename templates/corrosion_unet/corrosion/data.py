"""Dataset loading for the CorroVision semantic-segmentation export.

The exporter writes mask PNGs where every pixel holds a class index. This module
figures out the rest by looking at the files, because the details vary between
exports:

  * how the splits are laid out on disk
  * whether index 0 means "background" or is a real corrosion class
  * how many classes actually appear

Nothing here imports torch, so the class discovery can be unit-tested and run
inside a Streamlit app without pulling in the training stack.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

# Filenames the exporter may use for the class list, best guess first.
_CLASS_FILES = ("classes.txt", "classes.json", "labels.txt", "data.yaml", "notes.json")

# Directory names that hold images and masks.
_IMAGE_DIRS = ("images", "image", "img", "JPEGImages")
_MASK_DIRS = ("masks", "mask", "labels", "annotations", "SegmentationClass")

_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}

# The 15 classes this dataset ships with: 5 corrosion types x 3 severities.
DEFAULT_CLASSES = [
    "crevice_corrosion_mild",
    "crevice_corrosion_moderate",
    "crevice_corrosion_severe",
    "galvanic_corrosion_mild",
    "galvanic_corrosion_moderate",
    "galvanic_corrosion_severe",
    "general_corrosion_mild",
    "general_corrosion_moderate",
    "general_corrosion_severe",
    "pitting_corrosion_mild",
    "pitting_corrosion_moderate",
    "pitting_corrosion_severe",
    "preferential_weld_attack_corrosion_mild",
    "preferential_weld_attack_corrosion_moderate",
    "preferential_weld_attack_corrosion_severe",
]


# --------------------------------------------------------------------------
# class list
# --------------------------------------------------------------------------
def _parse_class_file(path: Path) -> list[str]:
    """Read a class list from whichever format the exporter produced."""
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return []

    if path.suffix == ".json":
        data = json.loads(text)
        if isinstance(data, list):
            if data and isinstance(data[0], dict):  # [{"name": ...}, ...]
                return [str(d.get("name", d.get("label", ""))) for d in data]
            return [str(d) for d in data]
        if isinstance(data, dict):
            for key in ("classes", "names", "labels", "categories"):
                if key in data:
                    value = data[key]
                    if isinstance(value, dict):  # {"0": "name", ...}
                        return [value[k] for k in sorted(value, key=lambda x: int(x))]
                    if value and isinstance(value[0], dict):
                        return [str(d.get("name", d.get("label", ""))) for d in value]
                    return [str(v) for v in value]
        return []

    if path.name == "data.yaml":
        # names: [a, b]  or  a bulleted/indexed block. Avoids a yaml dependency.
        inline = re.search(r"names:\s*\[(.*?)\]", text, re.S)
        if inline:
            return [n.strip().strip("'\"") for n in inline.group(1).split(",") if n.strip()]
        block = re.search(r"names:\s*\n((?:\s+.*\n?)+)", text)
        if block:
            out = []
            for line in block.group(1).splitlines():
                line = line.strip()
                if not line:
                    continue
                m = re.match(r"(?:-\s*|\d+\s*:\s*)(.+)", line)
                if m:
                    out.append(m.group(1).strip().strip("'\""))
            return out
        return []

    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def find_classes(root: Path) -> tuple[list[str], Path | None]:
    """Look for a class-list file anywhere under root. Returns ([], None) if absent."""
    root = Path(root)
    for name in _CLASS_FILES:
        for path in sorted(root.rglob(name)):
            try:
                names = _parse_class_file(path)
            except Exception:
                continue
            if names:
                return names, path
    return [], None


# --------------------------------------------------------------------------
# file discovery
# --------------------------------------------------------------------------
def _is_image(p: Path) -> bool:
    return p.suffix.lower() in _IMAGE_EXT and not p.name.startswith(".")


def _mask_for(image: Path, mask_dir: Path) -> Path | None:
    """Match an image to its mask. Extensions usually differ (.jpg -> .png)."""
    direct = mask_dir / f"{image.stem}.png"
    if direct.exists():
        return direct
    for ext in (".png", ".PNG", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"):
        cand = mask_dir / f"{image.stem}{ext}"
        if cand.exists():
            return cand
    return None


@dataclass
class Split:
    """One train/val/test split: paired image and mask paths."""
    name: str
    images: list[Path] = field(default_factory=list)
    masks: list[Path] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.images)


def _pair_dir(image_dir: Path, mask_dir: Path, name: str) -> Split:
    split = Split(name)
    for img in sorted(image_dir.iterdir()):
        if not _is_image(img):
            continue
        msk = _mask_for(img, mask_dir)
        if msk is not None:
            split.images.append(img)
            split.masks.append(msk)
    return split


def _find_pairs(root: Path) -> list[tuple[Path, Path, str]]:
    """Find every (image_dir, mask_dir, split_name) under root."""
    found: list[tuple[Path, Path, str]] = []
    for image_dir in sorted(root.rglob("*")):
        if not image_dir.is_dir() or image_dir.name not in _IMAGE_DIRS:
            continue
        parent = image_dir.parent
        for mask_name in _MASK_DIRS:
            mask_dir = parent / mask_name
            if mask_dir.is_dir():
                # <root>/train/images -> "train"; <root>/images -> "all"
                label = parent.name if parent != root else "all"
                found.append((image_dir, mask_dir, label))
                break
    return found


def discover(root: str | Path) -> dict[str, Split]:
    """Map split name -> Split. Handles both split and flat layouts.

    Recognised:
        root/train/images + root/train/masks   (and valid/test)
        root/images/train + root/masks/train
        root/images       + root/masks         -> {"all": ...}
    """
    root = Path(root)
    if not root.exists():
        return {}

    splits: dict[str, Split] = {}
    for image_dir, mask_dir, label in _find_pairs(root):
        # images/train + masks/train: split name lives one level down instead.
        subdirs = [d for d in sorted(image_dir.iterdir()) if d.is_dir()]
        if subdirs and not any(_is_image(f) for f in image_dir.iterdir() if f.is_file()):
            for sub in subdirs:
                msub = mask_dir / sub.name
                if msub.is_dir():
                    s = _pair_dir(sub, msub, _canon(sub.name))
                    if len(s):
                        splits[s.name] = s
            continue

        s = _pair_dir(image_dir, mask_dir, _canon(label))
        if len(s):
            if s.name in splits:  # merge duplicates rather than overwrite
                splits[s.name].images += s.images
                splits[s.name].masks += s.masks
            else:
                splits[s.name] = s
    return splits


def _canon(name: str) -> str:
    """Normalise the many spellings of the same split."""
    n = name.strip().lower()
    if n in {"train", "training", "trn"}:
        return "train"
    if n in {"val", "valid", "validation", "dev", "eval"}:
        return "val"
    if n in {"test", "testing", "holdout"}:
        return "test"
    return n


def split_flat(splits: dict[str, Split], ratios=(0.8, 0.1, 0.1), seed: int = 42) -> dict[str, Split]:
    """Turn a single unsplit set into train/val/test.

    Only used when the export had no split of its own - if the exporter already
    made the splits, its choice is respected so results stay comparable.
    """
    if set(splits) != {"all"}:
        return splits

    everything = splits["all"]
    idx = np.arange(len(everything))
    np.random.default_rng(seed).shuffle(idx)

    n = len(idx)
    n_train = int(n * ratios[0])
    n_val = int(n * ratios[1])
    chunks = {
        "train": idx[:n_train],
        "val": idx[n_train:n_train + n_val],
        "test": idx[n_train + n_val:],
    }
    return {
        name: Split(name,
                    [everything.images[i] for i in ids],
                    [everything.masks[i] for i in ids])
        for name, ids in chunks.items() if len(ids)
    }


# --------------------------------------------------------------------------
# label-space inspection
# --------------------------------------------------------------------------
@dataclass
class LabelSpace:
    """What the mask pixel values actually mean."""
    class_names: list[str]
    has_background: bool
    values: list[int]
    pixel_counts: dict[int, int]
    source: str

    @property
    def num_classes(self) -> int:
        """Channels the network must output, background included if present."""
        return len(self.class_names)

    @property
    def ignore_index(self) -> int | None:
        return None

    def frequencies(self) -> dict[str, float]:
        total = sum(self.pixel_counts.values()) or 1
        return {
            self.class_names[v] if v < len(self.class_names) else f"class_{v}":
                self.pixel_counts.get(v, 0) / total
            for v in self.values
        }


def inspect_labels(
    splits: dict[str, Split],
    class_names: list[str] | None = None,
    sample: int = 60,
) -> LabelSpace:
    """Work out the label space by reading actual mask pixels.

    The question that matters is whether index 0 is background or a real class,
    because it decides how many output channels the network needs. Rather than
    assume, count the distinct values present and compare against the class list.
    """
    masks: list[Path] = []
    for name in ("train", "all", "val", "test"):
        if name in splits:
            masks += splits[name].masks
    if not masks:
        masks = [m for s in splits.values() for m in s.masks]

    if len(masks) > sample:
        step = max(1, len(masks) // sample)
        masks = masks[::step][:sample]

    counts: dict[int, int] = {}
    for path in masks:
        arr = np.array(Image.open(path))
        if arr.ndim == 3:  # RGB mask: collapse to the first channel
            arr = arr[..., 0]
        vals, cnts = np.unique(arr, return_counts=True)
        for v, c in zip(vals.tolist(), cnts.tolist()):
            counts[int(v)] = counts.get(int(v), 0) + int(c)

    values = sorted(counts)
    max_value = max(values) if values else 0
    names = list(class_names) if class_names else []

    # Decide whether a background class exists.
    if names and len(names) == max_value + 1:
        # Class list already covers every value, background included if listed.
        has_bg = names[0].strip().lower() in {"background", "bg", "none", "unlabeled", "unlabelled"}
        source = "class file covers all mask values"
    elif names and len(names) == max_value:
        # One more value than names -> 0 is an unlisted background.
        names = ["background"] + names
        has_bg = True
        source = "value 0 is unlisted background"
    elif names:
        has_bg = names[0].strip().lower() in {"background", "bg", "none", "unlabeled", "unlabelled"}
        source = "class file (count differs from mask values)"
        while len(names) <= max_value:
            names.append(f"class_{len(names)}")
    else:
        # No class file: fall back on the known 15, plus background if needed.
        if max_value == len(DEFAULT_CLASSES):
            names = ["background"] + DEFAULT_CLASSES
            has_bg = True
            source = "inferred: 15 classes + background"
        elif max_value == len(DEFAULT_CLASSES) - 1:
            names = list(DEFAULT_CLASSES)
            has_bg = False
            source = "inferred: 15 classes, no background"
        else:
            names = [f"class_{i}" for i in range(max_value + 1)]
            has_bg = 0 in values
            source = "inferred from mask values only"

    return LabelSpace(names[:max_value + 1] if names else [], has_bg, values, counts, source)


def summarise(splits: dict[str, Split], space: LabelSpace) -> str:
    """Human-readable report, printed by the notebook after loading."""
    lines = ["Dataset", "-" * 46]
    total = 0
    for name in ("train", "val", "test", "all"):
        if name in splits:
            n = len(splits[name])
            total += n
            lines.append(f"  {name:<6} {n:>6} image/mask pairs")
    lines.append(f"  {'total':<6} {total:>6}")
    lines.append("")
    lines.append(f"Classes: {space.num_classes} "
                 f"({'with' if space.has_background else 'no'} background) - {space.source}")
    freq = space.frequencies()
    for name, share in sorted(freq.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {share * 100:6.2f}%  {name}")
    return "\n".join(lines)

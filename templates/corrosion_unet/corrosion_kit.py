"""corrosion_kit - one file that carries the whole corrosion pipeline.

The five playground notebooks (EDA, training, evaluation, inference, deployment)
and the deployed Streamlit app all need the same pieces: find the data, decide
what the mask values mean, build the U-Net, score it, draw an overlay. Copying
that into every notebook would guarantee they drift apart, so it lives here once
and every notebook writes this exact file next to itself before importing it.

Deliberately dependency-light: numpy, pillow and torch. No torchvision, no
albumentations, nothing that a bare Colab or a slim Docker image would have to
install. Everything an intern is asked to understand is written out rather than
imported.

    from corrosion_kit import discover, inspect_labels, build_model, Predictor

Copy this file next to a notebook and it works standalone - it imports nothing
from ATLAS.
"""
from __future__ import annotations

import json
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

__version__ = "1.1.0"

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------
# The CorroVision export: 5 corrosion families x 3 severities.
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

# One hue per family, darkening with severity, so an overlay reads at a glance.
PALETTE = [
    (0, 0, 0),                                                # background
    (255, 179, 179), (255, 102, 102), (204, 0, 0),            # crevice
    (255, 224, 178), (255, 183, 77), (230, 126, 34),          # galvanic
    (200, 230, 201), (102, 187, 106), (27, 120, 55),          # general
    (187, 222, 251), (66, 165, 245), (21, 76, 168),           # pitting
    (225, 190, 231), (186, 104, 200), (123, 31, 162),         # preferential weld
    (200, 200, 200),                                          # anything extra
]

# ImageNet statistics. Kept even without pretrained weights so training and the
# deployed app normalise identically - a mismatch here silently wrecks accuracy.
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
IMAGE_DIRS = ("images", "image", "img", "JPEGImages")
MASK_DIRS = ("masks", "mask", "labels", "annotations", "SegmentationClass")
CLASS_FILES = ("classes.txt", "classes.json", "labels.txt", "notes.json")
BACKGROUND_NAMES = {"background", "bg", "none", "unlabeled", "unlabelled"}


def is_background(name: str) -> bool:
    return str(name).strip().lower() in BACKGROUND_NAMES


# --------------------------------------------------------------------------
# finding the data
# --------------------------------------------------------------------------
@dataclass
class Split:
    """One train/val/test split: paired image and mask paths."""

    name: str
    images: list = field(default_factory=list)
    masks: list = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.images)


def _canon(name: str) -> str:
    n = str(name).strip().lower()
    if n in {"train", "training", "trn"}:
        return "train"
    if n in {"val", "valid", "validation", "dev", "eval"}:
        return "val"
    if n in {"test", "testing", "holdout"}:
        return "test"
    return n


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXT and not path.name.startswith(".")


def _mask_for(image: Path, mask_dir: Path):
    """Match an image to its mask. Extensions usually differ (.jpg -> .png)."""
    direct = mask_dir / (image.stem + ".png")
    if direct.exists():
        return direct
    for ext in (".png", ".PNG", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"):
        candidate = mask_dir / (image.stem + ext)
        if candidate.exists():
            return candidate
    return None


def _pair_dir(image_dir: Path, mask_dir: Path, name: str) -> Split:
    split = Split(_canon(name))
    for img in sorted(image_dir.iterdir()):
        if not img.is_file() or not _is_image(img):
            continue
        msk = _mask_for(img, mask_dir)
        if msk is not None:
            split.images.append(img)
            split.masks.append(msk)
    return split


def discover(root) -> dict:
    """Map split name -> Split, whatever layout the exporter used.

    Handles root/train/images + root/train/masks, root/images/train +
    root/masks/train, and a flat root/images + root/masks (returned as "all").
    """
    root = Path(root)
    if not root.exists():
        return {}

    splits: dict = {}
    for image_dir in sorted(root.rglob("*")):
        if not image_dir.is_dir() or image_dir.name not in IMAGE_DIRS:
            continue
        parent = image_dir.parent
        mask_dir = None
        for name in MASK_DIRS:
            if (parent / name).is_dir():
                mask_dir = parent / name
                break
        if mask_dir is None:
            continue

        # images/train + masks/train: the split name lives one level down.
        subdirs = [d for d in sorted(image_dir.iterdir()) if d.is_dir()]
        has_files = any(_is_image(f) for f in image_dir.iterdir() if f.is_file())
        if subdirs and not has_files:
            for sub in subdirs:
                if (mask_dir / sub.name).is_dir():
                    split = _pair_dir(sub, mask_dir / sub.name, sub.name)
                    if len(split):
                        splits[split.name] = split
            continue

        label = parent.name if parent != root else "all"
        split = _pair_dir(image_dir, mask_dir, label)
        if len(split):
            if split.name in splits:          # merge rather than overwrite
                splits[split.name].images += split.images
                splits[split.name].masks += split.masks
            else:
                splits[split.name] = split
    return splits


def split_flat(splits: dict, ratios=(0.8, 0.1, 0.1), seed: int = 42) -> dict:
    """Turn a single unsplit set into train/val/test.

    Only used when the export had no split of its own; an exporter's own split
    is respected so results stay comparable between interns.
    """
    if set(splits) != {"all"}:
        return splits
    everything = splits["all"]
    idx = np.arange(len(everything))
    np.random.default_rng(seed).shuffle(idx)
    n_train = int(len(idx) * ratios[0])
    n_val = int(len(idx) * ratios[1])
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


def find_classes(root):
    """Read the exporter's class list if it wrote one. Returns (names, path)."""
    root = Path(root)
    for filename in CLASS_FILES:
        for path in sorted(root.rglob(filename)):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore").strip()
            except OSError:
                continue
            if not text:
                continue
            if path.suffix == ".json":
                try:
                    data = json.loads(text)
                except ValueError:
                    continue
                if isinstance(data, list):
                    names = [str(d.get("name", d.get("label", ""))) if isinstance(d, dict) else str(d)
                             for d in data]
                    if any(names):
                        return names, path
                elif isinstance(data, dict):
                    for key in ("classes", "names", "labels", "categories"):
                        value = data.get(key)
                        if isinstance(value, dict):
                            return [value[k] for k in sorted(value, key=lambda x: int(x))], path
                        if isinstance(value, list) and value:
                            return [str(v.get("name", v.get("label", ""))) if isinstance(v, dict) else str(v)
                                    for v in value], path
                continue
            names = [line.strip() for line in text.splitlines() if line.strip()]
            if names:
                return names, path
    return [], None


# --------------------------------------------------------------------------
# what the mask values mean
# --------------------------------------------------------------------------
@dataclass
class LabelSpace:
    class_names: list
    has_background: bool
    values: list
    pixel_counts: dict
    source: str

    @property
    def num_classes(self) -> int:
        """Channels the network must output, background included if present."""
        return len(self.class_names)

    def frequencies(self) -> dict:
        total = sum(self.pixel_counts.values()) or 1
        out = {}
        for i, name in enumerate(self.class_names):
            out[name] = self.pixel_counts.get(i, 0) / total
        return out

    def to_dict(self) -> dict:
        return {
            "class_names": list(self.class_names),
            "has_background": self.has_background,
            "num_classes": self.num_classes,
            "values": list(self.values),
            "pixel_counts": {str(k): int(v) for k, v in self.pixel_counts.items()},
            "source": self.source,
        }


def read_mask(path) -> np.ndarray:
    """A mask is a grid of class indices, not a picture. Read it as indices."""
    arr = np.array(Image.open(path))
    if arr.ndim == 3:                 # RGB mask: the index sits in one channel
        arr = arr[..., 0]
    return arr


def inspect_labels(splits: dict, class_names=None, sample: int = 60) -> LabelSpace:
    """Work out the label space by reading actual mask pixels.

    The question that decides the network's output width is whether index 0 is
    an unlisted background or a real class. Counting the distinct values present
    answers it; assuming does not.
    """
    masks = []
    for name in ("train", "all", "val", "test"):
        if name in splits:
            masks += list(splits[name].masks)
    if not masks:
        masks = [m for split in splits.values() for m in split.masks]
    if len(masks) > sample and sample > 0:
        masks = masks[::max(1, len(masks) // sample)][:sample]

    counts: dict = {}
    for path in masks:
        vals, cnts = np.unique(read_mask(path), return_counts=True)
        for v, c in zip(vals.tolist(), cnts.tolist()):
            counts[int(v)] = counts.get(int(v), 0) + int(c)

    values = sorted(counts)
    max_value = max(values) if values else 0
    names = [str(n) for n in (class_names or []) if str(n).strip()]

    if names and len(names) == max_value + 1:
        has_bg = is_background(names[0])
        source = "class file covers every mask value"
    elif names and len(names) == max_value:
        # One more value than names: index 0 is an unlisted background.
        names = ["background"] + names
        has_bg = True
        source = "value 0 is an unlisted background"
    elif names:
        has_bg = is_background(names[0])
        source = "class file (count differs from mask values)"
        while len(names) <= max_value:
            names.append("class_%d" % len(names))
    elif max_value == len(DEFAULT_CLASSES):
        names = ["background"] + DEFAULT_CLASSES
        has_bg = True
        source = "inferred: 15 known classes + background"
    elif max_value == len(DEFAULT_CLASSES) - 1:
        names = list(DEFAULT_CLASSES)
        has_bg = False
        source = "inferred: 15 known classes, no background"
    else:
        names = ["class_%d" % i for i in range(max_value + 1)]
        has_bg = 0 in values
        source = "inferred from mask values only"

    return LabelSpace(names[:max_value + 1], has_bg, values, counts, source)


def summarise(splits: dict, space: LabelSpace) -> str:
    """The report every notebook prints after loading the data."""
    lines = ["Dataset", "-" * 58]
    total = 0
    for name in ("train", "val", "test", "all"):
        if name in splits:
            total += len(splits[name])
            lines.append("  %-6s %6d image/mask pairs" % (name, len(splits[name])))
    lines.append("  %-6s %6d" % ("total", total))
    lines.append("")
    lines.append("Classes: %d (%s background) - %s"
                 % (space.num_classes,
                    "with" if space.has_background else "no",
                    space.source))
    for name, share in sorted(space.frequencies().items(), key=lambda kv: -kv[1]):
        lines.append("  %6.2f%%  %s" % (share * 100, name))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# torch pieces
# --------------------------------------------------------------------------
import torch  # noqa: E402  (kept below the torch-free helpers on purpose)
import torch.nn as nn  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from torch.utils.data import Dataset  # noqa: E402


def load_image(path, size: int) -> np.ndarray:
    img = Image.open(path).convert("RGB").resize((size, size), Image.BILINEAR)
    return np.asarray(img, dtype=np.float32) / 255.0


def load_mask(path, size: int) -> np.ndarray:
    """Resize with NEAREST. Bilinear would invent class 3.5, which is not a class."""
    msk = Image.open(path)
    if msk.mode not in ("L", "P", "I", "I;16"):
        msk = msk.convert("L")
    arr = np.asarray(msk.resize((size, size), Image.NEAREST))
    if arr.ndim == 3:
        arr = arr[..., 0]
    return arr.astype(np.int64)


class Augment:
    """Conservative augmentation: geometry and light, never texture.

    Corrosion classes are separated by texture and severity, so blur or elastic
    warping can turn a genuine "mild" example into something a human would call
    "moderate". Flips, rotations and mild brightness changes model camera angle
    and lighting, which really do vary between inspections.
    """

    def __init__(self, size: int = 256, train: bool = True, seed=None):
        self.size = size
        self.train = train
        self.rng = np.random.default_rng(seed)

    def __call__(self, image: np.ndarray, mask: np.ndarray):
        if self.train:
            # Image and mask move together, always. Flip one alone and every
            # label is now in the wrong place.
            if self.rng.random() < 0.5:
                image, mask = image[:, ::-1], mask[:, ::-1]
            if self.rng.random() < 0.2:
                image, mask = image[::-1], mask[::-1]
            k = int(self.rng.integers(0, 4))
            if k:
                image, mask = np.rot90(image, k), np.rot90(mask, k)
            if self.rng.random() < 0.5:
                brightness = self.rng.uniform(-0.15, 0.15)
                contrast = self.rng.uniform(0.85, 1.15)
                image = np.clip((image - 0.5) * contrast + 0.5 + brightness, 0, 1)
        return np.ascontiguousarray(image), np.ascontiguousarray(mask)


class CorrosionDataset(Dataset):
    """Pairs of (image tensor, mask tensor) ready for a DataLoader."""

    def __init__(self, images, masks, size: int = 256, augment=None, cache: bool = False):
        if len(images) != len(masks):
            raise ValueError("%d images but %d masks" % (len(images), len(masks)))
        self.images = [Path(p) for p in images]
        self.masks = [Path(p) for p in masks]
        self.size = size
        self.augment = augment
        self.cache = cache
        self._cache: dict = {}

    def __len__(self) -> int:
        return len(self.images)

    def __getitem__(self, i: int):
        if self.cache and i in self._cache:
            image, mask = self._cache[i]
        else:
            image = load_image(self.images[i], self.size)
            mask = load_mask(self.masks[i], self.size)
            if self.cache:
                self._cache[i] = (image, mask)
        if self.augment is not None:
            image, mask = self.augment(image, mask)
        image = (image - MEAN) / STD
        x = torch.from_numpy(image.transpose(2, 0, 1).copy()).float()   # HWC -> CHW
        y = torch.from_numpy(mask.copy()).long()
        return x, y


def class_weights(masks, num_classes: int, size: int = 256, sample: int = 120,
                  power: float = 0.5, max_ratio: float = 8.0) -> torch.Tensor:
    """Frequency-based class weights, damped so they do not overcorrect.

    Plain median-frequency balancing weights background about 68x below
    everything else on this dataset, and the model answers by painting
    corrosion nearly everywhere. `power` (0.5 = square root) keeps rare classes
    boosted without collapsing the majority class, and `max_ratio` clamps the
    spread so no single class owns the gradient. Normalised to mean 1, so the
    learning rate does not have to change when these do.
    """
    masks = list(masks)
    counts = np.zeros(num_classes, dtype=np.float64)
    step = max(1, len(masks) // sample) if sample else 1
    for path in masks[::step]:
        vals, cnt = np.unique(load_mask(path, size), return_counts=True)
        for v, c in zip(vals, cnt):
            if 0 <= v < num_classes:
                counts[int(v)] += int(c)

    freq = counts / max(counts.sum(), 1)
    seen = freq[freq > 0]
    if seen.size == 0:
        return torch.ones(num_classes)
    ratio = np.where(freq > 0, np.median(seen) / np.maximum(freq, 1e-12), 0.0)
    weights = np.power(ratio, power, where=ratio > 0, out=np.zeros_like(ratio))
    positive = weights[weights > 0]
    weights = np.clip(weights, positive.min(), positive.min() * max_ratio)
    weights = np.where(freq > 0, weights, 0.0)
    mean = weights[weights > 0].mean()
    if mean > 0:
        weights = weights / mean
    return torch.tensor(weights, dtype=torch.float32)


class DiceLoss(nn.Module):
    """Region overlap instead of per-pixel counting.

    Cross-entropy asks "how many pixels are right?", which an imbalanced dataset
    answers with "predict background". Dice asks "how much do the regions
    overlap?", which is much closer to the IoU the model is actually judged on.
    """

    def __init__(self, smooth: float = 1.0):
        super().__init__()
        self.smooth = smooth

    def forward(self, logits, target):
        probs = torch.softmax(logits, dim=1)
        classes = logits.shape[1]
        true = F.one_hot(target.clamp(0, classes - 1), classes).permute(0, 3, 1, 2).float()
        dims = (0, 2, 3)
        inter = (probs * true).sum(dims)
        card = probs.sum(dims) + true.sum(dims)
        dice = (2 * inter + self.smooth) / (card + self.smooth)
        present = true.sum(dims) > 0            # absent classes must not count
        return 1.0 - (dice[present].mean() if present.any() else dice.mean())


class ComboLoss(nn.Module):
    """0.5 * weighted cross-entropy + 0.5 * Dice.

    They cover each other's blind spot. Early on, when predictions are near
    random, Dice is almost flat while cross-entropy still gives a useful
    gradient; later, Dice is what pushes boundaries into place.
    """

    def __init__(self, weight=None, ce_weight: float = 0.5, dice_weight: float = 0.5):
        super().__init__()
        self.ce = nn.CrossEntropyLoss(weight=weight)
        self.dice = DiceLoss()
        self.ce_weight = ce_weight
        self.dice_weight = dice_weight

    def forward(self, logits, target):
        return self.ce_weight * self.ce(logits, target) + self.dice_weight * self.dice(logits, target)


def build_loss(name: str = "combo", class_weights=None) -> nn.Module:
    if name == "ce":
        return nn.CrossEntropyLoss(weight=class_weights)
    if name == "dice":
        return DiceLoss()
    return ComboLoss(weight=class_weights)


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------
class ConfusionMatrix:
    """Accumulated over a whole split, then turned into IoU / Dice.

    Averaging per-batch IoUs gives a different - and wrong - number, because a
    class absent from one batch would silently score 0 for that batch.
    """

    def __init__(self, num_classes: int, class_names=None):
        self.n = num_classes
        self.names = list(class_names or ["class_%d" % i for i in range(num_classes)])
        self.m = np.zeros((num_classes, num_classes), dtype=np.int64)

    def update(self, target, pred):
        t = np.asarray(target.detach().cpu() if hasattr(target, "detach") else target).ravel()
        p = np.asarray(pred.detach().cpu() if hasattr(pred, "detach") else pred).ravel()
        keep = (t >= 0) & (t < self.n) & (p >= 0) & (p < self.n)
        idx = t[keep].astype(np.int64) * self.n + p[keep].astype(np.int64)
        self.m += np.bincount(idx, minlength=self.n ** 2).reshape(self.n, self.n)
        return self

    def compute(self) -> dict:
        m = self.m.astype(np.float64)
        tp = np.diag(m)
        fp = m.sum(0) - tp
        fn = m.sum(1) - tp
        union = tp + fp + fn
        iou = np.where(union > 0, tp / np.maximum(union, 1e-9), 0.0)
        dice = np.where(2 * tp + fp + fn > 0, 2 * tp / np.maximum(2 * tp + fp + fn, 1e-9), 0.0)
        present = m.sum(1) > 0
        return {
            "mean_iou": float(iou[present].mean()) if present.any() else 0.0,
            "mean_dice": float(dice[present].mean()) if present.any() else 0.0,
            "pixel_acc": float(tp.sum() / m.sum()) if m.sum() else 0.0,
            "per_class_iou": {self.names[i]: float(iou[i]) for i in range(self.n)},
            "per_class_dice": {self.names[i]: float(dice[i]) for i in range(self.n)},
            "support": {self.names[i]: int(m.sum(1)[i]) for i in range(self.n)},
        }

    def table(self) -> str:
        r = self.compute()
        lines = ["%-46s%9s%9s%12s" % ("class", "IoU", "Dice", "pixels"), "-" * 76]
        for name in sorted(r["per_class_iou"], key=lambda k: -r["support"][k]):
            support = r["support"][name]
            lines.append("%-46s%9.4f%9.4f%12s%s"
                         % (name, r["per_class_iou"][name], r["per_class_dice"][name],
                            format(support, ","), "" if support else "   (absent)"))
        lines.append("-" * 76)
        lines.append("%-46s%9.4f%9.4f" % ("mean (present in ground truth)",
                                          r["mean_iou"], r["mean_dice"]))
        lines.append("%-46s%9.4f" % ("pixel accuracy", r["pixel_acc"]))
        return "\n".join(lines)

    def to_csv(self) -> str:
        head = "truth\\pred," + ",".join(self.names)
        rows = [head]
        for i, name in enumerate(self.names):
            rows.append(name + "," + ",".join(str(int(v)) for v in self.m[i]))
        return "\n".join(rows)


# --------------------------------------------------------------------------
# the network
# --------------------------------------------------------------------------
class DoubleConv(nn.Module):
    """(conv 3x3 -> BatchNorm -> ReLU) x 2 - the block every level is built from."""

    def __init__(self, in_ch: int, out_ch: int, mid_ch=None):
        super().__init__()
        mid_ch = mid_ch or out_ch
        self.block = nn.Sequential(
            nn.Conv2d(in_ch, mid_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(mid_ch),
            nn.ReLU(inplace=True),
            nn.Conv2d(mid_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
        )

    def forward(self, x):
        return self.block(x)


class Down(nn.Module):
    """Halve the resolution, then double the channels."""

    def __init__(self, in_ch: int, out_ch: int):
        super().__init__()
        self.pool_conv = nn.Sequential(nn.MaxPool2d(2), DoubleConv(in_ch, out_ch))

    def forward(self, x):
        return self.pool_conv(x)


class Up(nn.Module):
    """Upsample, glue the skip connection on, then convolve."""

    def __init__(self, in_ch: int, out_ch: int, bilinear: bool = True):
        super().__init__()
        if bilinear:
            # No parameters, and none of the checkerboard artefacts a transposed
            # convolution is prone to.
            self.up = nn.Upsample(scale_factor=2, mode="bilinear", align_corners=True)
            self.conv = DoubleConv(in_ch, out_ch, in_ch // 2)
        else:
            self.up = nn.ConvTranspose2d(in_ch, in_ch // 2, kernel_size=2, stride=2)
            self.conv = DoubleConv(in_ch, out_ch)

    def forward(self, x, skip):
        x = self.up(x)
        # An odd input size leaves the upsampled tensor a pixel short; pad it.
        dy = skip.size(-2) - x.size(-2)
        dx = skip.size(-1) - x.size(-1)
        if dy or dx:
            x = F.pad(x, [dx // 2, dx - dx // 2, dy // 2, dy - dy // 2])
        return self.conv(torch.cat([skip, x], dim=1))


class UNet(nn.Module):
    """U-Net for multi-class semantic segmentation.

        input 3xHxW
          down1 -> 64   -------------------------->  up1 -> 64 -> output KxHxW
            down2 -> 128 ----------------->  up2 -> 128
              down3 -> 256 ------->  up3 -> 256
                down4 -> 512 -> up4 -> 512

    The horizontal arrows are skip connections, and they are the whole trick.
    Downsampling answers "what is this?" while throwing away "where exactly?".
    The skips hand the sharp early feature maps back to the decoder, which is
    what lets the network draw a pit boundary two pixels wide instead of a blob.
    """

    def __init__(self, num_classes: int, in_channels: int = 3, width: int = 64,
                 bilinear: bool = True, depth: int = 4):
        super().__init__()
        if depth < 1:
            raise ValueError("depth must be at least 1")
        self.num_classes = num_classes
        self.depth = depth
        self.width = width
        self.inc = DoubleConv(in_channels, width)

        self.downs = nn.ModuleList()
        chans = [width]
        c = width
        for i in range(depth):
            out = c * 2
            if i == depth - 1 and bilinear:
                # Halved at the bottleneck so the decoder's channel arithmetic
                # stays exact after each concatenation.
                out = c * 2 // 2
            self.downs.append(Down(c, out))
            c = out
            chans.append(c)

        self.ups = nn.ModuleList()
        for i in range(depth):
            skip_ch = chans[depth - 1 - i]
            out_ch = skip_ch
            if i < depth - 1 and bilinear and skip_ch > width:
                out_ch = skip_ch // 2
            self.ups.append(Up(c + skip_ch, out_ch, bilinear))
            c = out_ch

        self.outc = nn.Conv2d(c, num_classes, kernel_size=1)

    def forward(self, x):
        skips = [self.inc(x)]                 # keep every encoder output...
        for down in self.downs:
            skips.append(down(skips[-1]))
        out = skips[-1]
        for i, up in enumerate(self.ups):
            out = up(out, skips[-2 - i])      # ...to hand back on the way up
        return self.outc(out)                 # raw logits, one channel per class

    @torch.no_grad()
    def predict(self, x):
        self.eval()
        return self.forward(x).argmax(dim=1)

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)


def build_model(num_classes: int, width: int = 32, depth: int = 4, bilinear: bool = True) -> UNet:
    return UNet(num_classes=num_classes, width=width, depth=depth, bilinear=bilinear)


def pick_device(prefer: str = "auto"):
    if prefer != "auto":
        return torch.device(prefer)
    if torch.cuda.is_available():
        return torch.device("cuda")
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def describe_device(device) -> str:
    device = torch.device(device)
    if device.type == "cuda":
        props = torch.cuda.get_device_properties(device.index or 0)
        return "CUDA: %s, %.1f GB" % (props.name, props.total_memory / 1024 ** 3)
    if device.type == "mps":
        return "Apple MPS"
    return "CPU"


def seed_everything(seed: int = 42) -> None:
    """Seed every RNG that affects a run - call it BEFORE building the model,
    because weight initialisation draws from the global torch RNG."""
    import random

    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


# --------------------------------------------------------------------------
# checkpoints - written so a killed Colab session costs nothing
# --------------------------------------------------------------------------
def save_checkpoint(path, payload: dict) -> Path:
    """Write atomically: a disconnect mid-save must not corrupt the file.

    torch.save straight onto the target leaves a truncated file if the runtime
    dies halfway through, and the next session then fails to resume - the exact
    situation checkpointing exists to prevent. Write a temp file, then replace.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, tmp)
    os.replace(tmp, path)
    return path


def load_checkpoint(path, map_location="cpu"):
    path = Path(path)
    if not path.exists():
        return None
    try:
        return torch.load(path, map_location=map_location, weights_only=False)
    except Exception as exc:                  # a half-written file from a crash
        print("checkpoint unreadable (%s): %s" % (path.name, exc))
        return None


def model_from_checkpoint(state: dict, device="cpu"):
    """Rebuild the network a checkpoint describes. The checkpoint carries its own
    class names and geometry, so nothing has to be told how it was trained."""
    config = state.get("config", {}) or {}
    names = state.get("class_names") or []
    weights = state.get("model") or state.get("state_dict") or {}
    if not names:
        out = [v for k, v in weights.items() if k.endswith("outc.weight")]
        n = int(out[0].shape[0]) if out else len(DEFAULT_CLASSES) + 1
        names = ["class_%d" % i for i in range(n)]
    model = UNet(num_classes=len(names),
                 width=int(config.get("width", 32)),
                 depth=int(config.get("depth", 4)))
    model.load_state_dict(weights)
    model.to(device).eval()
    return model, names, config


# --------------------------------------------------------------------------
# inference and rendering
# --------------------------------------------------------------------------
@dataclass
class Prediction:
    mask: np.ndarray                 # (H, W) class indices, at the input's size
    confidence: np.ndarray           # (H, W) softmax probability of the winner
    class_pixels: dict
    class_share: dict
    mean_confidence: float
    dominant: str
    dominant_confidence: float
    image_size: tuple

    def rows(self, min_share: float = 0.0) -> list:
        out = [{"class": name,
                "pixels": self.class_pixels[name],
                "share_percent": round(self.class_share[name] * 100, 2)}
               for name in self.class_pixels if self.class_share[name] > min_share]
        return sorted(out, key=lambda r: -r["pixels"])

    def to_dict(self) -> dict:
        return {
            "dominant": self.dominant,
            "dominant_confidence": round(self.dominant_confidence, 4),
            "mean_confidence": round(self.mean_confidence, 4),
            "image_size": list(self.image_size),
            "classes": self.rows(0.0),
        }


def colorise(mask: np.ndarray, num_classes: int = None) -> Image.Image:
    n = num_classes or int(mask.max()) + 1
    rgb = np.zeros((mask.shape[0], mask.shape[1], 3), dtype=np.uint8)
    for i in range(n):
        rgb[mask == i] = PALETTE[i % len(PALETTE)]
    return Image.fromarray(rgb)


def overlay(image, mask: np.ndarray, alpha: float = 0.5) -> Image.Image:
    """Paint the prediction over the photograph, leaving background untouched
    so the inspector can still see the metal."""
    base = as_pil(image).convert("RGB")
    colour = colorise(mask).resize(base.size, Image.NEAREST)
    base_arr = np.asarray(base, dtype=np.float32)
    colour_arr = np.asarray(colour, dtype=np.float32)
    scaled = np.asarray(Image.fromarray(mask.astype(np.uint8)).resize(base.size, Image.NEAREST))
    blended = base_arr * (1 - alpha) + colour_arr * alpha
    blended[scaled == 0] = base_arr[scaled == 0]
    return Image.fromarray(blended.astype(np.uint8))


def as_pil(image) -> Image.Image:
    if isinstance(image, Image.Image):
        return image.convert("RGB")
    if isinstance(image, (str, Path)):
        return Image.open(image).convert("RGB")
    if isinstance(image, np.ndarray):
        arr = image
        if arr.dtype != np.uint8:
            arr = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
        return Image.fromarray(arr).convert("RGB")
    raise TypeError("cannot read an image from %s" % type(image))


class Predictor:
    """Loads a checkpoint and segments images. The only thing the deployed app
    imports from the training stack."""

    def __init__(self, checkpoint, device=None):
        self.checkpoint_path = Path(checkpoint)
        if not self.checkpoint_path.exists():
            raise FileNotFoundError("no checkpoint at %s" % self.checkpoint_path)
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        state = load_checkpoint(self.checkpoint_path, map_location=self.device)
        if state is None:
            raise ValueError("checkpoint at %s could not be read" % self.checkpoint_path)
        self.model, self.class_names, self.config = model_from_checkpoint(state, self.device)
        self.image_size = int(self.config.get("image_size", 256))
        self.trained_epoch = state.get("epoch")
        self.trained_iou = state.get("mean_iou")

    @torch.no_grad()
    def predict(self, image) -> Prediction:
        img = as_pil(image)
        original = img.size                                   # (W, H)
        small = img.resize((self.image_size, self.image_size), Image.BILINEAR)
        arr = (np.asarray(small, dtype=np.float32) / 255.0 - MEAN) / STD
        x = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0).float().to(self.device)

        probs = torch.softmax(self.model(x), dim=1)[0]
        conf, mask = probs.max(dim=0)
        mask_np = mask.cpu().numpy().astype(np.uint8)
        conf_np = conf.cpu().numpy().astype(np.float32)

        # Back to the caller's resolution, so an overlay lines up with their photo.
        mask_np = np.asarray(Image.fromarray(mask_np).resize(original, Image.NEAREST))
        conf_np = np.asarray(Image.fromarray(conf_np, mode="F").resize(original, Image.BILINEAR))

        total = mask_np.size
        pixels, share = {}, {}
        for i, name in enumerate(self.class_names):
            n = int((mask_np == i).sum())
            pixels[name] = n
            share[name] = n / total

        ranked = sorted(((n, name) for name, n in pixels.items() if not is_background(name)),
                        reverse=True)
        dominant = ranked[0][1] if ranked and ranked[0][0] > 0 else "none detected"
        if dominant == "none detected":
            dominant_conf = float(conf_np.mean())
        else:
            idx = self.class_names.index(dominant)
            dominant_conf = float(conf_np[mask_np == idx].mean())

        return Prediction(mask_np, conf_np, pixels, share, float(conf_np.mean()),
                          dominant, dominant_conf, original)

    def predict_batch(self, images) -> list:
        return [self.predict(im) for im in images]

    def colorise(self, mask):
        return colorise(mask, len(self.class_names))

    def overlay(self, image, mask, alpha: float = 0.5):
        return overlay(image, mask, alpha)

    def legend(self) -> list:
        return [{"index": i, "name": n, "color": "#%02x%02x%02x" % PALETTE[i % len(PALETTE)]}
                for i, n in enumerate(self.class_names)]

    def metadata(self) -> dict:
        return {
            "checkpoint": str(self.checkpoint_path),
            "classes": len(self.class_names),
            "class_names": self.class_names,
            "image_size": self.image_size,
            "device": str(self.device),
            "parameters": self.model.count_parameters(),
            "trained_epoch": self.trained_epoch,
            "validation_mean_iou": self.trained_iou,
        }


# --------------------------------------------------------------------------
# dataset plumbing shared by the notebooks
# --------------------------------------------------------------------------
def looks_like_dataset(root) -> bool:
    root = Path(root)
    if not root.is_dir():
        return False
    for split in ("train", "val", "valid", "test"):
        if (root / split / "images").is_dir():
            return True
    return (root / "images").is_dir()


def extract_zip(zip_path, dest, quiet: bool = False) -> Path:
    """Unzip, skipping the wrapper folder some exporters add."""
    zip_path, dest = Path(zip_path), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.namelist() if not m.startswith("/") and ".." not in m]
        zf.extractall(dest, members)
        if not quiet:
            print("extracted %d entries -> %s" % (len(members), dest))
    if not looks_like_dataset(dest):
        inner = [p for p in dest.iterdir() if p.is_dir() and looks_like_dataset(p)]
        if inner:
            return inner[0]
    return dest


def find_local_dataset(name: str = "corrovision-dataset-v1_semantic_export", start=None):
    """Walk up from the notebook looking for the export, so a checkout that has
    the data on disk needs no download and no configuration."""
    start = Path(start or Path.cwd()).resolve()
    roots = [start] + list(start.parents)[:6]
    for root in roots:
        for candidate in (root / name, root / "dataset" / name, root / "data" / name,
                          root / "datasets" / name):
            if looks_like_dataset(candidate):
                return candidate
    for root in roots:
        for candidate in (root, root / "dataset", root / "data"):
            if looks_like_dataset(candidate):
                return candidate
    return None


def make_sample_dataset(dest, count: int = 60, size: int = 128, seed: int = 7) -> Path:
    """A tiny synthetic export, shaped exactly like the real one.

    The last resort when no dataset can be found: a notebook that cannot reach
    the data should still run end to end so the intern can read real output
    while they sort the download out. It mimics the structure, not the physics -
    same layout, same 15 class names, same mask encoding, same background
    dominance. Anything trained on it proves the code path, nothing more.
    """
    dest = Path(dest)
    rng = np.random.default_rng(seed)
    (dest).mkdir(parents=True, exist_ok=True)
    (dest / "classes.txt").write_text("\n".join(DEFAULT_CLASSES))

    plan = {"train": count, "val": max(2, count // 5), "test": max(2, count // 5)}
    for split, n in plan.items():
        img_dir = dest / split / "images"
        msk_dir = dest / split / "masks"
        img_dir.mkdir(parents=True, exist_ok=True)
        msk_dir.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            cls = 1 + (i % len(DEFAULT_CLASSES))          # 0 stays background
            base = rng.normal(165, 12, (size, size, 1)).repeat(3, axis=2)
            mask = np.zeros((size, size), dtype=np.uint8)
            for _ in range(rng.integers(1, 4)):
                cy, cx = rng.integers(size // 6, size - size // 6, 2)
                r = int(rng.integers(size // 12, size // 5))
                yy, xx = np.ogrid[:size, :size]
                blob = (yy - cy) ** 2 + (xx - cx) ** 2 <= r ** 2
                mask[blob] = cls
                base[blob] = np.array(PALETTE[cls % len(PALETTE)], dtype=np.float64) * \
                    rng.uniform(0.75, 1.05)
            noise = rng.normal(0, 6, (size, size, 3))
            photo = np.clip(base + noise, 0, 255).astype(np.uint8)
            stem = "sample_%s_%03d" % (split, i)
            Image.fromarray(photo).save(img_dir / (stem + ".jpg"), quality=88)
            Image.fromarray(mask).save(msk_dir / (stem + ".png"))
    return dest


def write_manifest(path, splits: dict, space: LabelSpace, root, extra=None) -> Path:
    """What the later notebooks need to know about the data, in one small file."""
    payload = {
        "dataset_root": str(root),
        "kit_version": __version__,
        "splits": {name: {"count": len(split),
                          "images": [str(p) for p in split.images],
                          "masks": [str(p) for p in split.masks]}
                   for name, split in splits.items()},
        "label_space": space.to_dict(),
    }
    payload.update(extra or {})
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return path


def read_manifest(path):
    path = Path(path)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    splits = {name: Split(name, [Path(p) for p in payload["images"]],
                          [Path(p) for p in payload["masks"]])
              for name, payload in data.get("splits", {}).items()}
    space_raw = data.get("label_space", {})
    space = LabelSpace(space_raw.get("class_names", []),
                       space_raw.get("has_background", False),
                       space_raw.get("values", []),
                       {int(k): v for k, v in space_raw.get("pixel_counts", {}).items()},
                       space_raw.get("source", "manifest"))
    return {"root": data.get("dataset_root", ""), "splits": splits, "space": space, "raw": data}

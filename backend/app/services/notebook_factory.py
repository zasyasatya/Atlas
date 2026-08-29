"""Builds nbformat v4 playground notebooks for each internship topic."""
from __future__ import annotations

import uuid
from typing import Any


def _cell_id() -> str:
    return uuid.uuid4().hex[:12]


def _md(source: str) -> dict[str, Any]:
    return {"id": _cell_id(), "cell_type": "markdown", "metadata": {},
            "source": source.strip().splitlines(keepends=True)}


def _code(source: str) -> dict[str, Any]:
    return {"id": _cell_id(), "cell_type": "code", "metadata": {}, "execution_count": None,
            "outputs": [], "source": source.strip().splitlines(keepends=True)}


def _nb(cells: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11"},
            "atlas": {"generated": True},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


_HEADER = """# {title}

**ATLAS playground - {topic}**

This notebook runs on the compute target you picked in the platform
(CPU worker, Colab GPU, or Kaggle GPU). The injected `atlas` bridge streams
logs, metrics and artifacts back to your run timeline automatically.

| Helper | What it does |
|---|---|
| `atlas.log("...")` | append to the run log |
| `atlas.metric(accuracy=0.93)` | push a metric to the dashboard |
| `atlas.dataset()` | download the dataset attached to this run |
| `atlas.artifact("model.pkl")` | upload a trained file back to ATLAS |
| `atlas.finish()` | mark the run complete |
"""

_TABULAR = """
import pandas as pd, numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, classification_report

path = atlas.dataset()
if path:
    df = pd.read_csv(path)
else:
    rng = np.random.default_rng(7)
    n = 1200
    df = pd.DataFrame({
        "vibration": rng.normal(3.2, 0.9, n),
        "temperature": rng.normal(78, 12, n),
        "pressure": rng.normal(4.1, 0.7, n),
        "runtime_hours": rng.integers(100, 9000, n),
    })
    risk = (df.vibration * 0.8 + (df.temperature - 78) * 0.05 + (df.runtime_hours / 9000) * 2)
    df["failure"] = (risk > risk.median()).astype(int)
    atlas.log("No dataset attached - using synthetic sensor data.")

atlas.log("shape:", df.shape)
df.head()
"""

_TABULAR_TRAIN = """
target = "failure"
X = pd.get_dummies(df.drop(columns=[target]), drop_first=True)
y = df[target]
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

model = RandomForestClassifier(n_estimators=300, random_state=42, n_jobs=-1)
model.fit(X_train, y_train)
pred = model.predict(X_test)
proba = model.predict_proba(X_test).max(axis=1)

acc = accuracy_score(y_test, pred)
f1 = f1_score(y_test, pred, average="weighted")
atlas.metric(accuracy=round(float(acc), 4), f1_weighted=round(float(f1), 4),
             mean_confidence=round(float(proba.mean()), 4))
print(classification_report(y_test, pred))
"""

_EXPORT = """
import joblib, json
joblib.dump(model, "model.pkl")
json.dump({"features": list(X.columns)}, open("features.json", "w"))
atlas.artifact("model.pkl")
atlas.artifact("features.json")
atlas.finish("succeeded")
"""

_CV_SETUP = """
import torch, torchvision
atlas.log("torch", torch.__version__, "| cuda:", torch.cuda.is_available())
if torch.cuda.is_available():
    atlas.log("device:", torch.cuda.get_device_name(0))
else:
    atlas.log("WARNING: no GPU. Switch the run target to Colab GPU or Kaggle GPU.")
device = "cuda" if torch.cuda.is_available() else "cpu"
"""


def pid_extractor_notebook() -> dict[str, Any]:
    """Topic 2 - symbol + line detection on P&ID engineering drawings."""
    return _nb([
        _md(_HEADER.format(title="P&ID Symbol Extractor", topic="Topic 2 - Computer Vision")),
        _md("""## 0. Compute check
P&ID detection trains a real object detector. **Run this on a GPU target.**
The platform auto-upgrades this notebook to Colab/Kaggle GPU when you press Run."""),
        _code(_CV_SETUP),
        _code("""!pip -q install ultralytics==8.3.0 pdf2image opencv-python-headless 2>/dev/null
atlas.log("dependencies installed")"""),
        _md("""## 1. Dataset
Attach a YOLO-format dataset in the platform (Datasets tab) - images plus
`labels/*.txt` and a `data.yaml`. Classes are typically: `valve`, `pump`,
`instrument`, `vessel`, `line`, `tag`."""),
        _code("""import zipfile, os, glob
path = atlas.dataset()
DATA_DIR = "pid_data"
if path:
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with zipfile.ZipFile(path) as zf:
            zf.extractall(DATA_DIR)
        atlas.log("extracted", len(zf.namelist()), "files")
    except zipfile.BadZipFile:
        atlas.log("dataset is not a zip - treating as a single file")
yaml_files = glob.glob(f"{DATA_DIR}/**/data.yaml", recursive=True)
DATA_YAML = yaml_files[0] if yaml_files else None
atlas.log("data.yaml:", DATA_YAML)"""),
        _md("""## 2. Preprocessing
P&ID scans are large and mostly white. Tiling preserves small symbols that
would vanish if you resized a 5000px drawing down to 640px."""),
        _code("""import cv2, numpy as np

def tile_drawing(img_path, tile=1024, overlap=128):
    img = cv2.imread(img_path)
    if img is None:
        return []
    h, w = img.shape[:2]
    tiles, step = [], tile - overlap
    for y in range(0, max(h - overlap, 1), step):
        for x in range(0, max(w - overlap, 1), step):
            crop = img[y:y+tile, x:x+tile]
            if crop.shape[0] > 64 and crop.shape[1] > 64:
                tiles.append(((x, y), crop))
    return tiles

atlas.log("tiling helper ready")"""),
        _md("## 3. Train the detector"),
        _code("""from ultralytics import YOLO

EPOCHS = 50
model = YOLO("yolov8n.pt")
if DATA_YAML:
    results = model.train(data=DATA_YAML, epochs=EPOCHS, imgsz=1024, batch=8,
                          device=0 if device == "cuda" else "cpu", project="runs", name="pid")
    m = results.results_dict
    atlas.metric(mAP50=round(float(m.get("metrics/mAP50(B)", 0)), 4),
                 mAP50_95=round(float(m.get("metrics/mAP50-95(B)", 0)), 4),
                 precision=round(float(m.get("metrics/precision(B)", 0)), 4),
                 recall=round(float(m.get("metrics/recall(B)", 0)), 4))
else:
    atlas.log("No data.yaml found - attach a YOLO dataset and re-run.")"""),
        _md("""## 4. Symbol -> connectivity
Detected symbols become nodes; morphological line-following turns pipe runs
into edges. That graph is what the downstream web app consumes."""),
        _code("""def lines_from_drawing(img_path):
    img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return []
    bw = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, 25, 10)
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1)))
    vert  = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40)))
    mask = cv2.bitwise_or(horiz, vert)
    segs = cv2.HoughLinesP(mask, 1, np.pi/180, threshold=80, minLineLength=60, maxLineGap=12)
    return [] if segs is None else [tuple(s[0]) for s in segs]

atlas.log("connectivity helper ready")"""),
        _code("""best = "runs/pid/weights/best.pt"
import os
if os.path.exists(best):
    atlas.artifact(best)
atlas.finish("succeeded")"""),
    ])


def corrosion_segmentation_notebook() -> dict[str, Any]:
    """Topic 6 - semantic segmentation of corrosion types with U-Net.

    Written against the CorroVision export: 15 classes (5 corrosion families x
    3 severities) as single-channel mask PNGs. The notebook detects the label
    space from the files rather than hardcoding it, so a re-export with
    different classes still works.
    """
    return _nb([
        _md(_HEADER.format(title="Corrosion Type Segmentation",
                           topic="Topic 6 - Computer Vision")),

        # ---------------------------------------------------------- 0
        _md("""## 0. What you are building

Classification asks *"is there corrosion?"*. Segmentation asks *"which pixels,
and what kind?"* - you get a map, not a label. That is what an inspector needs:
where the damage is, how much of the surface it covers, and which repair it
implies.

Fifteen classes: five corrosion families, each at three severities.

| Family | What it looks like | Why it matters |
|---|---|---|
| `general` | Even rust across a broad area | Predictable metal loss, easiest to plan for |
| `pitting` | Small deep holes, often tiny on the surface | Dangerous - a pinhole can hide deep penetration |
| `crevice` | Concentrated in gaps, under bolts and flanges | Hidden by geometry, found late |
| `galvanic` | At the join between two different metals | A design fault, not just wear |
| `preferential_weld_attack` | Follows the weld line | Attacks the seam holding it together |

Each is labelled `mild`, `moderate` or `severe`. Telling *pitting* from
*crevice* is easier than telling *moderate* from *severe* - severity is partly
a judgement call, and the model inherits that ambiguity from the annotators.

**Compute:** this trains a real convolutional network. Pick **Colab GPU** or
**Kaggle GPU** as the run target. On CPU a full run takes hours instead of
minutes."""),

        _code(_CV_SETUP),

        _code("""!pip -q install numpy pillow 2>/dev/null
atlas.log("dependencies ready")"""),

        # ---------------------------------------------------------- 1
        _md("""## 1. The dataset

Upload the export from the annotation tool as a ZIP in the **Datasets** tab,
then attach it to this run. Expected inside:

```
train/images/*.jpg    train/masks/*.png
val/images/*.jpg      val/masks/*.png
test/images/*.jpg     test/masks/*.png
classes.txt
```

A mask is **not** a picture. It is a grid of class indices stored as a PNG: the
pixel value *is* the label. A pixel holding `7` means "class 7 here". Opened in
an image viewer a mask looks almost black, because the values are 0-15 out of a
possible 255 - that is expected, not a corrupt file.

The code below works out the label space by reading the pixels, rather than
assuming. The question that matters is whether index `0` means background or is
a real class, because it decides how many output channels the network needs."""),

        _code("""import zipfile, os, glob, json
from pathlib import Path
import numpy as np
from PIL import Image

ROOT = Path("corrosion_data")
path = atlas.dataset()
if path:
    ROOT.mkdir(exist_ok=True)
    try:
        with zipfile.ZipFile(path) as zf:
            zf.extractall(ROOT)
        atlas.log("extracted", len(zf.namelist()), "files")
    except zipfile.BadZipFile:
        atlas.log("attached file is not a zip")
else:
    atlas.log("no dataset attached - attach one in the platform and re-run")

def find_pairs(root):
    \"\"\"Pair every image with its mask, whatever the split layout.\"\"\"
    splits = {}
    for img_dir in sorted(Path(root).rglob("images")):
        msk_dir = img_dir.parent / "masks"
        if not msk_dir.is_dir():
            continue
        name = img_dir.parent.name
        name = {"valid": "val", "validation": "val", "training": "train"}.get(name, name)
        pairs = []
        for img in sorted(img_dir.iterdir()):
            if img.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp"}:
                continue
            msk = msk_dir / (img.stem + ".png")
            if msk.exists():
                pairs.append((img, msk))
        if pairs:
            splits.setdefault(name, []).extend(pairs)
    return splits

splits = find_pairs(ROOT)
for name, pairs in sorted(splits.items()):
    atlas.log(f"{name}: {len(pairs)} image/mask pairs")"""),

        _code("""# Read the class list if the exporter wrote one.
class_names = []
for candidate in ["classes.txt", "labels.txt"]:
    hits = list(ROOT.rglob(candidate))
    if hits:
        class_names = [l.strip() for l in hits[0].read_text().splitlines() if l.strip()]
        atlas.log(f"read {len(class_names)} names from {hits[0].name}")
        break

# Which values actually appear in the masks?
sample = [m for pairs in splits.values() for _, m in pairs][:60]
values = set()
pixel_counts = {}
for m in sample:
    arr = np.array(Image.open(m))
    if arr.ndim == 3:
        arr = arr[..., 0]
    v, c = np.unique(arr, return_counts=True)
    values.update(v.tolist())
    for vi, ci in zip(v.tolist(), c.tolist()):
        pixel_counts[vi] = pixel_counts.get(vi, 0) + ci

max_value = max(values) if values else 0
atlas.log("mask values present:", sorted(values))

# 15 names but values reach 15 -> there are 16 labels, so 0 is an unlisted
# background. 15 names and values stop at 14 -> no background.
if class_names and len(class_names) == max_value:
    class_names = ["background"] + class_names
    atlas.log("value 0 is an unlisted background -> prepended it")
elif not class_names:
    class_names = [f"class_{i}" for i in range(max_value + 1)]
    atlas.log("no class file; naming classes by index")

NUM_CLASSES = len(class_names)
total_px = sum(pixel_counts.values()) or 1
atlas.log(f"NUM_CLASSES = {NUM_CLASSES}")
for i, n in enumerate(class_names):
    share = pixel_counts.get(i, 0) / total_px
    atlas.log(f"  {i:>2} {n:<46} {share*100:6.2f}% of pixels")"""),

        _md("""### Read that class distribution before going further

Background will be the large majority - typically 80% or more. This is the
single most important fact about the dataset, because it sets a trap: a model
that predicts "background" for every pixel scores over 80% accuracy and is
completely useless.

Two consequences, both handled below:

1. **Accuracy is the wrong metric.** Use IoU per class instead.
2. **The loss needs help**, or gradient descent will take the easy win and
   predict background everywhere."""),

        # ---------------------------------------------------------- 2
        _md("""## 2. Loading and augmentation

Two rules specific to segmentation:

**Resize masks with NEAREST, never bilinear.** Smoothing interpolation averages
neighbouring pixels. Halfway between class 3 and class 4 is 3.5, which is not a
class - it silently corrupts labels.

**Augment the image and the mask together.** Flip one without the other and the
labels no longer line up with the pixels.

Augmentation is kept conservative on purpose. Corrosion classes are separated by
texture and severity, so heavy blur or elastic warping can turn a genuine "mild"
example into something a human would call "moderate". Flips, rotations and mild
brightness changes model camera angle and lighting, which really do vary."""),

        _code("""import torch
from torch.utils.data import Dataset, DataLoader

SIZE = 512  # drop to 256 if the GPU runs out of memory
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32)

class CorrosionDataset(Dataset):
    def __init__(self, pairs, size=SIZE, train=False, seed=0):
        self.pairs, self.size, self.train = pairs, size, train
        self.rng = np.random.default_rng(seed)

    def __len__(self):
        return len(self.pairs)

    def __getitem__(self, i):
        img_p, msk_p = self.pairs[i]
        img = Image.open(img_p).convert("RGB").resize((self.size, self.size), Image.BILINEAR)
        msk = Image.open(msk_p).resize((self.size, self.size), Image.NEAREST)  # NEAREST!
        img = np.asarray(img, dtype=np.float32) / 255.0
        msk = np.asarray(msk)
        if msk.ndim == 3:
            msk = msk[..., 0]
        msk = msk.astype(np.int64)

        if self.train:
            if self.rng.random() < 0.5:
                img, msk = img[:, ::-1], msk[:, ::-1]      # both, together
            if self.rng.random() < 0.3:
                img, msk = img[::-1], msk[::-1]
            if self.rng.random() < 0.5:
                img = np.clip((img - 0.5) * self.rng.uniform(0.85, 1.15)
                              + 0.5 + self.rng.uniform(-0.15, 0.15), 0, 1)

        img = (np.ascontiguousarray(img) - MEAN) / STD
        x = torch.from_numpy(img.transpose(2, 0, 1).copy()).float()
        y = torch.from_numpy(np.ascontiguousarray(msk).copy()).long()
        return x, y

train_ds = CorrosionDataset(splits.get("train", []), train=True, seed=42)
val_ds   = CorrosionDataset(splits.get("val", []))
test_ds  = CorrosionDataset(splits.get("test", []))
atlas.log(f"train {len(train_ds)} | val {len(val_ds)} | test {len(test_ds)}")"""),

        # ---------------------------------------------------------- 3
        _md("""## 3. U-Net, and why it is shaped like that

A plain classifier crushes an image down to one label. Segmentation needs a
prediction for every pixel, so the network has to come back *up* to full
resolution. U-Net does exactly that, and its name is its diagram:

```
input ---> 64 ---------------------------------> 64 ---> output
            |                                    ^
            v                                    |
           128 ------------------------------> 128
            |                                    ^
            v                                    |
           256 --------------------------> 256
            |                              ^
            v                              |
                       512 (bottleneck)
```

The **left side** downsamples: each step halves the resolution and doubles the
channels. It answers *what is in this image* - and in doing so throws away
*exactly where*.

The **right side** upsamples back to full size.

The **horizontal arrows are skip connections**, and they are the entire trick.
Without them the decoder has to reconstruct precise boundaries from a blurry
low-resolution summary, and you get vague blobs. The skips hand the encoder's
sharp early feature maps directly across, so the decoder can combine "this
region is pitting" with "the edge is exactly here". For thin defects like a
weld-line attack a few pixels wide, that is the difference between a usable
prediction and a smear.

The implementation below is the full architecture, written out."""),

        _code("""import torch.nn as nn
import torch.nn.functional as F

class DoubleConv(nn.Module):
    \"\"\"(conv 3x3 -> BatchNorm -> ReLU) x 2\"\"\"
    def __init__(self, cin, cout, mid=None):
        super().__init__()
        mid = mid or cout
        self.block = nn.Sequential(
            nn.Conv2d(cin, mid, 3, padding=1, bias=False),
            nn.BatchNorm2d(mid), nn.ReLU(inplace=True),
            nn.Conv2d(mid, cout, 3, padding=1, bias=False),
            nn.BatchNorm2d(cout), nn.ReLU(inplace=True))
    def forward(self, x):
        return self.block(x)

class Down(nn.Module):
    # Halve the resolution, then double the channels.
    def __init__(self, cin, cout):
        super().__init__()
        self.pool_conv = nn.Sequential(nn.MaxPool2d(2), DoubleConv(cin, cout))
    def forward(self, x):
        return self.pool_conv(x)

class Up(nn.Module):
    # Upsample, concatenate the skip connection, convolve.
    def __init__(self, cin, cout):
        super().__init__()
        self.up = nn.Upsample(scale_factor=2, mode="bilinear", align_corners=True)
        self.conv = DoubleConv(cin, cout, cin // 2)
    def forward(self, x, skip):
        x = self.up(x)
        dy, dx = skip.size(-2) - x.size(-2), skip.size(-1) - x.size(-1)
        if dy or dx:
            x = F.pad(x, [dx//2, dx-dx//2, dy//2, dy-dy//2])
        return self.conv(torch.cat([skip, x], dim=1))

class UNet(nn.Module):
    # Same module names as templates/corrosion_unet/corrosion/model.py, so a
    # checkpoint saved here loads directly in the deployment app.
    def __init__(self, num_classes, width=64, depth=4):
        super().__init__()
        self.num_classes, self.depth = num_classes, depth
        self.inc = DoubleConv(3, width)

        self.downs = nn.ModuleList()
        chans, c = [width], width
        for i in range(depth):
            out = c * 2 // 2 if i == depth - 1 else c * 2   # halved at the bottleneck
            self.downs.append(Down(c, out))
            c = out
            chans.append(c)

        self.ups = nn.ModuleList()
        for i in range(depth):
            skip_ch = chans[depth - 1 - i]
            out_ch = skip_ch
            if i < depth - 1 and skip_ch > width:
                out_ch = skip_ch // 2
            self.ups.append(Up(c + skip_ch, out_ch))
            c = out_ch

        self.outc = nn.Conv2d(c, num_classes, 1)

    def forward(self, x):
        skips = [self.inc(x)]           # keep every encoder output...
        for down in self.downs:
            skips.append(down(skips[-1]))
        out = skips[-1]
        for i, up in enumerate(self.ups):
            out = up(out, skips[-2 - i])  # ...to hand back on the way up
        return self.outc(out)           # raw logits, one channel per class

WIDTH = 64        # drop to 32 if the GPU is tight on memory
model = UNet(NUM_CLASSES, width=WIDTH).to(device)
atlas.log(f"U-Net: {sum(p.numel() for p in model.parameters()):,} parameters, "
          f"{NUM_CLASSES} output channels")

# Sanity check: output must be the same height and width as the input.
with torch.no_grad():
    probe = model(torch.randn(1, 3, 256, 256, device=device))
atlas.log("shape check:", tuple(probe.shape), "<- (batch, classes, H, W)")"""),

        # ---------------------------------------------------------- 4
        _md("""## 4. Loss: making the model care about 18% of the pixels

Cross-entropy alone optimises average per-pixel correctness. With background at
~82%, the cheapest way to lower that average is to predict background more
often - so the model learns to ignore the very thing you want.

Two corrections, used together:

**Class weights.** Rare classes count for more. The textbook recipe is
`median(frequency) / frequency`, but on this distribution that weights
background about 68x below everything else and the model overcorrects, spraying
corrosion everywhere. Taking the square root and clamping the spread keeps rare
classes boosted without collapsing the majority class.

**Dice loss.** Cross-entropy counts pixels; Dice measures *region overlap*,
which is much closer to what IoU scores and far less sensitive to imbalance.

They complement each other. Early in training, when predictions are near random,
Dice is almost flat while cross-entropy still gives a useful gradient. Later,
Dice is what pushes the boundaries into place. Summing them gets both."""),

        _code("""# --- class weights, damped ---------------------------------------------
counts = np.zeros(NUM_CLASSES)
for i in range(0, len(train_ds), max(1, len(train_ds)//100)):
    _, m = train_ds.pairs[i]
    arr = np.array(Image.open(m))
    if arr.ndim == 3:
        arr = arr[..., 0]
    v, c = np.unique(arr, return_counts=True)
    for vi, ci in zip(v, c):
        if vi < NUM_CLASSES:
            counts[vi] += ci

freq = counts / max(counts.sum(), 1)
seen = freq[freq > 0]
ratio = np.where(freq > 0, np.median(seen) / np.maximum(freq, 1e-12), 0.0)
weights = np.sqrt(ratio)                       # damp the correction
pos = weights[weights > 0]
weights = np.where(freq > 0, np.clip(weights, pos.min(), pos.min()*8), 0.0)
weights = weights / weights[weights > 0].mean()  # normalise to mean 1
weights_t = torch.tensor(weights, dtype=torch.float32, device=device)
atlas.log("background weight:", round(float(weights_t[0]), 3),
          "| max:", round(float(weights_t.max()), 3))

# --- combo loss ---------------------------------------------------------
class DiceLoss(nn.Module):
    def __init__(self, smooth=1.0):
        super().__init__()
        self.smooth = smooth
    def forward(self, logits, target):
        probs = F.softmax(logits, dim=1)
        true1h = F.one_hot(target.clamp(0, logits.shape[1]-1),
                           logits.shape[1]).permute(0, 3, 1, 2).float()
        dims = (0, 2, 3)
        inter = (probs * true1h).sum(dims)
        card  = probs.sum(dims) + true1h.sum(dims)
        dice = (2*inter + self.smooth) / (card + self.smooth)
        present = true1h.sum(dims) > 0        # ignore absent classes
        return 1.0 - (dice[present].mean() if present.any() else dice.mean())

ce, dl = nn.CrossEntropyLoss(weight=weights_t), DiceLoss()
def loss_fn(logits, target):
    return 0.5*ce(logits, target) + 0.5*dl(logits, target)
atlas.log("loss = 0.5 * weighted cross-entropy + 0.5 * dice")"""),

        # ---------------------------------------------------------- 5
        _md("""## 5. Metrics: IoU, not accuracy

**IoU** (Intersection over Union) per class = correctly predicted pixels of that
class, divided by every pixel either predicted as it or truly it. Predict
background everywhere and every corrosion class scores 0 - the metric refuses to
be fooled.

**Dice** = `2 x overlap / (predicted + actual)`. Slightly more forgiving on small
regions, which is why medical and defect segmentation often report both.

Both are computed from a confusion matrix accumulated over the whole split.
Averaging per-batch IoUs would give a different, wrong number."""),

        _code("""class ConfusionMatrix:
    def __init__(self, n, names):
        self.n, self.names = n, names
        self.m = np.zeros((n, n), dtype=np.int64)
    def update(self, target, pred):
        t = target.detach().cpu().numpy().ravel()
        p = pred.detach().cpu().numpy().ravel()
        keep = (t >= 0) & (t < self.n) & (p >= 0) & (p < self.n)
        idx = t[keep].astype(np.int64) * self.n + p[keep].astype(np.int64)
        self.m += np.bincount(idx, minlength=self.n**2).reshape(self.n, self.n)
    def compute(self):
        m = self.m.astype(np.float64)
        tp = np.diag(m)
        fp, fn = m.sum(0) - tp, m.sum(1) - tp
        union = tp + fp + fn
        iou  = np.where(union > 0, tp / np.maximum(union, 1e-9), 0.0)
        dice = np.where(2*tp+fp+fn > 0, 2*tp / np.maximum(2*tp+fp+fn, 1e-9), 0.0)
        present = m.sum(1) > 0            # classes absent from truth are excluded
        return {
            "mean_iou":  float(iou[present].mean()) if present.any() else 0.0,
            "mean_dice": float(dice[present].mean()) if present.any() else 0.0,
            "pixel_acc": float(tp.sum() / m.sum()) if m.sum() else 0.0,
            "per_class_iou": {self.names[i]: float(iou[i]) for i in range(self.n)},
            "support": {self.names[i]: int(m.sum(1)[i]) for i in range(self.n)},
        }
atlas.log("metrics ready")"""),

        # ---------------------------------------------------------- 6
        _md("""## 6. Training

Mixed precision (`autocast` + `GradScaler`) is switched on for CUDA. It runs most
operations in 16-bit, roughly halving memory use and speeding training up
noticeably, while keeping a 32-bit copy of the weights for stability. The
`GradScaler` multiplies the loss before backprop so small gradients do not
vanish in 16-bit, then scales them back before the optimiser step.

Every epoch reports through `atlas.metric(...)`, so the platform charts progress
live and the run history survives the notebook."""),

        _code("""EPOCHS = 40
BATCH  = 8 if SIZE <= 256 else 4

if len(train_ds) == 0:
    atlas.log("No training data - attach a dataset and re-run.")
else:
    torch.manual_seed(42)
    tl = DataLoader(train_ds, batch_size=BATCH, shuffle=True, num_workers=2, pin_memory=True)
    vl = DataLoader(val_ds,   batch_size=BATCH, num_workers=2, pin_memory=True)

    opt = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=EPOCHS)
    use_amp = (device == "cuda")
    scaler = torch.amp.GradScaler("cuda") if use_amp else None

    best_iou, history = -1.0, []
    for epoch in range(1, EPOCHS + 1):
        model.train(); running = 0.0
        for x, y in tl:
            x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
            opt.zero_grad(set_to_none=True)
            if use_amp:
                with torch.autocast("cuda", dtype=torch.float16):
                    loss = loss_fn(model(x), y)
                scaler.scale(loss).backward()
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(opt); scaler.update()
            else:
                loss = loss_fn(model(x), y)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
            running += loss.item() * x.size(0)
        sched.step()

        model.eval()
        cm = ConfusionMatrix(NUM_CLASSES, class_names)
        vloss = 0.0
        with torch.no_grad():
            for x, y in vl:
                x, y = x.to(device), y.to(device)
                logits = model(x)
                vloss += loss_fn(logits, y).item() * x.size(0)
                cm.update(y, logits.argmax(1))
        r = cm.compute()

        row = {"epoch": epoch,
               "train_loss": round(running/max(len(train_ds),1), 4),
               "val_loss":   round(vloss/max(len(val_ds),1), 4),
               "val_mean_iou":  round(r["mean_iou"], 4),
               "val_mean_dice": round(r["mean_dice"], 4),
               "val_pixel_acc": round(r["pixel_acc"], 4)}
        history.append(row)
        atlas.metric(**row)

        if r["mean_iou"] > best_iou:
            best_iou = r["mean_iou"]
            torch.save({"model": model.state_dict(), "class_names": class_names,
                        "epoch": epoch, "mean_iou": best_iou,
                        "config": {"image_size": SIZE, "width": WIDTH, "depth": 4}},
                       "corrosion_unet_best.pt")
            atlas.log(f"epoch {epoch}: new best mIoU {best_iou:.4f} - checkpoint saved")
        else:
            atlas.log(f"epoch {epoch}: mIoU {r['mean_iou']:.4f} (best {best_iou:.4f})")"""),

        # ---------------------------------------------------------- 7
        _md("""## 7. Test and per-class report

The number that matters is per-class IoU on the held-out test split. A good mean
can hide a class the model never gets right - and if that class is `pitting`,
the model is not fit for purpose regardless of its average."""),

        _code("""if len(test_ds):
    ckpt = torch.load("corrosion_unet_best.pt", map_location=device, weights_only=False)
    model.load_state_dict(ckpt["model"]); model.eval()

    cm = ConfusionMatrix(NUM_CLASSES, class_names)
    with torch.no_grad():
        for x, y in DataLoader(test_ds, batch_size=BATCH):
            cm.update(y.to(device), model(x.to(device)).argmax(1))
    r = cm.compute()

    atlas.log("")
    atlas.log(f"{'class':<46}{'IoU':>8}{'pixels':>12}")
    atlas.log("-" * 66)
    for name, iou in sorted(r["per_class_iou"].items(),
                            key=lambda kv: -r["support"][kv[0]]):
        n = r["support"][name]
        atlas.log(f"{name:<46}{iou:>8.4f}{n:>12,}" + ("" if n else "   absent"))
    atlas.log("-" * 66)
    atlas.log(f"{'mean IoU':<46}{r['mean_iou']:>8.4f}")
    atlas.log(f"{'mean Dice':<46}{r['mean_dice']:>8.4f}")
    atlas.log(f"{'pixel accuracy':<46}{r['pixel_acc']:>8.4f}")

    atlas.metric(test_mean_iou=round(r["mean_iou"], 4),
                 test_mean_dice=round(r["mean_dice"], 4),
                 test_pixel_acc=round(r["pixel_acc"], 4))

    with open("report.json", "w") as f:
        json.dump(r, f, indent=2)
    atlas.artifact("report.json")"""),

        # ---------------------------------------------------------- 8
        _md("""## 8. Look at the predictions

Metrics summarise; they do not explain. Overlay a few predictions on the
original photographs and check the failures make sense. Confusion between
`moderate` and `severe` of the same family is expected. Confusion between
`pitting` and `general` is a real problem."""),

        _code("""PALETTE = np.array([
    [0,0,0],
    [255,179,179],[255,102,102],[204,0,0],
    [255,224,178],[255,183,77],[230,126,34],
    [200,230,201],[102,187,106],[27,120,55],
    [187,222,251],[66,165,245],[21,76,168],
    [225,190,231],[186,104,200],[123,31,162],
], dtype=np.uint8)

if len(test_ds):
    os.makedirs("previews", exist_ok=True)
    for i in range(min(4, len(test_ds))):
        x, y = test_ds[i]
        with torch.no_grad():
            probs = torch.softmax(model(x.unsqueeze(0).to(device)), 1)[0]
            conf, pred = probs.max(0)
        pred = pred.cpu().numpy()

        photo = np.array(Image.open(test_ds.pairs[i][0]).convert("RGB")
                         .resize((SIZE, SIZE)))
        colour = PALETTE[np.clip(pred, 0, len(PALETTE)-1)]
        blend = photo.copy()
        fg = pred > 0
        blend[fg] = (0.5*photo[fg] + 0.5*colour[fg]).astype(np.uint8)

        strip = np.concatenate([photo, colour, blend], axis=1)
        out = f"previews/pred_{i}.png"
        Image.fromarray(strip).save(out)
        atlas.artifact(out)

        found = [(class_names[c], int((pred == c).sum()))
                 for c in np.unique(pred) if c > 0]
        found.sort(key=lambda kv: -kv[1])
        atlas.log(f"image {i}: mean confidence {conf.mean():.1%} | " +
                  ", ".join(f"{n} {p}px" for n, p in found[:3]))
    atlas.log("saved previews: original | predicted mask | overlay")"""),

        # ---------------------------------------------------------- 9
        _md("""## 9. Ship it

`corrosion_unet_best.pt` carries its own class names and input size, so the
deployment app can rebuild the model without being told how it was trained.

Next: the **Deployment** tab. The Streamlit reference app already meets all five
rubric rules - single and bulk input, the four documentation sections, confidence
scores and charts. Open it in the platform under **Pipeline Library -> Corrosion
U-Net** (file `app.py`), or download the whole folder as a zip from there. Point
it at this checkpoint, then attach the deployed URL in Whimsical."""),

        _code("""atlas.artifact("corrosion_unet_best.pt")
atlas.log("checkpoint uploaded - attach it in the Deployment tab")
atlas.finish("succeeded")"""),
    ])


def tabular_notebook(title: str, topic: str) -> dict[str, Any]:
    return _nb([
        _md(_HEADER.format(title=title, topic=topic)),
        _md("## 1. Load data"),
        _code(_TABULAR),
        _md("## 2. Train + evaluate"),
        _code(_TABULAR_TRAIN),
        _md("## 3. Export for the web app"),
        _code(_EXPORT),
    ])


def forecasting_notebook(title: str, topic: str) -> dict[str, Any]:
    return _nb([
        _md(_HEADER.format(title=title, topic=topic)),
        _md("""## 1. Series
Forecasting deliverables must report **MAPE** - it is the mandatory metric in
the graduation rubric."""),
        _code("""import pandas as pd, numpy as np
path = atlas.dataset()
if path:
    df = pd.read_csv(path, parse_dates=[0])
    df = df.rename(columns={df.columns[0]: "ds", df.columns[1]: "y"})
else:
    idx = pd.date_range("2023-01-01", periods=730, freq="D")
    trend = np.linspace(100, 160, 730)
    season = 12 * np.sin(np.arange(730) * 2 * np.pi / 365.25)
    df = pd.DataFrame({"ds": idx, "y": trend + season + np.random.default_rng(3).normal(0, 4, 730)})
    atlas.log("Using synthetic production series.")
df.tail()"""),
        _md("## 2. Baseline + gradient boosting"),
        _code("""from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_percentage_error, mean_absolute_error

d = df.copy()
for lag in (1, 7, 14, 28):
    d[f"lag{lag}"] = d.y.shift(lag)
d["dow"], d["month"] = d.ds.dt.dayofweek, d.ds.dt.month
d = d.dropna()
cut = int(len(d) * 0.85)
train, test = d[:cut], d[cut:]
feats = [c for c in d.columns if c not in ("ds", "y")]

model = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.06)
model.fit(train[feats], train.y)
pred = model.predict(test[feats])

mape = mean_absolute_percentage_error(test.y, pred) * 100
mae = mean_absolute_error(test.y, pred)
atlas.metric(mape_percent=round(float(mape), 3), mae=round(float(mae), 3))
atlas.log(f"MAPE={mape:.2f}%  MAE={mae:.2f}")"""),
        _code("""import joblib
joblib.dump(model, "forecaster.pkl")
atlas.artifact("forecaster.pkl")
atlas.finish("succeeded")"""),
    ])


def nlp_notebook(title: str, topic: str) -> dict[str, Any]:
    return _nb([
        _md(_HEADER.format(title=title, topic=topic)),
        _md("## 1. Documents"),
        _code("""import pandas as pd
path = atlas.dataset()
if path:
    df = pd.read_csv(path)
else:
    df = pd.DataFrame({
        "text": ["Pump P-101 leaking at seal, vibration high",
                 "Routine inspection completed, no findings",
                 "Corrosion observed on line 6-INCH-CS at support",
                 "Valve V-22 fails to close fully during test"],
        "label": ["mechanical", "none", "corrosion", "mechanical"],
    })
    atlas.log("Using built-in sample reports.")
df.head()"""),
        _md("## 2. TF-IDF baseline"),
        _code("""from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import cross_val_score
import numpy as np

pipe = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), min_df=1),
                     LogisticRegression(max_iter=1000))
folds = min(3, df.label.value_counts().min(), len(df) // 2) if len(df) > 3 else 2
scores = cross_val_score(pipe, df.text, df.label, cv=max(folds, 2))
pipe.fit(df.text, df.label)
atlas.metric(cv_accuracy=round(float(np.mean(scores)), 4))
atlas.log("cv accuracy:", np.mean(scores))"""),
        _md("## 3. Entity extraction with regex rules"),
        _code("""import re
TAG = re.compile(r"\\b([A-Z]{1,3}-\\d{2,4})\\b")
SIZE = re.compile(r"\\b(\\d+(?:\\.\\d+)?)\\s*-?\\s*(INCH|IN|MM)\\b", re.I)

def extract(text):
    return {"equipment_tags": TAG.findall(text),
            "sizes": ["".join(m) for m in SIZE.findall(text)]}

for t in df.text.head(3):
    atlas.log(t, "->", extract(t))"""),
        _code("""import joblib
joblib.dump(pipe, "nlp_model.pkl")
atlas.artifact("nlp_model.pkl")
atlas.finish("succeeded")"""),
    ])


def rag_notebook(title: str, topic: str) -> dict[str, Any]:
    return _nb([
        _md(_HEADER.format(title=title, topic=topic)),
        _md("""## 1. Chunk the corpus
RAG quality is decided at chunking time, long before the LLM is involved."""),
        _code("""path = atlas.dataset()
if path:
    raw = open(path, "rb").read().decode("utf-8", errors="ignore")
else:
    raw = ("Standard operating procedure. Isolate the line before maintenance. "
           "Lock out and tag out all energy sources. Verify zero pressure. "
           "Purge with nitrogen until oxygen is below two percent. "
           "Only then open the flange. Record every step in the permit.") * 20
    atlas.log("Using sample SOP text.")

def chunk(text, size=400, overlap=80):
    words, out, i = text.split(), [], 0
    while i < len(words):
        out.append(" ".join(words[i:i+size]))
        i += size - overlap
    return out

chunks = chunk(raw)
atlas.log("chunks:", len(chunks))"""),
        _md("## 2. Embed + retrieve (TF-IDF baseline, swap for a vector DB later)"),
        _code("""from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

vec = TfidfVectorizer(stop_words="english").fit(chunks)
matrix = vec.transform(chunks)

def retrieve(question, k=3):
    sims = cosine_similarity(vec.transform([question]), matrix)[0]
    top = sims.argsort()[::-1][:k]
    return [(chunks[i][:200], round(float(sims[i]), 3)) for i in top]

for hit, score in retrieve("How do I purge the line?"):
    atlas.log(f"[{score}] {hit[:120]}")"""),
        _md("## 3. Grounded answer + evaluation"),
        _code("""questions = ["How do I purge the line?", "What must be locked out?"]
hit_rate = sum(1 for q in questions if retrieve(q)[0][1] > 0.05) / len(questions)
atlas.metric(retrieval_hit_rate=round(hit_rate, 3), chunk_count=len(chunks))
atlas.finish("succeeded")"""),
    ])

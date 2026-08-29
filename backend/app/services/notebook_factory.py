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
    """Topic 6 - semantic segmentation of corrosion types."""
    return _nb([
        _md(_HEADER.format(title="Corrosion Type Segmentation", topic="Topic 6 - Computer Vision")),
        _md("""## 0. Compute check
Segmentation training needs a GPU. Choose **Colab GPU** or **Kaggle GPU** as
the run target; ATLAS blocks this notebook from silently running on CPU."""),
        _code(_CV_SETUP),
        _code("""!pip -q install segmentation-models-pytorch==0.3.4 albumentations==1.4.14 opencv-python-headless 2>/dev/null
atlas.log("dependencies installed")"""),
        _md("""## 1. Dataset
Expected layout inside the uploaded zip:

```
images/  img001.jpg ...
masks/   img001.png ...   # palette PNG, one value per class
```
Classes: `0 background, 1 uniform, 2 pitting, 3 crevice, 4 galvanic, 5 scaling`."""),
        _code("""import zipfile, os, glob
CLASSES = ["background", "uniform", "pitting", "crevice", "galvanic", "scaling"]
NUM_CLASSES = len(CLASSES)
path = atlas.dataset()
ROOT = "corrosion"
if path:
    os.makedirs(ROOT, exist_ok=True)
    try:
        with zipfile.ZipFile(path) as zf:
            zf.extractall(ROOT)
    except zipfile.BadZipFile:
        atlas.log("not a zip archive")
images = sorted(glob.glob(f"{ROOT}/**/images/*.*", recursive=True))
masks  = sorted(glob.glob(f"{ROOT}/**/masks/*.*", recursive=True))
atlas.log(f"{len(images)} images / {len(masks)} masks")"""),
        _md("""## 2. Augmentation
Corrosion is texture-driven. Colour jitter and flips help; heavy geometric
distortion hurts, because pit geometry *is* the label."""),
        _code("""import albumentations as A
from albumentations.pytorch import ToTensorV2

SIZE = 512
train_tf = A.Compose([
    A.LongestMaxSize(SIZE), A.PadIfNeeded(SIZE, SIZE),
    A.HorizontalFlip(p=0.5), A.VerticalFlip(p=0.2),
    A.RandomBrightnessContrast(0.2, 0.2, p=0.5),
    A.HueSaturationValue(10, 15, 10, p=0.3),
    A.Normalize(), ToTensorV2(),
])
valid_tf = A.Compose([A.LongestMaxSize(SIZE), A.PadIfNeeded(SIZE, SIZE), A.Normalize(), ToTensorV2()])
atlas.log("transforms ready")"""),
        _code("""import cv2, numpy as np, torch
from torch.utils.data import Dataset, DataLoader

class CorrosionDataset(Dataset):
    def __init__(self, imgs, msks, tf):
        self.imgs, self.msks, self.tf = imgs, msks, tf
    def __len__(self):
        return len(self.imgs)
    def __getitem__(self, i):
        img = cv2.cvtColor(cv2.imread(self.imgs[i]), cv2.COLOR_BGR2RGB)
        msk = cv2.imread(self.msks[i], cv2.IMREAD_GRAYSCALE)
        out = self.tf(image=img, mask=msk)
        return out["image"], out["mask"].long()

split = int(len(images) * 0.8)
train_ds = CorrosionDataset(images[:split], masks[:split], train_tf)
valid_ds = CorrosionDataset(images[split:], masks[split:], valid_tf)
atlas.log("train:", len(train_ds), "valid:", len(valid_ds))"""),
        _md("## 3. U-Net + ResNet34 encoder"),
        _code("""import segmentation_models_pytorch as smp

model = smp.Unet("resnet34", encoder_weights="imagenet", in_channels=3, classes=NUM_CLASSES).to(device)
loss_fn = smp.losses.DiceLoss(mode="multiclass")
opt = torch.optim.AdamW(model.parameters(), lr=3e-4)
atlas.log("U-Net ready:", sum(p.numel() for p in model.parameters()) // 1000, "K params")"""),
        _code("""EPOCHS = 25
if len(train_ds) == 0:
    atlas.log("No data - attach a dataset and re-run.")
else:
    tl = DataLoader(train_ds, batch_size=4, shuffle=True, num_workers=2)
    vl = DataLoader(valid_ds, batch_size=4, num_workers=2)
    for epoch in range(EPOCHS):
        model.train(); total = 0.0
        for x, y in tl:
            x, y = x.to(device), y.to(device)
            opt.zero_grad(); loss = loss_fn(model(x), y); loss.backward(); opt.step()
            total += loss.item()
        model.eval(); inter = torch.zeros(NUM_CLASSES); union = torch.zeros(NUM_CLASSES)
        with torch.no_grad():
            for x, y in vl:
                p = model(x.to(device)).argmax(1).cpu()
                for c in range(NUM_CLASSES):
                    pi, gi = (p == c), (y == c)
                    inter[c] += (pi & gi).sum(); union[c] += (pi | gi).sum()
        iou = (inter / union.clamp(min=1))
        atlas.metric(epoch=epoch + 1, train_loss=round(total / max(len(tl), 1), 4),
                     mean_iou=round(float(iou.mean()), 4))
        atlas.log(f"epoch {epoch+1}/{EPOCHS} mIoU={iou.mean():.4f}")"""),
        _code("""torch.save(model.state_dict(), "corrosion_unet.pt")
atlas.artifact("corrosion_unet.pt")
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

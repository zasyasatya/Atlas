"""Corrosion Type Segmentation - deployment app.

What an inspector actually gets: upload a photograph, see which pixels are
corroded, which of the fifteen classes each patch is, and how confident the
model is about it.

Built to satisfy the ATLAS graduation rubric:

  R1  Streamlit                                     - this file
  R2  Single image AND bulk upload                  - Analyse tab
  R3  Documentation: limitations, dataset, architecture, evaluation
  R4  Confidence score on every prediction, plus charts
  R5  Whimsical URL shown in the sidebar

Run it:
    pip install -r requirements.txt
    streamlit run app.py

The model comes from `best.pt`, written by the training notebook. The app never
imports the training stack - only `corrosion_kit.Predictor` - so it starts
without the dataset present.
"""
from __future__ import annotations

import io
import json
import os
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image

from corrosion_kit import PALETTE, Predictor, is_background

HERE = Path(__file__).parent
st.set_page_config(page_title="Corrosion Segmentation", page_icon="🛢", layout="wide")

WHIMSICAL_URL = os.environ.get("WHIMSICAL_URL", "https://whimsical.com/atlas-corrosion-segmentation")
MAX_BULK = 40


def find_checkpoint() -> Path | None:
    """Find the weights wherever the bundle happens to put them.

    People lay a deployment zip out differently - `best.pt` beside app.py,
    `model/best.pt`, `runs/<name>/best.pt`. Hard-coding one path is the most
    common way a finished submission shows "no checkpoint" and looks broken.
    """
    explicit = os.environ.get("CORROSION_CHECKPOINT", "")
    if explicit and Path(explicit).exists():
        return Path(explicit)
    candidates: list[Path] = []
    for pattern in ("*.pt", "model/*.pt", "models/*.pt", "checkpoints/*.pt",
                    "weights/*.pt", "runs/*/*.pt", "artifacts/*.pt"):
        candidates.extend(HERE.glob(pattern))
    if not candidates:
        return None
    named = [c for c in candidates if c.name == "best.pt"]
    return max(named or candidates, key=lambda p: p.stat().st_mtime)


@st.cache_resource(show_spinner="Loading the model...")
def get_predictor(path: str, mtime: float):
    return Predictor(path, device="cpu")


@st.cache_data
def get_report() -> dict:
    for name in ("report.json", "runs/report.json"):
        path = HERE / name
        if path.exists():
            return json.loads(path.read_text())
    return {}


@st.cache_data
def get_history() -> pd.DataFrame:
    for name in ("history.csv", "runs/history.csv"):
        path = HERE / name
        if path.exists():
            return pd.read_csv(path)
    return pd.DataFrame()


def severity_of(name: str) -> str:
    tail = name.rsplit("_", 1)[-1]
    return tail if tail in ("mild", "moderate", "severe") else "-"


def family_of(name: str) -> str:
    return name.split("_")[0] if not is_background(name) else "background"


def prediction_table(pred, class_names: list[str]) -> pd.DataFrame:
    rows = []
    for row in pred.rows(0.0):
        if row["pixels"] == 0 or is_background(row["class"]):
            continue
        idx = class_names.index(row["class"])
        conf = float(pred.confidence[pred.mask == idx].mean()) if row["pixels"] else 0.0
        rows.append({
            "class": row["class"],
            "family": family_of(row["class"]),
            "severity": severity_of(row["class"]),
            "area_percent": row["share_percent"],
            "confidence": round(conf, 4),
        })
    return pd.DataFrame(rows).sort_values("area_percent", ascending=False) if rows else pd.DataFrame()


# --------------------------------------------------------------------------
# sidebar
# --------------------------------------------------------------------------
st.sidebar.title("Corrosion Segmentation")
st.sidebar.caption("U-Net · semantic segmentation · 15 corrosion classes")

checkpoint = find_checkpoint()
predictor = None
if checkpoint is None:
    st.sidebar.error("No checkpoint (.pt) found in this bundle.")
    st.sidebar.code("python train.py --data <dataset> --run-dir runs/corrosion", language="bash")
else:
    predictor = get_predictor(str(checkpoint), checkpoint.stat().st_mtime)
    meta = predictor.metadata()
    st.sidebar.success("Model loaded: %s" % checkpoint.name)
    st.sidebar.metric("Validation mean IoU",
                      "%.4f" % meta["validation_mean_iou"] if meta.get("validation_mean_iou") else "n/a")
    st.sidebar.write("**Classes:** %d  \n**Input size:** %dpx  \n**Parameters:** %s"
                     % (meta["classes"], meta["image_size"], format(meta["parameters"], ",")))

alpha = st.sidebar.slider("Overlay strength", 0.1, 0.9, 0.5, 0.05)
min_area = st.sidebar.slider("Hide classes below this area share (%)", 0.0, 5.0, 0.1, 0.1)
st.sidebar.markdown("---")
st.sidebar.markdown("**Whimsical board**  \n[%s](%s)" % (WHIMSICAL_URL, WHIMSICAL_URL))
st.sidebar.caption("R5: the deployed URL is attached to this board for review.")

st.title("Corrosion Type Segmentation")
st.caption("Upload an inspection photograph. The model labels every pixel with one of "
           "15 corrosion classes - five families at three severities - and reports its confidence.")

analyse_tab, bulk_tab, docs_tab = st.tabs(["Single image", "Bulk upload", "Documentation"])

# --------------------------------------------------------------------------
# single image
# --------------------------------------------------------------------------
with analyse_tab:
    col_in, col_opt = st.columns([2, 1])
    with col_in:
        uploaded = st.file_uploader("Inspection photograph", type=["jpg", "jpeg", "png", "bmp"],
                                    key="single")
    with col_opt:
        asset = st.selectbox("Or use a bundled example",
                             ["(none)"] + sorted(p.name for p in (HERE / "examples").glob("*"))
                             if (HERE / "examples").is_dir() else ["(none)"])
        equipment = st.text_input("Equipment tag (optional)", placeholder="P-101-A")

    image = None
    if uploaded is not None:
        image = Image.open(uploaded).convert("RGB")
    elif asset and asset != "(none)":
        image = Image.open(HERE / "examples" / asset).convert("RGB")

    if image is None:
        st.info("Upload a photograph to run the model.")
    elif predictor is None:
        st.error("No model checkpoint in this deployment - nothing to run.")
    else:
        started = time.time()
        pred = predictor.predict(image)
        elapsed = time.time() - started

        left, mid, right = st.columns(3)
        left.image(image, caption="Input", use_container_width=True)
        mid.image(predictor.colorise(pred.mask), caption="Predicted classes",
                  use_container_width=True)
        right.image(predictor.overlay(image, pred.mask, alpha), caption="Overlay",
                    use_container_width=True)

        corroded = float((pred.mask > 0).mean())
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Dominant class", pred.dominant)
        m2.metric("Confidence (dominant)", "%.1f%%" % (pred.dominant_confidence * 100))
        m3.metric("Mean confidence", "%.1f%%" % (pred.mean_confidence * 100))
        m4.metric("Corroded area", "%.1f%%" % (corroded * 100))
        st.caption("Inference took %.2f s on CPU%s."
                   % (elapsed, " · %s" % equipment if equipment else ""))

        table = prediction_table(pred, predictor.class_names)
        if not table.empty:
            table = table[table["area_percent"] >= min_area]
        if table.empty:
            st.success("No corrosion above the area threshold - the surface reads as clean.")
        else:
            st.subheader("Detected classes")
            st.dataframe(table, use_container_width=True, hide_index=True)
            chart = table.set_index("class")[["area_percent"]]
            st.bar_chart(chart, height=260)
            st.caption("Area share per class. Confidence is the mean softmax probability "
                       "over the pixels assigned to that class.")

            st.subheader("Confidence map")
            conf_img = (np.clip(pred.confidence, 0, 1) * 255).astype(np.uint8)
            st.image(Image.fromarray(conf_img), use_container_width=True,
                     caption="Bright = confident. Dark bands sit on class boundaries, "
                             "which is where the model is genuinely unsure.")

            buffer = io.BytesIO()
            predictor.overlay(image, pred.mask, alpha).save(buffer, format="PNG")
            st.download_button("Download overlay (PNG)", buffer.getvalue(),
                               file_name="corrosion_overlay.png", mime="image/png")
            st.download_button("Download result (JSON)",
                               json.dumps(pred.to_dict(), indent=2),
                               file_name="corrosion_result.json", mime="application/json")

# --------------------------------------------------------------------------
# bulk
# --------------------------------------------------------------------------
with bulk_tab:
    st.write("Run a whole inspection round at once. Upload up to %d photographs, or a "
             "single .zip of them, and get one row per image plus a CSV to hand on." % MAX_BULK)
    many = st.file_uploader("Photographs or a .zip", type=["jpg", "jpeg", "png", "bmp", "zip"],
                            accept_multiple_files=True, key="bulk")

    if many and predictor is not None:
        items: list[tuple[str, Image.Image]] = []
        for upload in many:
            if upload.name.lower().endswith(".zip"):
                with zipfile.ZipFile(upload) as zf:
                    for member in zf.namelist()[: MAX_BULK * 2]:
                        if member.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")):
                            items.append((member, Image.open(io.BytesIO(zf.read(member))).convert("RGB")))
            else:
                items.append((upload.name, Image.open(upload).convert("RGB")))
        items = items[:MAX_BULK]

        rows = []
        progress = st.progress(0.0, text="Segmenting %d images..." % len(items))
        for i, (name, img) in enumerate(items, start=1):
            pred = predictor.predict(img)
            rows.append({
                "image": name,
                "dominant_class": pred.dominant,
                "family": family_of(pred.dominant) if pred.dominant != "none detected" else "-",
                "severity": severity_of(pred.dominant),
                "confidence": round(pred.dominant_confidence, 4),
                "mean_confidence": round(pred.mean_confidence, 4),
                "corroded_area_percent": round(float((pred.mask > 0).mean()) * 100, 2),
            })
            progress.progress(i / len(items), text="Segmented %d/%d" % (i, len(items)))
        progress.empty()

        frame = pd.DataFrame(rows)
        st.dataframe(frame, use_container_width=True, hide_index=True)

        st.subheader("Findings across the batch")
        left, right = st.columns(2)
        left.bar_chart(frame["dominant_class"].value_counts(), height=280)
        left.caption("How many photographs each class dominates.")
        right.bar_chart(frame.set_index("image")[["corroded_area_percent"]], height=280)
        right.caption("Corroded area per photograph, worst first is where to send a technician.")

        review = frame[frame["confidence"] < 0.6]
        if not review.empty:
            st.warning("%d image(s) came back under 60%% confidence. Those need a human look "
                       "before anything is scheduled." % len(review))

        st.download_button("Download results (CSV)", frame.to_csv(index=False),
                           file_name="corrosion_batch_results.csv", mime="text/csv")
    elif many:
        st.error("No model checkpoint in this deployment - nothing to run.")

# --------------------------------------------------------------------------
# documentation
# --------------------------------------------------------------------------
with docs_tab:
    report = get_report()
    history = get_history()

    st.header("Documentation")

    st.subheader("1. Dataset")
    st.markdown(
        """
The CorroVision semantic export: **3,129 annotated inspection photographs**
(2,498 train / 307 validation / 324 test). Every photograph has a mask PNG where
the pixel value *is* the class index.

**15 classes** - five corrosion families at three severities each:

| Family | Signature | Why it matters |
|---|---|---|
| `general` | Even rust over a broad area | Predictable metal loss, easiest to plan for |
| `pitting` | Small deep holes | Dangerous: a pinhole can hide deep penetration |
| `crevice` | Concentrated in gaps, under bolts and flanges | Hidden by geometry, found late |
| `galvanic` | At the join between two different metals | A design fault, not just wear |
| `preferential_weld_attack` | Follows the weld line | Attacks the seam holding it together |

Index 0 is background and takes roughly **74% of all pixels**, so the sixteenth
output channel exists for "no corrosion here".
        """
    )

    st.subheader("2. Model architecture")
    st.markdown(
        """
A **U-Net** trained from scratch. An encoder halves the resolution and doubles
the channels four times over; a decoder brings it back to full size; skip
connections hand the encoder's sharp early feature maps across to the decoder.

Those skips are the whole trick. Downsampling answers *what is in this image*
and throws away *exactly where*; without the skips the decoder has to
reconstruct a boundary from a blurry summary and produces vague blobs. For a
weld-line attack a few pixels wide, that is the difference between a usable
prediction and a smear.

The loss is **0.5 x class-weighted cross-entropy + 0.5 x Dice**. Cross-entropy
alone optimises average per-pixel correctness, and with 74% background the
cheapest way to improve that average is to predict background everywhere. Class
weights are damped (square root, spread clamped to 8:1) because raw
median-frequency balancing overcorrects and paints corrosion across the frame.
        """
    )
    if predictor is not None:
        st.json(predictor.metadata(), expanded=False)

    st.subheader("3. Evaluation")
    st.markdown(
        """
Scored with **IoU per class** on the held-out test split, never pixel accuracy:
a model that predicts background everywhere scores over 70% accuracy and is
useless, while its IoU on every corrosion class is 0. Mean Dice is reported
alongside because it is more forgiving on small regions.
        """
    )
    if report:
        per_class = report.get("per_class_iou", {})
        support = report.get("support", {})
        frame = pd.DataFrame(
            [{"class": k, "IoU": round(v, 4),
              "dice": round(report.get("per_class_dice", {}).get(k, 0.0), 4),
              "test_pixels": support.get(k, 0)}
             for k, v in per_class.items()]
        ).sort_values("test_pixels", ascending=False)
        c1, c2, c3 = st.columns(3)
        c1.metric("Test mean IoU", "%.4f" % report.get("mean_iou", 0))
        c2.metric("Test mean Dice", "%.4f" % report.get("mean_dice", 0))
        # The notebooks call it pixel_acc, the CLI trainer pixel_accuracy. Both
        # produce valid reports, so read either rather than showing 0.0000.
        c3.metric("Pixel accuracy",
                  "%.4f" % report.get("pixel_acc", report.get("pixel_accuracy", 0)))
        st.dataframe(frame, use_container_width=True, hide_index=True)
        st.bar_chart(frame.set_index("class")[["IoU"]], height=300)
    else:
        st.info("No report.json in the bundle - run the evaluation notebook and include it.")

    if not history.empty:
        st.markdown("**Training history**")
        cols = [c for c in ("train_loss", "val_loss", "val_mean_iou") if c in history.columns]
        st.line_chart(history.set_index("epoch")[cols], height=280)

    st.subheader("4. Limitations")
    st.markdown(
        """
- **Severity is the weak axis.** Telling `pitting` from `crevice` is far easier
  than telling `moderate` from `severe`; severity is partly a judgement call and
  the model inherits the annotators' disagreement. Treat a severity label as a
  prompt for inspection, not a verdict.
- **Not a thickness measurement.** The model sees surface appearance. It cannot
  tell you remaining wall thickness, and a small confident pit may still be a
  through-wall defect. Ultrasonic testing decides that, not this app.
- **Out of scope:** underwater photographs, thermal or radiographic images,
  heavily motion-blurred frames, and coatings or paints that mimic rust colour.
- **Lighting and scale matter.** Training photographs were taken close up in
  daylight or work lighting. A distant shot of a whole vessel will under-detect.
- **Confidence is softmax, not calibrated probability.** A 90% reading means the
  network preferred that class strongly, not that it is right nine times in ten.
  Anything under 60% is flagged for a human in the bulk tab for that reason.
- **A prediction is a second opinion.** Repair decisions stay with a qualified
  inspector.
        """
    )

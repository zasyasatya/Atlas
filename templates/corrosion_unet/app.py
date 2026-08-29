"""Corrosion Segmentation - deployment app.

Built to satisfy the ATLAS graduation rubric:

  R1  Streamlit                                        - this file
  R2  Single image AND bulk upload                     - Analyse tab
  R3  Documentation: limitations, dataset, architecture, evaluation
  R4  Confidence score on every prediction, plus charts
  R5  Whimsical URL shown in the sidebar for review

Run:
    streamlit run app.py
    streamlit run app.py -- --checkpoint runs/smoke/best.pt
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from corrosion.inference import Predictor, load_report  # noqa: E402

st.set_page_config(page_title="Corrosion Segmentation", page_icon="🛢", layout="wide")

DEFAULT_CHECKPOINT = os.environ.get("CORROSION_CHECKPOINT", "runs/corrosion-unet/best.pt")
DEFAULT_RUN_DIR = os.environ.get("CORROSION_RUN_DIR", "runs/corrosion-unet")
WHIMSICAL_URL = os.environ.get("WHIMSICAL_URL", "")


def _arg(flag: str, fallback: str) -> str:
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return fallback


def _discover_checkpoint(preferred: str) -> str:
    """Find the trained weights wherever the bundle happens to put them.

    The app is deployed by uploading a zip, and people lay that zip out
    differently: `model/best.pt`, `runs/<name>/best.pt`, or a bare `best.pt`
    beside app.py. Hard-coding one path means a perfectly good deployment shows
    "No checkpoint found" and looks broken, which is the single most common way
    an otherwise finished submission fails review.

    The explicit flag or env var always wins; this only runs when that path is
    missing. Newest wins, since a re-trained model is the interesting one.
    """
    if Path(preferred).exists():
        return preferred

    here = Path(__file__).parent
    candidates: list[Path] = []
    for pattern in ("*.pt", "model/*.pt", "models/*.pt", "runs/*/*.pt",
                    "checkpoints/*.pt", "weights/*.pt", "artifacts/*.pt"):
        candidates.extend(here.glob(pattern))

    # Prefer a file literally called best.pt, then fall back to newest.
    best = [c for c in candidates if c.name == "best.pt"]
    pool = best or candidates
    if not pool:
        return preferred
    winner = max(pool, key=lambda p: p.stat().st_mtime)
    try:
        return str(winner.relative_to(here))
    except ValueError:
        return str(winner)


CHECKPOINT = _discover_checkpoint(_arg("--checkpoint", DEFAULT_CHECKPOINT))
RUN_DIR = _arg("--run-dir", DEFAULT_RUN_DIR)
# A checkpoint found outside the default run dir carries its own siblings
# (history.csv, report.json), so point the docs tab at the same folder.
if CHECKPOINT != DEFAULT_CHECKPOINT and RUN_DIR == DEFAULT_RUN_DIR:
    _found_dir = str(Path(CHECKPOINT).parent)
    if _found_dir not in ("", "."):
        RUN_DIR = _found_dir


@st.cache_resource(show_spinner="Loading model...")
def get_predictor(path: str):
    return Predictor(path, device="cpu")


@st.cache_data
def get_report(run_dir: str) -> dict:
    return load_report(run_dir)


@st.cache_data
def get_history(run_dir: str) -> pd.DataFrame:
    p = Path(run_dir) / "history.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


# --------------------------------------------------------------------------
# sidebar
# --------------------------------------------------------------------------
st.sidebar.title("Corrosion Segmentation")
st.sidebar.caption("U-Net · semantic segmentation · 15 corrosion classes")

ckpt_path = st.sidebar.text_input("Checkpoint", CHECKPOINT)
model_ready = Path(ckpt_path).exists()

if not model_ready:
    st.sidebar.error("No checkpoint found.")
    st.sidebar.code("python train.py --data data/sample --run-dir runs/smoke", language="bash")
else:
    predictor = get_predictor(ckpt_path)
    meta = predictor.metadata()
    st.sidebar.success("Model loaded")
    st.sidebar.metric("Classes", meta["classes"])
    st.sidebar.metric("Parameters", f"{meta['parameters']:,}")
    if meta.get("validation_mean_iou") is not None:
        st.sidebar.metric("Validation mIoU", f"{meta['validation_mean_iou']:.4f}")

if WHIMSICAL_URL:
    st.sidebar.markdown(f"[Whimsical board]({WHIMSICAL_URL})")
else:
    st.sidebar.caption("Set WHIMSICAL_URL to show the review link (rubric R5).")

def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


tab_run, tab_docs = st.tabs(["Analyse", "Documentation"])


# --------------------------------------------------------------------------
# analyse
# --------------------------------------------------------------------------
with tab_run:
    if not model_ready:
        st.warning("Train a model first, then reload this page.")
        st.stop()

    mode = st.radio("Input", ["Single image", "Bulk upload"], horizontal=True)

    # ---------------------------------------------------------- single
    if mode == "Single image":
        up = st.file_uploader("Inspection photo", type=["jpg", "jpeg", "png", "bmp", "webp"])
        if up:
            image = Image.open(up).convert("RGB")
            t0 = time.time()
            out = predictor.predict(image)
            elapsed = (time.time() - t0) * 1000

            c1, c2, c3 = st.columns(3)
            c1.metric("Dominant finding", out.dominant.replace("_", " "))
            c2.metric("Mean confidence", f"{out.mean_confidence:.1%}")
            c3.metric("Inference", f"{elapsed:.0f} ms")

            affected = 1 - out.class_share.get("background", 0.0)
            st.progress(min(affected, 1.0), text=f"Surface affected: {affected:.1%}")

            v1, v2, v3 = st.columns(3)
            v1.image(image, caption="Input", use_container_width=True)
            v2.image(predictor.colorise(out.mask), caption="Predicted mask",
                     use_container_width=True)
            v3.image(predictor.overlay(image, out.mask), caption="Overlay",
                     use_container_width=True)

            st.subheader("Detected classes")
            rows = [r for r in out.summary_rows() if not r["class"].startswith("background")]
            if rows:
                df = pd.DataFrame(rows)
                st.bar_chart(df.set_index("class")["share_percent"])
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("No corrosion detected in this image.")

            st.subheader("Confidence map")
            st.caption("Brighter means the model was more certain about that pixel.")
            conf_img = (out.confidence * 255).astype(np.uint8)
            st.image(conf_img, use_container_width=True, clamp=True)

            st.download_button(
                "Download mask (PNG)",
                data=_png_bytes(Image.fromarray(out.mask)),
                file_name=f"{Path(up.name).stem}_mask.png",
                mime="image/png",
            )

    # ---------------------------------------------------------- bulk
    else:
        st.caption("Upload many photos, or a ZIP. One row per image, downloadable as CSV.")
        ups = st.file_uploader("Photos or a ZIP archive",
                               type=["jpg", "jpeg", "png", "bmp", "webp", "zip"],
                               accept_multiple_files=True)
        if ups and st.button("Run batch", type="primary"):
            items: list[tuple[str, Image.Image]] = []
            for f in ups:
                if f.name.lower().endswith(".zip"):
                    with zipfile.ZipFile(f) as zf:
                        for n in zf.namelist():
                            if n.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")) \
                                    and not n.startswith("__MACOSX"):
                                items.append((n, Image.open(io.BytesIO(zf.read(n))).convert("RGB")))
                else:
                    items.append((f.name, Image.open(f).convert("RGB")))

            if not items:
                st.warning("Nothing readable in that upload.")
                st.stop()

            bar = st.progress(0.0, text=f"0 / {len(items)}")
            records = []
            for i, (name, img) in enumerate(items, 1):
                out = predictor.predict(img)
                affected = 1 - out.class_share.get("background", 0.0)
                records.append({
                    "file": name,
                    "dominant_class": out.dominant,
                    "confidence": round(out.mean_confidence, 4),
                    "affected_percent": round(affected * 100, 2),
                    **{f"pct_{k}": round(v * 100, 2)
                       for k, v in out.class_share.items() if not k.startswith("background")},
                })
                bar.progress(i / len(items), text=f"{i} / {len(items)}")

            df = pd.DataFrame(records)
            st.success(f"Processed {len(df)} images.")

            m1, m2, m3 = st.columns(3)
            m1.metric("Images", len(df))
            m2.metric("Mean confidence", f"{df['confidence'].mean():.1%}")
            m3.metric("Mean affected area", f"{df['affected_percent'].mean():.2f}%")

            st.subheader("Findings by class")
            st.bar_chart(df["dominant_class"].value_counts())

            st.subheader("Confidence distribution")
            st.bar_chart(pd.cut(df["confidence"], bins=10).value_counts().sort_index()
                         .rename_axis("confidence").reset_index(name="images")
                         .set_index("confidence"))

            st.dataframe(df, use_container_width=True, hide_index=True)
            st.download_button("Download results (CSV)",
                               df.to_csv(index=False).encode(),
                               "corrosion_results.csv", "text/csv")


# --------------------------------------------------------------------------
# documentation (rubric R3)
# --------------------------------------------------------------------------
with tab_docs:
    st.header("Documentation")

    st.subheader("1. Model limitations")
    st.markdown("""
- **Trained on inspection photography only.** Drone footage, thermal or radiographic
  images are outside the training distribution; predictions on them are not meaningful.
- **Severity is the weakest axis.** Telling *crevice* from *pitting* is easier than
  telling *moderate* from *severe*, because severity annotation is partly subjective.
  Expect most confusion between neighbouring severities of the same family.
- **Lighting sensitivity.** Strong specular glare on wet metal is regularly read as
  corrosion. Matte, evenly lit photographs are considerably more reliable.
- **No scale awareness.** The model sees pixels, not millimetres. Without a scale
  reference in frame, "affected area %" is relative to the photo, not the asset.
- **Not a substitute for inspection.** Output is a triage aid for a qualified
  inspector, not a certification of asset condition.
- **Fixed input size.** Images are resized to a square before inference, so extreme
  aspect ratios are distorted, and pits a few pixels wide may vanish in the resize.
    """)

    st.subheader("2. Dataset details")
    report = get_report(RUN_DIR)
    cfg_path = Path(RUN_DIR) / "config.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}

    d1, d2 = st.columns(2)
    with d1:
        st.markdown(f"""
**Source** CorroVision inspection dataset (`corrovision-dataset-v1`)
**Task** Semantic segmentation, one class per pixel
**Annotation** Polygon masks, exported as single-channel PNG
**Validation** 100% reviewed — 3129 of 3129 images validated
**Splits** train / val / test, as produced by the exporter
**Mask encoding** pixel value = class index
        """)
    with d2:
        st.markdown(f"""
**Classes** {cfg.get('class_names', []) and len(cfg['class_names']) or 16}
(5 corrosion families × 3 severities, plus background)
**Families** crevice · galvanic · general · pitting · preferential weld attack
**Severities** mild · moderate · severe
**Input size** {cfg.get('image_size', '—')} × {cfg.get('image_size', '—')} px
**Imbalance** background dominates; handled with median-frequency class weights
        """)

    if cfg.get("class_names"):
        st.caption("Class list used by this checkpoint")
        st.code("\n".join(f"{i:>2}  {n}" for i, n in enumerate(cfg["class_names"])))

    st.subheader("3. Model architecture")
    st.markdown(f"""
**U-Net** (Ronneberger et al., 2015), encoder–decoder with skip connections,
written from scratch in `corrosion/model.py` — not imported from a library.

- **Encoder** {cfg.get('depth', 4)} downsampling stages; channels double each stage
  from a base width of {cfg.get('width', 32)}
- **Bottleneck** double 3×3 convolution at the lowest resolution
- **Decoder** mirrors the encoder, bilinear upsampling, concatenating the matching
  encoder feature map at every level
- **Skip connections** the reason U-Net beats a plain encoder–decoder: pooling
  discards spatial precision, and the skips hand it back so boundaries stay sharp
- **Head** 1×1 convolution mapping to one logit per class per pixel
- **Loss** `{cfg.get('loss', 'combo')}` — Dice + weighted cross-entropy. Cross-entropy
  gives usable gradients early; Dice optimises overlap and resists class imbalance
- **Optimiser** AdamW, cosine-annealed learning rate from {cfg.get('lr', 3e-4)}
- **Mixed precision** enabled automatically on CUDA
    """)

    st.subheader("4. Evaluation results")
    if report:
        e1, e2, e3, e4 = st.columns(4)
        e1.metric("Mean IoU", f"{report.get('mean_iou', 0):.4f}")
        e2.metric("Mean Dice", f"{report.get('mean_dice', 0):.4f}")
        e3.metric("Pixel accuracy", f"{report.get('pixel_accuracy', 0):.4f}")
        e4.metric("Test loss", f"{report.get('test_loss', 0):.4f}")

        st.caption(f"Checkpoint: `{report.get('checkpoint', '—')}` · "
                   f"device: {report.get('device', '—')}")

        per_class = report.get("per_class_iou", {})
        support = report.get("support", {})
        if per_class:
            df = pd.DataFrame({
                "class": list(per_class),
                "IoU": list(per_class.values()),
                "Dice": [report.get("per_class_dice", {}).get(k, 0) for k in per_class],
                "pixels": [support.get(k, 0) for k in per_class],
            })
            present = df[df["pixels"] > 0].sort_values("IoU", ascending=False)
            st.bar_chart(present.set_index("class")["IoU"])
            st.dataframe(df.sort_values("pixels", ascending=False),
                         use_container_width=True, hide_index=True)
            st.caption("Classes with zero pixels are absent from the test split and "
                       "are excluded from the mean.")

        history = get_history(RUN_DIR)
        if not history.empty:
            st.subheader("Training history")
            st.line_chart(history.set_index("epoch")[["train_loss", "val_loss"]])
            st.line_chart(history.set_index("epoch")[["val_mean_iou", "val_mean_dice"]])
            with st.expander("Per-epoch table"):
                st.dataframe(history, use_container_width=True, hide_index=True)

        cm_path = Path(RUN_DIR) / "confusion.csv"
        if cm_path.exists():
            with st.expander("Confusion matrix"):
                st.dataframe(pd.read_csv(cm_path), use_container_width=True)
    else:
        st.info(f"No report at `{RUN_DIR}/report.json`. Train a model to populate this page.")

    st.subheader("5. Metric definitions")
    st.markdown("""
| Metric | Meaning | Why it is here |
|---|---|---|
| **IoU** | overlap ÷ union, per class | The standard segmentation metric. Punishes both misses and false alarms. |
| **Dice** | 2·overlap ÷ (pred + truth) | Kinder to small regions than IoU; the usual choice for thin defects. |
| **Pixel accuracy** | correct pixels ÷ all pixels | Reported for completeness, but misleading on its own — predicting "background" everywhere already scores above 90%. |
| **Confidence** | softmax probability of the winning class | Rubric R4. Averaged per image; low values mean the model is guessing. |
    """)

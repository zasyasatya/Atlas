"""Loading a trained model and running it on new images.

This is the bridge between training and deployment. The Streamlit app imports
`Predictor` and nothing else from the training stack, so the deployed app never
depends on the dataset being present.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from .dataset import MEAN, STD
from .model import UNet

# Distinct colours for overlays. Grouped so the five corrosion families read as
# related hues and severity varies within a family.
PALETTE = [
    (0, 0, 0),           # background
    (255, 179, 179), (255, 102, 102), (204, 0, 0),          # crevice
    (255, 224, 178), (255, 183, 77), (230, 126, 34),        # galvanic
    (200, 230, 201), (102, 187, 106), (27, 120, 55),        # general
    (187, 222, 251), (66, 165, 245), (21, 76, 168),         # pitting
    (225, 190, 231), (186, 104, 200), (123, 31, 162),       # preferential weld
    (200, 200, 200),
]


@dataclass
class Prediction:
    """One image's result."""
    mask: np.ndarray                  # (H, W) class indices
    confidence: np.ndarray            # (H, W) softmax probability of the winner
    class_pixels: dict[str, int]
    class_share: dict[str, float]
    mean_confidence: float
    dominant: str
    image_size: tuple[int, int]

    def summary_rows(self, min_share: float = 0.0) -> list[dict]:
        rows = [
            {"class": name,
             "pixels": self.class_pixels[name],
             "share_percent": round(self.class_share[name] * 100, 2)}
            for name in self.class_pixels
            if self.class_share[name] > min_share
        ]
        return sorted(rows, key=lambda r: -r["pixels"])


class Predictor:
    """Loads a checkpoint and segments images.

    The checkpoint carries its own class names and architecture settings, so the
    app does not need to be told how the model was built.
    """

    def __init__(self, checkpoint: str | Path, device: str | None = None):
        self.checkpoint_path = Path(checkpoint)
        if not self.checkpoint_path.exists():
            raise FileNotFoundError(f"no checkpoint at {self.checkpoint_path}")

        self.device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu"))
        state = torch.load(self.checkpoint_path, map_location=self.device, weights_only=False)

        self.class_names: list[str] = state.get("class_names") or []
        cfg = state.get("config", {}) or {}
        self.image_size = int(cfg.get("image_size", 256))

        num_classes = len(self.class_names)
        if not num_classes:
            # Fall back to the output layer's shape if names are missing.
            out_w = [v for k, v in state["model"].items() if k.endswith("outc.weight")]
            num_classes = out_w[0].shape[0] if out_w else 16
            self.class_names = [f"class_{i}" for i in range(num_classes)]

        self.model = UNet(
            num_classes=num_classes,
            width=int(cfg.get("width", 32)),
            depth=int(cfg.get("depth", 4)),
        )
        self.model.load_state_dict(state["model"])
        self.model.to(self.device).eval()

        self.trained_epoch = state.get("epoch")
        self.trained_iou = state.get("mean_iou")

    # ---------------------------------------------------------------- predict
    @torch.no_grad()
    def predict(self, image: Image.Image | str | Path | np.ndarray) -> Prediction:
        img = _as_pil(image)
        original = img.size  # (W, H)

        small = img.resize((self.image_size, self.image_size), Image.BILINEAR)
        arr = np.asarray(small, dtype=np.float32) / 255.0
        arr = (arr - MEAN) / STD
        x = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0).float().to(self.device)

        probs = torch.softmax(self.model(x), dim=1)[0]
        conf, mask = probs.max(dim=0)

        mask_np = mask.cpu().numpy().astype(np.uint8)
        conf_np = conf.cpu().numpy().astype(np.float32)

        # Back to the caller's resolution so overlays line up with their image.
        mask_np = np.asarray(
            Image.fromarray(mask_np).resize(original, Image.NEAREST))
        conf_np = np.asarray(
            Image.fromarray(conf_np, mode="F").resize(original, Image.BILINEAR))

        total = mask_np.size
        pixels, share = {}, {}
        for i, name in enumerate(self.class_names):
            n = int((mask_np == i).sum())
            pixels[name] = n
            share[name] = n / total

        # "Dominant" ignores background - the useful answer is which defect wins.
        ranked = sorted(
            ((n, name) for name, n in pixels.items() if not _is_background(name)),
            reverse=True,
        )
        dominant = ranked[0][1] if ranked and ranked[0][0] > 0 else "none detected"

        return Prediction(
            mask=mask_np,
            confidence=conf_np,
            class_pixels=pixels,
            class_share=share,
            mean_confidence=float(conf_np.mean()),
            dominant=dominant,
            image_size=original,
        )

    def predict_batch(self, images: list) -> list[Prediction]:
        return [self.predict(im) for im in images]

    # ---------------------------------------------------------------- render
    def colorise(self, mask: np.ndarray) -> Image.Image:
        rgb = np.zeros((*mask.shape, 3), dtype=np.uint8)
        for i in range(len(self.class_names)):
            rgb[mask == i] = PALETTE[i % len(PALETTE)]
        return Image.fromarray(rgb)

    def overlay(self, image, mask: np.ndarray, alpha: float = 0.5) -> Image.Image:
        base = _as_pil(image).convert("RGB")
        colour = self.colorise(mask).resize(base.size, Image.NEAREST)

        base_a = np.asarray(base, dtype=np.float32)
        col_a = np.asarray(colour, dtype=np.float32)
        # Leave background pixels untouched so the photo stays readable.
        keep = (np.asarray(Image.fromarray(mask).resize(base.size, Image.NEAREST)) == 0)
        blended = base_a * (1 - alpha) + col_a * alpha
        blended[keep] = base_a[keep]
        return Image.fromarray(blended.astype(np.uint8))

    def legend(self) -> list[dict]:
        return [
            {"index": i, "name": n, "color": "#%02x%02x%02x" % PALETTE[i % len(PALETTE)]}
            for i, n in enumerate(self.class_names)
        ]

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


def _as_pil(image) -> Image.Image:
    if isinstance(image, Image.Image):
        return image.convert("RGB")
    if isinstance(image, (str, Path)):
        return Image.open(image).convert("RGB")
    if isinstance(image, np.ndarray):
        arr = image
        if arr.dtype != np.uint8:
            arr = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
        return Image.fromarray(arr).convert("RGB")
    raise TypeError(f"cannot read an image from {type(image)}")


def _is_background(name: str) -> bool:
    return name.strip().lower() in {"background", "bg", "none", "unlabeled", "unlabelled"}


def load_report(run_dir: str | Path) -> dict:
    """Read report.json from a run directory, for the app's evaluation page."""
    path = Path(run_dir) / "report.json"
    return json.loads(path.read_text()) if path.exists() else {}

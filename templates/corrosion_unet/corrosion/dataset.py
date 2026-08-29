"""Torch Dataset and augmentation for corrosion masks.

Augmentation here is deliberately conservative. Corrosion classes are separated
by *texture and severity*, so anything that rewrites local texture — heavy blur,
elastic warping, aggressive noise — can turn a "mild" example into something a
human would label "moderate". Flips and mild photometric jitter are safe: they
model camera angle and lighting, which genuinely vary between inspections.

Masks are resized with NEAREST. Any smoothing interpolation would invent class
indices that do not exist (halfway between class 3 and class 4 is not a class).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset

# ImageNet statistics - the encoder weights, if pretrained, expect this scaling.
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class Augment:
    """Light augmentation. Set train=False for validation and test."""

    def __init__(self, size: int = 256, train: bool = True, seed: int | None = None):
        self.size = size
        self.train = train
        self.rng = np.random.default_rng(seed)

    def __call__(self, image: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if self.train:
            if self.rng.random() < 0.5:
                image, mask = image[:, ::-1], mask[:, ::-1]
            if self.rng.random() < 0.2:
                image, mask = image[::-1], mask[::-1]
            k = int(self.rng.integers(0, 4))
            if k:
                image, mask = np.rot90(image, k), np.rot90(mask, k)
            if self.rng.random() < 0.5:
                # Brightness/contrast only: hue shifts would recolour rust,
                # and colour is a real signal for corrosion type.
                brightness = self.rng.uniform(-0.15, 0.15)
                contrast = self.rng.uniform(0.85, 1.15)
                image = np.clip((image - 0.5) * contrast + 0.5 + brightness, 0, 1)
        return np.ascontiguousarray(image), np.ascontiguousarray(mask)


def _load_image(path: Path, size: int) -> np.ndarray:
    img = Image.open(path).convert("RGB").resize((size, size), Image.BILINEAR)
    return np.asarray(img, dtype=np.float32) / 255.0


def _load_mask(path: Path, size: int) -> np.ndarray:
    msk = Image.open(path)
    if msk.mode not in ("L", "P", "I", "I;16"):
        msk = msk.convert("L")
    msk = msk.resize((size, size), Image.NEAREST)
    arr = np.asarray(msk)
    if arr.ndim == 3:
        arr = arr[..., 0]
    return arr.astype(np.int64)


class CorrosionDataset(Dataset):
    """Pairs of (image tensor, mask tensor) ready for a DataLoader.

    Args:
        images / masks: matching lists of paths.
        size: square side the images are resized to.
        augment: an Augment instance, or None.
        cache: hold decoded arrays in memory. Fine for a few hundred small
            images; leave off for the full 3129-image set unless RAM allows.
    """

    def __init__(
        self,
        images: list[Path],
        masks: list[Path],
        size: int = 256,
        augment: Augment | None = None,
        cache: bool = False,
    ):
        if len(images) != len(masks):
            raise ValueError(f"{len(images)} images but {len(masks)} masks")
        self.images = [Path(p) for p in images]
        self.masks = [Path(p) for p in masks]
        self.size = size
        self.augment = augment
        self.cache = cache
        self._cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}

    def __len__(self) -> int:
        return len(self.images)

    def __getitem__(self, i: int) -> tuple[torch.Tensor, torch.Tensor]:
        if self.cache and i in self._cache:
            image, mask = self._cache[i]
        else:
            image = _load_image(self.images[i], self.size)
            mask = _load_mask(self.masks[i], self.size)
            if self.cache:
                self._cache[i] = (image, mask)

        if self.augment is not None:
            image, mask = self.augment(image, mask)

        image = (image - MEAN) / STD
        # HWC -> CHW, which is what conv layers expect.
        x = torch.from_numpy(image.transpose(2, 0, 1).copy()).float()
        y = torch.from_numpy(mask.copy()).long()
        return x, y


def class_weights(
    dataset: CorrosionDataset,
    num_classes: int,
    sample: int = 100,
    power: float = 0.5,
    max_ratio: float = 8.0,
) -> torch.Tensor:
    """Frequency-based class weights, damped so they do not overcorrect.

    The obvious choice, median-frequency balancing (`median(freq) / freq`), is
    too aggressive here. With background at ~82% and fifteen classes splitting
    the remaining 18%, it weights background about 68x lower than everything
    else — so the cheapest way to reduce the loss becomes predicting corrosion
    nearly everywhere. Measured on the sample data that collapsed pixel accuracy
    to 0.02, far below the 0.82 you get by predicting background and nothing else.

    Two changes fix it:

    ``power``
        Raise the ratio to a fractional power. 1.0 is full median-frequency
        balancing, 0.0 is uniform weighting. 0.5 (the square root) keeps rare
        classes boosted without letting background collapse.
    ``max_ratio``
        Clamp the spread between the largest and smallest weight, so no single
        class can dominate the gradient.

    Weights are normalised to a mean of 1, which keeps the loss magnitude — and
    therefore a sensible learning rate — roughly independent of these settings.
    """
    counts = np.zeros(num_classes, dtype=np.float64)
    n = min(len(dataset), sample)
    step = max(1, len(dataset) // n) if n else 1
    for i in range(0, len(dataset), step):
        mask = _load_mask(dataset.masks[i], dataset.size)
        vals, cnt = np.unique(mask, return_counts=True)
        for v, c in zip(vals, cnt):
            if 0 <= v < num_classes:
                counts[v] += c

    freq = counts / max(counts.sum(), 1)
    seen = freq[freq > 0]
    if seen.size == 0:
        return torch.ones(num_classes)

    ratio = np.where(freq > 0, np.median(seen) / np.maximum(freq, 1e-12), 0.0)
    weights = np.power(ratio, power, where=ratio > 0, out=np.zeros_like(ratio))

    positive = weights[weights > 0]
    if positive.size:
        # Clamp the spread, then normalise so the mean weight is 1.
        weights = np.clip(weights, positive.min(), positive.min() * max_ratio)
        weights = np.where(freq > 0, weights, 0.0)
        mean = weights[weights > 0].mean()
        if mean > 0:
            weights = weights / mean

    return torch.tensor(weights, dtype=torch.float32)

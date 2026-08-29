"""Segmentation metrics, accumulated over batches.

Why not just accuracy: on this dataset most pixels are clean metal. A model that
predicts "background" everywhere scores over 90% pixel accuracy and is useless.
IoU per class exposes that immediately - the corrosion classes sit at zero.

Everything is accumulated into a confusion matrix first, then metrics are derived
from it. That keeps the numbers exact regardless of batch size, which streaming
averages do not (a mean of per-batch IoUs is not the IoU of the dataset).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Result:
    """Metrics for one evaluation pass."""
    mean_iou: float
    mean_dice: float
    pixel_accuracy: float
    per_class_iou: dict[str, float]
    per_class_dice: dict[str, float]
    support: dict[str, int]
    present: list[str]

    def to_dict(self) -> dict:
        return {
            "mean_iou": round(self.mean_iou, 4),
            "mean_dice": round(self.mean_dice, 4),
            "pixel_accuracy": round(self.pixel_accuracy, 4),
            "per_class_iou": {k: round(v, 4) for k, v in self.per_class_iou.items()},
            "per_class_dice": {k: round(v, 4) for k, v in self.per_class_dice.items()},
            "support": self.support,
        }

    def table(self, top: int | None = None) -> str:
        rows = sorted(self.per_class_iou.items(), key=lambda kv: -self.support.get(kv[0], 0))
        if top:
            rows = rows[:top]
        out = [f"{'class':<46}{'IoU':>8}{'Dice':>8}{'pixels':>12}",
               "-" * 74]
        for name, iou in rows:
            n = self.support.get(name, 0)
            flag = "" if n else "   (absent)"
            out.append(f"{name:<46}{iou:>8.4f}{self.per_class_dice[name]:>8.4f}{n:>12,}{flag}")
        out.append("-" * 74)
        out.append(f"{'mean (classes present in ground truth)':<46}"
                   f"{self.mean_iou:>8.4f}{self.mean_dice:>8.4f}")
        out.append(f"{'pixel accuracy':<46}{self.pixel_accuracy:>8.4f}")
        return "\n".join(out)


class ConfusionMatrix:
    """Accumulates predictions across batches.

    Entry [i, j] counts pixels whose true class is i and predicted class is j.
    """

    def __init__(self, num_classes: int, class_names: list[str] | None = None):
        self.num_classes = num_classes
        self.class_names = class_names or [f"class_{i}" for i in range(num_classes)]
        self.matrix = np.zeros((num_classes, num_classes), dtype=np.int64)

    def reset(self) -> None:
        self.matrix[:] = 0

    def update(self, target, prediction) -> None:
        """Add a batch. Accepts torch tensors or numpy arrays of equal shape."""
        t = _to_numpy(target).reshape(-1)
        p = _to_numpy(prediction).reshape(-1)
        if t.shape != p.shape:
            raise ValueError(f"shape mismatch: target {t.shape} vs prediction {p.shape}")

        # Ignore anything outside the label space instead of crashing on a
        # stray value - a corrupt mask should not kill a long training run.
        keep = (t >= 0) & (t < self.num_classes) & (p >= 0) & (p < self.num_classes)
        t, p = t[keep], p[keep]

        # bincount on a flattened index is far faster than a Python loop.
        idx = t.astype(np.int64) * self.num_classes + p.astype(np.int64)
        counts = np.bincount(idx, minlength=self.num_classes ** 2)
        self.matrix += counts.reshape(self.num_classes, self.num_classes)

    def compute(self) -> Result:
        m = self.matrix.astype(np.float64)
        tp = np.diag(m)
        fp = m.sum(axis=0) - tp
        fn = m.sum(axis=1) - tp

        union = tp + fp + fn
        denom = 2 * tp + fp + fn

        # Classes absent from the ground truth are reported as 0 but excluded
        # from the mean; averaging in a class nobody annotated would be noise.
        with np.errstate(divide="ignore", invalid="ignore"):
            iou = np.where(union > 0, tp / np.maximum(union, 1e-9), 0.0)
            dice = np.where(denom > 0, 2 * tp / np.maximum(denom, 1e-9), 0.0)

        support = m.sum(axis=1)
        present = support > 0

        total = m.sum()
        names = self.class_names
        return Result(
            mean_iou=float(iou[present].mean()) if present.any() else 0.0,
            mean_dice=float(dice[present].mean()) if present.any() else 0.0,
            pixel_accuracy=float(tp.sum() / total) if total else 0.0,
            per_class_iou={names[i]: float(iou[i]) for i in range(self.num_classes)},
            per_class_dice={names[i]: float(dice[i]) for i in range(self.num_classes)},
            support={names[i]: int(support[i]) for i in range(self.num_classes)},
            present=[names[i] for i in range(self.num_classes) if present[i]],
        )


def _to_numpy(x):
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    return np.asarray(x)


def confusion_to_csv(cm: ConfusionMatrix) -> str:
    head = "true\\pred," + ",".join(cm.class_names)
    rows = [head]
    for i, name in enumerate(cm.class_names):
        rows.append(name + "," + ",".join(str(int(v)) for v in cm.matrix[i]))
    return "\n".join(rows)

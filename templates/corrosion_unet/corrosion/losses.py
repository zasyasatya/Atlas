"""Loss functions for imbalanced segmentation.

Cross-entropy alone under-performs here. It optimises average per-pixel
correctness, and when 90% of pixels are background the cheapest way to lower the
loss is to predict background more often. Dice optimises region overlap instead,
which is closer to what IoU measures and much less sensitive to imbalance.

The default is the sum of both: cross-entropy gives clean gradients early when
predictions are near-random and Dice is nearly flat, while Dice pulls the model
towards overlap once it is roughly right.
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class DiceLoss(nn.Module):
    """Soft multi-class Dice loss.

    "Soft" because it uses softmax probabilities rather than hard argmax labels,
    which keeps the whole thing differentiable.
    """

    def __init__(self, smooth: float = 1.0, ignore_index: int | None = None):
        super().__init__()
        self.smooth = smooth
        self.ignore_index = ignore_index

    def forward(self, logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        num_classes = logits.shape[1]
        probs = F.softmax(logits, dim=1)

        valid = None
        if self.ignore_index is not None:
            valid = (target != self.ignore_index)
            target = target.clone()
            target[~valid] = 0

        true_1h = F.one_hot(target.clamp(0, num_classes - 1), num_classes)
        true_1h = true_1h.permute(0, 3, 1, 2).float()

        if valid is not None:
            m = valid.unsqueeze(1).float()
            probs, true_1h = probs * m, true_1h * m

        dims = (0, 2, 3)
        intersection = (probs * true_1h).sum(dims)
        cardinality = probs.sum(dims) + true_1h.sum(dims)
        dice = (2 * intersection + self.smooth) / (cardinality + self.smooth)

        # Average only over classes that appear in this batch; a class with no
        # pixels scores a perfect 1.0 by construction and would inflate the score.
        present = true_1h.sum(dims) > 0
        if present.any():
            dice = dice[present]
        return 1.0 - dice.mean()


class ComboLoss(nn.Module):
    """weight_ce * CrossEntropy + weight_dice * Dice."""

    def __init__(
        self,
        class_weights: torch.Tensor | None = None,
        weight_ce: float = 0.5,
        weight_dice: float = 0.5,
        ignore_index: int | None = None,
    ):
        super().__init__()
        self.ce = nn.CrossEntropyLoss(
            weight=class_weights,
            ignore_index=ignore_index if ignore_index is not None else -100,
        )
        self.dice = DiceLoss(ignore_index=ignore_index)
        self.weight_ce = weight_ce
        self.weight_dice = weight_dice

    def forward(self, logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        return self.weight_ce * self.ce(logits, target) + self.weight_dice * self.dice(logits, target)


def build_loss(
    name: str = "combo",
    class_weights: torch.Tensor | None = None,
    ignore_index: int | None = None,
) -> nn.Module:
    name = name.lower()
    if name in ("ce", "crossentropy"):
        return nn.CrossEntropyLoss(
            weight=class_weights,
            ignore_index=ignore_index if ignore_index is not None else -100,
        )
    if name == "dice":
        return DiceLoss(ignore_index=ignore_index)
    if name == "combo":
        return ComboLoss(class_weights=class_weights, ignore_index=ignore_index)
    raise ValueError(f"unknown loss {name!r}; expected ce, dice or combo")

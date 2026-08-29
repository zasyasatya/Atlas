"""Corrosion type segmentation with U-Net.

A small, readable implementation built for the ATLAS internship: every piece an
intern is asked to understand is written out rather than imported from a library.

    from corrosion import discover, inspect_labels, build_model, fit

Modules:
    data        find images/masks, work out the class list from the files
    dataset     torch Dataset, augmentation, class weighting
    model       U-Net, written from scratch
    losses      Dice / cross-entropy / combo
    metrics     IoU, Dice, pixel accuracy via a confusion matrix
    train       training loop, checkpoints, run history
    inference   load a checkpoint and segment new images
"""
from .data import (
    DEFAULT_CLASSES,
    LabelSpace,
    Split,
    discover,
    find_classes,
    inspect_labels,
    split_flat,
    summarise,
)
from .dataset import Augment, CorrosionDataset, class_weights
from .losses import ComboLoss, DiceLoss, build_loss
from .metrics import ConfusionMatrix, Result
from .model import UNet, build_model
from .train import (
    TrainConfig,
    describe_device,
    evaluate,
    fit,
    pick_device,
    seed_everything,
    test_and_report,
)

__version__ = "1.0.0"

__all__ = [
    "DEFAULT_CLASSES", "LabelSpace", "Split", "discover", "find_classes",
    "inspect_labels", "split_flat", "summarise",
    "Augment", "CorrosionDataset", "class_weights",
    "ComboLoss", "DiceLoss", "build_loss",
    "ConfusionMatrix", "Result",
    "UNet", "build_model",
    "TrainConfig", "describe_device", "evaluate", "fit", "pick_device",
    "seed_everything", "test_and_report",
    "__version__",
]

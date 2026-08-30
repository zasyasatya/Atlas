#!/usr/bin/env python3
"""Unit checks for corrosion_kit.py - the file every notebook and the app import.

The kit is the single source of truth for the Topic 6 pipeline: dataset
discovery, the label-space decision, augmentation, the U-Net, the loss, the
metrics, checkpointing and inference. If it is wrong, five notebooks and a
deployed app are wrong together - so it gets its own tests.

    python tests/test_kit.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import corrosion_kit as ck  # noqa: E402

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"
_passed = _failed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global _passed, _failed
    if ok:
        _passed += 1
        print(f"  {GREEN}[PASS]{RESET} {name} {DIM}{detail}{RESET}")
    else:
        _failed += 1
        print(f"  {RED}[FAIL]{RESET} {name} {DIM}{detail}{RESET}")


def section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")


def main() -> int:
    import torch

    work = ROOT / ".kittest"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()

    print(f"{BOLD}corrosion_kit{RESET}")
    print("=" * 74)

    # ------------------------------------------------------------ discovery
    section("Dataset discovery")
    # 16 images so every one of the 15 classes is drawn at least once - the
    # background decision below is only meaningful when the mask values
    # actually reach 15.
    data = Path(ck.make_sample_dataset(work / "data", count=16, size=64, seed=3))
    check("sample dataset generated", ck.looks_like_dataset(data), str(data))

    splits = ck.discover(data)
    check("splits found", set(splits) == {"train", "val", "test"}, ", ".join(sorted(splits)))
    check("images pair with masks",
          all(len(s.images) == len(s.masks) and len(s) for s in splits.values()),
          ", ".join(f"{n}={len(s)}" for n, s in sorted(splits.items())))

    # A stray image with no mask must be dropped, not silently mispaired.
    orphan = data / "train" / "images" / "orphan.jpg"
    Image.fromarray(np.zeros((32, 32, 3), dtype=np.uint8)).save(orphan)
    check("an image with no mask is skipped",
          len(ck.discover(data)["train"]) == len(splits["train"]), "unchanged count")
    orphan.unlink()

    flat = work / "flat"
    (flat / "images").mkdir(parents=True)
    (flat / "masks").mkdir(parents=True)
    for i, (image, mask) in enumerate(zip(splits["train"].images, splits["train"].masks)):
        shutil.copy(image, flat / "images" / f"f{i}.jpg")
        shutil.copy(mask, flat / "masks" / f"f{i}.png")
    flat_splits = ck.split_flat(ck.discover(flat))
    check("a flat export is split into train/val/test",
          set(flat_splits) <= {"train", "val", "test"} and "train" in flat_splits,
          ", ".join(f"{n}={len(s)}" for n, s in sorted(flat_splits.items())))

    # ---------------------------------------------------------- label space
    section("Label space")
    names, class_file = ck.find_classes(data)
    check("class list read from the export", len(names) == 15, f"{len(names)} names")

    space = ck.inspect_labels(splits, names)
    check("an unlisted background is detected and prepended",
          space.num_classes == 16 and space.has_background and space.class_names[0] == "background",
          space.source)
    check("frequencies sum to 1",
          abs(sum(space.frequencies().values()) - 1.0) < 1e-6,
          f"{sum(space.frequencies().values()):.6f}")
    check("background dominates, as the real export does",
          space.frequencies()["background"] > 0.4,
          f"{space.frequencies()['background'] * 100:.1f}%")

    listed = ["background"] + names
    space_listed = ck.inspect_labels(splits, listed)
    check("a class file that already lists background is not doubled",
          space_listed.num_classes == 16 and space_listed.class_names[0] == "background",
          space_listed.source)

    # ------------------------------------------------------------- dataset
    section("Loading and augmentation")
    mask_path = splits["train"].masks[0]
    original = set(np.unique(ck.read_mask(mask_path)).tolist())
    resized = set(np.unique(ck.load_mask(mask_path, 37)).tolist())
    check("resizing a mask invents no new class indices",
          resized <= original, f"{sorted(original)} -> {sorted(resized)}")

    dataset = ck.CorrosionDataset(splits["train"].images, splits["train"].masks, size=48)
    x, y = dataset[0]
    check("image tensor is CHW float", tuple(x.shape) == (3, 48, 48) and x.dtype == torch.float32,
          str(tuple(x.shape)))
    check("mask tensor is HW long", tuple(y.shape) == (48, 48) and y.dtype == torch.int64,
          str(tuple(y.shape)))

    image = np.zeros((8, 8, 3), dtype=np.float32)
    image[:, :4] = 1.0
    mask = np.zeros((8, 8), dtype=np.int64)
    mask[:, :4] = 5
    flipped_image, flipped_mask = ck.Augment(8, train=True, seed=0)(image, mask)
    aligned = ((flipped_image[..., 0] > 0.5) == (flipped_mask == 5)).all()
    check("augmentation moves image and mask together", bool(aligned),
          "labels still line up with the pixels")

    weights = ck.class_weights(splits["train"].masks, space.num_classes, size=48)
    positive = weights[weights > 0]
    check("class weights normalise to mean 1", abs(float(positive.mean()) - 1.0) < 0.05,
          f"mean {float(positive.mean()):.3f}")
    check("class weights are clamped to an 8:1 spread",
          float(positive.max()) / float(positive.min()) <= 8.01,
          f"{float(positive.max()) / float(positive.min()):.1f}x")

    # --------------------------------------------------------------- model
    section("U-Net")
    model = ck.build_model(space.num_classes, width=8)
    out = model(torch.randn(2, 3, 64, 64))
    check("output keeps the input's height and width",
          tuple(out.shape) == (2, space.num_classes, 64, 64), str(tuple(out.shape)))
    odd = model(torch.randn(1, 3, 70, 54))
    check("odd input sizes still come back whole",
          tuple(odd.shape)[-2:] == (70, 54), str(tuple(odd.shape)))
    check("parameters are counted", model.count_parameters() > 1000,
          f"{model.count_parameters():,}")

    # ---------------------------------------------------------------- loss
    section("Loss")
    logits = torch.zeros(1, 3, 4, 4)
    target = torch.zeros(1, 4, 4, dtype=torch.long)
    logits[:, 0] = 10.0
    dice = ck.DiceLoss()(logits, target)
    check("a perfect prediction gives ~0 dice loss", float(dice) < 0.05, f"{float(dice):.4f}")
    logits_wrong = torch.zeros(1, 3, 4, 4)
    logits_wrong[:, 2] = 10.0
    check("a wrong prediction gives ~1 dice loss",
          float(ck.DiceLoss()(logits_wrong, target)) > 0.9,
          f"{float(ck.DiceLoss()(logits_wrong, target)):.4f}")
    combo = ck.build_loss("combo", class_weights=torch.ones(3))
    check("combo loss ranks a good prediction below a bad one",
          float(combo(logits, target)) < float(combo(logits_wrong, target)),
          f"{float(combo(logits, target)):.3f} < {float(combo(logits_wrong, target)):.3f}")

    # ------------------------------------------------------------- metrics
    section("Metrics")
    matrix = ck.ConfusionMatrix(3, ["background", "a", "b"])
    truth = torch.tensor([[0, 0, 1, 1]])
    predicted = torch.tensor([[0, 0, 1, 2]])
    result = matrix.update(truth, predicted).compute()
    check("perfectly predicted class scores IoU 1",
          abs(result["per_class_iou"]["background"] - 1.0) < 1e-9,
          f"{result['per_class_iou']['background']:.3f}")
    check("half-missed class scores IoU 0.5",
          abs(result["per_class_iou"]["a"] - 0.5) < 1e-9, f"{result['per_class_iou']['a']:.3f}")
    check("a class absent from the truth is excluded from the mean",
          abs(result["mean_iou"] - 0.75) < 1e-9, f"{result['mean_iou']:.3f}")

    # "predict background everywhere" must look good on accuracy and terrible
    # on IoU - the entire reason the notebooks report IoU.
    lazy = ck.ConfusionMatrix(3, ["background", "a", "b"])
    lazy_truth = torch.tensor([[0] * 90 + [1] * 10])
    lazy.update(lazy_truth, torch.zeros_like(lazy_truth))
    lazy_result = lazy.compute()
    check("predicting only background scores high accuracy",
          lazy_result["pixel_acc"] > 0.85, f"{lazy_result['pixel_acc']:.2f}")
    check("...and IoU refuses to be fooled by it",
          lazy_result["per_class_iou"]["a"] == 0.0 and lazy_result["mean_iou"] < 0.6,
          f"mean IoU {lazy_result['mean_iou']:.2f}")
    check("confusion matrix exports as CSV",
          lazy.to_csv().startswith("truth\\pred,background"), lazy.to_csv().splitlines()[0][:40])

    # --------------------------------------------------------- checkpoints
    section("Checkpoints")
    path = work / "checkpoints" / "best.pt"
    ck.save_checkpoint(path, {"model": model.state_dict(), "class_names": space.class_names,
                              "epoch": 3, "mean_iou": 0.42,
                              "config": {"image_size": 64, "width": 8, "depth": 4}})
    check("checkpoint written", path.exists(), f"{path.stat().st_size:,} bytes")
    check("no temp file left behind", not path.with_suffix(".pt.tmp").exists(),
          "atomic save cleaned up")

    rebuilt, rebuilt_names, config = ck.model_from_checkpoint(ck.load_checkpoint(path))
    check("model rebuilt from the checkpoint alone",
          rebuilt.num_classes == space.num_classes and rebuilt_names == space.class_names,
          f"{rebuilt.num_classes} classes, width {config.get('width')}")

    corrupt = work / "checkpoints" / "corrupt.pt"
    corrupt.write_bytes(b"not a checkpoint")
    check("a half-written checkpoint is reported, not raised",
          ck.load_checkpoint(corrupt) is None, "returns None")
    check("a missing checkpoint returns None",
          ck.load_checkpoint(work / "nope.pt") is None)

    # ----------------------------------------------------------- inference
    section("Inference")
    predictor = ck.Predictor(path, device="cpu")
    photo = Image.open(splits["test"].images[0]).convert("RGB").resize((91, 53))
    prediction = predictor.predict(photo)
    check("prediction comes back at the photograph's resolution",
          prediction.mask.shape == (53, 91), str(prediction.mask.shape))
    check("confidence is a probability",
          0.0 < prediction.mean_confidence <= 1.0, f"{prediction.mean_confidence:.3f}")
    check("class shares sum to 1",
          abs(sum(prediction.class_share.values()) - 1.0) < 1e-6)
    check("the dominant class is never background",
          not ck.is_background(prediction.dominant), prediction.dominant)
    check("result serialises for an API or a report",
          set(prediction.to_dict()) >= {"dominant", "mean_confidence", "classes"})

    overlay = predictor.overlay(photo, prediction.mask, 0.5)
    check("overlay matches the photograph's size", overlay.size == (91, 53), str(overlay.size))
    check("legend covers every class", len(predictor.legend()) == space.num_classes,
          f"{len(predictor.legend())} entries")
    check("metadata says how the model was trained",
          predictor.metadata()["trained_epoch"] == 3
          and predictor.metadata()["validation_mean_iou"] == 0.42)

    # ------------------------------------------------------------ manifest
    section("Manifest")
    manifest = ck.write_manifest(work / "manifest.json", splits, space, data,
                                 extra={"class_weights": weights.tolist()})
    record = ck.read_manifest(manifest)
    check("manifest round-trips the splits",
          {n: len(s) for n, s in record["splits"].items()} ==
          {n: len(s) for n, s in splits.items()},
          ", ".join(f"{n}={len(s)}" for n, s in sorted(record["splits"].items())))
    check("manifest round-trips the label space",
          record["space"].class_names == space.class_names
          and record["space"].has_background == space.has_background)
    check("manifest carries the class weights",
          len(record["raw"]["class_weights"]) == space.num_classes)

    # ------------------------------------------------------- the shipped app
    section("Deployment app")
    app = (ROOT.parent / "corrosion_app" / "app.py").read_text(encoding="utf-8")
    check("app imports only the kit from the training stack",
          "from corrosion_kit import" in app and "from corrosion." not in app)
    check("app offers single and bulk input",
          "st.file_uploader" in app and "accept_multiple_files=True" in app)
    check("app shows a confidence score", "confidence" in app.lower())
    check("app draws a chart", "st.bar_chart" in app)
    for word in ("limitation", "dataset", "architecture", "evaluation"):
        check(f"documentation covers {word}", word in app.lower())

    shutil.rmtree(work, ignore_errors=True)

    total = _passed + _failed
    print()
    if _failed:
        print(f"{RED}{BOLD}=== {_passed}/{total} passed, {_failed} failed ==={RESET}")
    else:
        print(f"{GREEN}{BOLD}=== {_passed}/{total} passed ==={RESET}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())

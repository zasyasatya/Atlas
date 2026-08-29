#!/usr/bin/env python3
"""Train the corrosion U-Net from the command line.

    # smoke test on generated data
    python make_sample_data.py --out data/sample --count 60
    python train.py --data data/sample --epochs 3 --width 16 --size 128

    # the real export, on a GPU
    python train.py --data data/corrovision --epochs 60 --batch-size 16 --size 512

Everything lands in --run-dir: config, per-epoch history, best/last weights,
a test report and a confusion matrix.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch

from corrosion import (
    Augment, CorrosionDataset, TrainConfig, build_loss, build_model,
    class_weights, describe_device, discover, find_classes, fit,
    inspect_labels, pick_device, seed_everything, split_flat, summarise,
    test_and_report,
)


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="dataset root (the unzipped export)")
    ap.add_argument("--run-dir", default="runs/corrosion-unet")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--size", type=int, default=256, help="images are resized to size x size")
    ap.add_argument("--width", type=int, default=32, help="channels at the first U-Net level")
    ap.add_argument("--depth", type=int, default=4, help="downsampling steps")
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--loss", default="combo", choices=["combo", "dice", "ce"])
    ap.add_argument("--device", default="auto", help="auto, cuda, cpu, mps")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--patience", type=int, default=10, help="0 disables early stopping")
    ap.add_argument("--no-amp", action="store_true", help="disable mixed precision on CUDA")
    ap.add_argument("--no-class-weights", action="store_true")
    ap.add_argument("--cache", action="store_true", help="hold decoded images in RAM")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--limit", type=int, default=0, help="use only N training images (debug)")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    root = Path(args.data)

    # Before build_model(), so weight initialisation is part of the seed.
    seed_everything(args.seed)

    # ---- data -----------------------------------------------------------
    splits = discover(root)
    if not splits:
        print(f"No image/mask pairs under {root}.", file=sys.stderr)
        print("Expected <root>/train/images + <root>/train/masks, "
              "or <root>/images + <root>/masks.", file=sys.stderr)
        return 2

    splits = split_flat(splits)
    names, class_file = find_classes(root)
    space = inspect_labels(splits, names)

    print(summarise(splits, space))
    print(f"\nclass list: {class_file if class_file else 'not found, inferred from masks'}")

    if "train" not in splits:
        print("No training split found.", file=sys.stderr)
        return 2
    if "val" not in splits:
        # Borrow from train rather than train blind.
        tr = splits["train"]
        cut = max(1, int(len(tr) * 0.1))
        from corrosion.data import Split
        splits["val"] = Split("val", tr.images[:cut], tr.masks[:cut])
        splits["train"] = Split("train", tr.images[cut:], tr.masks[cut:])
        print(f"no validation split; held out {cut} training images")

    if args.limit:
        from corrosion.data import Split
        t = splits["train"]
        splits["train"] = Split("train", t.images[:args.limit], t.masks[:args.limit])
        print(f"limited to {len(splits['train'])} training images")

    train_ds = CorrosionDataset(splits["train"].images, splits["train"].masks,
                                size=args.size, augment=Augment(args.size, True, args.seed),
                                cache=args.cache)
    val_ds = CorrosionDataset(splits["val"].images, splits["val"].masks,
                              size=args.size, cache=args.cache)
    test_split = splits.get("test") or splits["val"]
    test_ds = CorrosionDataset(test_split.images, test_split.masks, size=args.size)

    # ---- model ----------------------------------------------------------
    device = pick_device(args.device)
    print(f"\ndevice: {describe_device(device)}")
    if device.type == "cpu":
        print("  running on CPU - fine for a smoke test, slow for real training")

    model = build_model(space.num_classes, width=args.width, depth=args.depth)
    print(f"U-Net: {model.count_parameters():,} parameters, "
          f"{space.num_classes} output channels")

    weights = None
    if not args.no_class_weights:
        weights = class_weights(train_ds, space.num_classes).to(device)
        top = sorted(zip(space.class_names, weights.tolist()), key=lambda kv: -kv[1])[:3]
        print("class weights (highest): " + ", ".join(f"{n}={w:.2f}" for n, w in top))
    loss_fn = build_loss(args.loss, class_weights=weights)

    config = TrainConfig(
        epochs=args.epochs, batch_size=args.batch_size, lr=args.lr,
        image_size=args.size, width=args.width, depth=args.depth, loss=args.loss,
        amp=not args.no_amp, num_workers=args.workers, patience=args.patience,
        seed=args.seed, run_dir=args.run_dir, class_names=space.class_names,
    )

    # ---- train ----------------------------------------------------------
    print(f"\ntraining {args.epochs} epochs, batch {args.batch_size}, {args.size}px")
    print("-" * 74)

    def show(row: dict) -> None:
        star = " *" if row.get("best") else "  "
        print(f"  epoch {row['epoch']:>3}/{args.epochs}"
              f"  train {row['train_loss']:.4f}"
              f"  val {row['val_loss']:.4f}"
              f"  mIoU {row['val_mean_iou']:.4f}"
              f"  dice {row['val_mean_dice']:.4f}"
              f"  {row['seconds']:.1f}s{star}")

    summary = fit(model, train_ds, val_ds, config, loss_fn, device, on_epoch=show)

    print("-" * 74)
    print(f"best mIoU {summary['best_mean_iou']:.4f} at epoch {summary['best_epoch']}"
          f" | {summary['total_seconds']:.1f}s total")

    # ---- test -----------------------------------------------------------
    print(f"\nevaluating on the {test_split.name} split ({len(test_ds)} images)")
    result = test_and_report(model, test_ds, config, loss_fn, device)
    print(result.table())

    run_dir = Path(args.run_dir)
    print(f"\nwritten to {run_dir}/")
    for f in ("config.json", "history.csv", "history.json", "best.pt",
              "last.pt", "report.json", "confusion.csv"):
        p = run_dir / f
        if p.exists():
            print(f"  {f:<16} {p.stat().st_size:>10,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

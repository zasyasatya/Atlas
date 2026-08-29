"""Training loop with per-epoch tracking, checkpointing and GPU support.

Every run writes a directory that is enough to reproduce and review it:

    runs/<name>/
        config.json      exact settings used
        history.csv      one row per epoch
        history.json     same, plus environment and timing
        best.pt          weights at the best validation mIoU
        last.pt          weights after the final epoch
        report.json      final test metrics, per class
        confusion.csv    test confusion matrix

GPU is used automatically when torch reports one. Mixed precision is switched on
for CUDA only, where it roughly halves memory use and speeds up training; on CPU
it is a slowdown, so it stays off.
"""
from __future__ import annotations

import csv
import json
import platform
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import torch
from torch.utils.data import DataLoader

from .metrics import ConfusionMatrix, Result, confusion_to_csv


# --------------------------------------------------------------------------
# reproducibility
# --------------------------------------------------------------------------
def seed_everything(seed: int = 42, deterministic: bool = False) -> None:
    """Seed every RNG that affects a run.

    Call this **before building the model**. Weight initialisation draws from the
    global torch RNG, so seeding inside fit() - after the caller has already
    constructed the network - leaves initialisation uncontrolled and two runs
    with the same seed diverge.

    deterministic=True additionally forces cuDNN into deterministic algorithms.
    That costs speed, so it is off by default; turn it on when you need two runs
    to match bit for bit.
    """
    import os
    import random

    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    if deterministic:
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


# --------------------------------------------------------------------------
# device
# --------------------------------------------------------------------------
def pick_device(prefer: str = "auto") -> torch.device:
    """Choose a device. 'auto' takes CUDA, then Apple MPS, then CPU."""
    if prefer != "auto":
        return torch.device(prefer)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def describe_device(device: torch.device) -> str:
    if device.type == "cuda":
        i = device.index or 0
        p = torch.cuda.get_device_properties(i)
        return f"CUDA: {p.name}, {p.total_memory / 1024**3:.1f} GB, capability {p.major}.{p.minor}"
    if device.type == "mps":
        return "Apple MPS"
    return f"CPU: {platform.processor() or platform.machine()}"


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------
@dataclass
class TrainConfig:
    epochs: int = 30
    batch_size: int = 8
    lr: float = 3e-4
    weight_decay: float = 1e-4
    image_size: int = 256
    width: int = 32
    depth: int = 4
    loss: str = "combo"
    amp: bool = True
    num_workers: int = 2
    patience: int = 10           # early stop after N epochs with no improvement
    grad_clip: float = 1.0
    seed: int = 42
    run_dir: str = "runs/corrosion-unet"
    class_names: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# one pass
# --------------------------------------------------------------------------
def train_one_epoch(
    model, loader, loss_fn, optimizer, device, scaler=None, grad_clip: float = 0.0,
) -> float:
    model.train()
    total, seen = 0.0, 0
    for x, y in loader:
        x = x.to(device, non_blocking=True)
        y = y.to(device, non_blocking=True)
        optimizer.zero_grad(set_to_none=True)

        if scaler is not None:
            with torch.autocast(device_type=device.type, dtype=torch.float16):
                loss = loss_fn(model(x), y)
            scaler.scale(loss).backward()
            if grad_clip:
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
            scaler.step(optimizer)
            scaler.update()
        else:
            loss = loss_fn(model(x), y)
            loss.backward()
            if grad_clip:
                torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
            optimizer.step()

        total += loss.item() * x.size(0)
        seen += x.size(0)
    return total / max(seen, 1)


@torch.no_grad()
def evaluate(model, loader, loss_fn, device, num_classes: int,
             class_names: list[str]) -> tuple[float, Result, ConfusionMatrix]:
    model.eval()
    cm = ConfusionMatrix(num_classes, class_names)
    total, seen = 0.0, 0
    for x, y in loader:
        x = x.to(device, non_blocking=True)
        y = y.to(device, non_blocking=True)
        logits = model(x)
        total += loss_fn(logits, y).item() * x.size(0)
        seen += x.size(0)
        cm.update(y, logits.argmax(dim=1))
    return total / max(seen, 1), cm.compute(), cm


# --------------------------------------------------------------------------
# the whole run
# --------------------------------------------------------------------------
def fit(
    model,
    train_ds,
    val_ds,
    config: TrainConfig,
    loss_fn,
    device: torch.device | None = None,
    on_epoch: Callable[[dict], None] | None = None,
) -> dict:
    """Train, tracking every epoch. Returns the history dict.

    on_epoch is called with each epoch's metrics — the ATLAS notebook passes
    atlas.metric here so progress streams back to the platform live.
    """
    # Reseeds shuffling and augmentation. Weight init happened in the caller,
    # so call seed_everything() before build_model() for a fully repeatable run.
    torch.manual_seed(config.seed)
    device = device or pick_device()
    model = model.to(device)

    run_dir = Path(config.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.json").write_text(json.dumps(asdict(config), indent=2))

    class_names = config.class_names or [f"class_{i}" for i in range(model.num_classes)]

    # Workers cost more than they save on tiny datasets, and can hang in
    # notebook sandboxes; disable them there.
    workers = config.num_workers if len(train_ds) > 64 else 0
    train_loader = DataLoader(
        train_ds, batch_size=config.batch_size, shuffle=True,
        num_workers=workers, pin_memory=(device.type == "cuda"), drop_last=False,
    )
    val_loader = DataLoader(
        val_ds, batch_size=config.batch_size, shuffle=False,
        num_workers=workers, pin_memory=(device.type == "cuda"),
    )

    optimizer = torch.optim.AdamW(model.parameters(), lr=config.lr,
                                  weight_decay=config.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=config.epochs)

    use_amp = config.amp and device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda") if use_amp else None

    history: list[dict] = []
    best_iou, best_epoch, stale = -1.0, 0, 0
    started = time.time()

    for epoch in range(1, config.epochs + 1):
        t0 = time.time()
        train_loss = train_one_epoch(model, train_loader, loss_fn, optimizer,
                                     device, scaler, config.grad_clip)
        val_loss, result, _ = evaluate(model, val_loader, loss_fn, device,
                                       model.num_classes, class_names)
        scheduler.step()

        row = {
            "epoch": epoch,
            "train_loss": round(train_loss, 5),
            "val_loss": round(val_loss, 5),
            "val_mean_iou": round(result.mean_iou, 5),
            "val_mean_dice": round(result.mean_dice, 5),
            "val_pixel_acc": round(result.pixel_accuracy, 5),
            "lr": round(optimizer.param_groups[0]["lr"], 8),
            "seconds": round(time.time() - t0, 2),
        }
        history.append(row)

        if result.mean_iou > best_iou:
            best_iou, best_epoch, stale = result.mean_iou, epoch, 0
            torch.save(
                {"model": model.state_dict(), "epoch": epoch,
                 "mean_iou": best_iou, "class_names": class_names,
                 "config": asdict(config)},
                run_dir / "best.pt",
            )
            row["best"] = True
        else:
            stale += 1
            row["best"] = False

        if on_epoch:
            on_epoch(row)

        _write_history(run_dir, history)

        if config.patience and stale >= config.patience:
            print(f"early stop at epoch {epoch}: no improvement for {stale} epochs")
            break

    torch.save({"model": model.state_dict(), "class_names": class_names,
                "config": asdict(config)}, run_dir / "last.pt")

    summary = {
        "history": history,
        "best_epoch": best_epoch,
        "best_mean_iou": round(best_iou, 5),
        "epochs_ran": len(history),
        "total_seconds": round(time.time() - started, 2),
        "device": describe_device(device),
        "amp": use_amp,
        "parameters": model.count_parameters(),
        "class_names": class_names,
    }
    (run_dir / "history.json").write_text(json.dumps(summary, indent=2))
    return summary


def _write_history(run_dir: Path, history: list[dict]) -> None:
    """Rewrite the CSV every epoch, so a killed run still leaves usable history."""
    if not history:
        return
    keys = list(history[0])
    with open(run_dir / "history.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys)
        writer.writeheader()
        for row in history:
            writer.writerow({k: row.get(k, "") for k in keys})


def test_and_report(model, test_ds, config: TrainConfig, loss_fn,
                    device: torch.device | None = None,
                    checkpoint: str | Path | None = None) -> Result:
    """Evaluate on the held-out test split and write report.json + confusion.csv."""
    device = device or pick_device()
    run_dir = Path(config.run_dir)
    class_names = config.class_names or [f"class_{i}" for i in range(model.num_classes)]

    ckpt_path = Path(checkpoint) if checkpoint else run_dir / "best.pt"
    if ckpt_path.exists():
        state = torch.load(ckpt_path, map_location=device, weights_only=False)
        model.load_state_dict(state["model"])
    model = model.to(device)

    loader = DataLoader(test_ds, batch_size=config.batch_size, shuffle=False)
    loss, result, cm = evaluate(model, loader, loss_fn, device,
                                model.num_classes, class_names)

    payload = result.to_dict()
    payload["test_loss"] = round(loss, 5)
    payload["checkpoint"] = str(ckpt_path)
    payload["device"] = describe_device(device)
    (run_dir / "report.json").write_text(json.dumps(payload, indent=2))
    (run_dir / "confusion.csv").write_text(confusion_to_csv(cm))
    return result

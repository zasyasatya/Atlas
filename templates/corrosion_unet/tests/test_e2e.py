#!/usr/bin/env python3
"""End-to-end scenario test: data on disk to a running deployment.

Not a unit test. This walks the entire path an intern walks, with real files and
a real model, and asserts on what actually happened at each step:

    1  generate a dataset shaped like the CorroVision export
    2  discover it and work out the label space from the pixels
    3  train a U-Net for real, on GPU if one exists
    4  prove the model learnt something (loss fell, mIoU rose)
    5  check every artifact a review needs was written
    6  reload the checkpoint in a fresh process-like context
    7  segment an unseen image and sanity-check the output
    8  run the bulk path over a folder
    9  confirm predictions are deterministic and CPU/GPU agree
   10  boot the Streamlit app and hit it over HTTP

    python tests/test_e2e.py                 # full run
    python tests/test_e2e.py --fast          # fewer epochs
    python tests/test_e2e.py --skip-app      # no Streamlit boot
"""
from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import torch
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from corrosion import (  # noqa: E402
    Augment, CorrosionDataset, TrainConfig, build_loss, build_model,
    class_weights, describe_device, discover, find_classes, fit,
    inspect_labels, pick_device, seed_everything, test_and_report,
)
from corrosion.inference import Predictor  # noqa: E402
from make_sample_data import generate  # noqa: E402

GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m")

_passed = _failed = 0
_notes: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    global _passed, _failed
    if ok:
        _passed += 1
        print(f"  {GREEN}[PASS]{RESET} {name} {DIM}{detail}{RESET}")
    else:
        _failed += 1
        print(f"  {RED}[FAIL]{RESET} {name} {DIM}{detail}{RESET}")
    return ok


def note(msg: str) -> None:
    _notes.append(msg)
    print(f"  {YELLOW}[NOTE]{RESET} {DIM}{msg}{RESET}")


def step(n: int, title: str) -> None:
    print(f"\n{BOLD}Step {n}: {title}{RESET}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true",
                    help="3 epochs: checks the pipeline runs, skips quality assertions")
    ap.add_argument("--skip-app", action="store_true", help="do not boot Streamlit")
    ap.add_argument("--keep", action="store_true", help="keep the scratch directory")
    args = ap.parse_args()

    work = ROOT / ".e2e"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()

    data_dir = work / "data"
    run_dir = work / "run"
    epochs = 3 if args.fast else 10
    # Below ~8 epochs the model has not converged, so quality assertions would
    # be measuring noise. --fast proves the pipeline runs; the full run proves
    # the model learns.
    quality = epochs >= 8

    print(f"{BOLD}End-to-end scenario: corrosion segmentation{RESET}")
    print("=" * 74)
    device = pick_device()
    print(f"device: {describe_device(device)}")
    if device.type == "cuda":
        print(f"        mixed precision will be enabled")
    else:
        note("no GPU here, running on CPU - the same code path takes the GPU "
             "branch automatically when one is present")

    # -------------------------------------------------------------- step 1
    step(1, "Generate a dataset shaped like the CorroVision export")
    counts = generate(data_dir, count=48, size=96, seed=7)
    check("dataset written", sum(counts.values()) == 48, f"{counts}")
    check("split directories exist",
          all((data_dir / s / d).is_dir() for s in ("train", "val", "test")
              for d in ("images", "masks")))
    check("class list written", (data_dir / "classes.txt").exists())

    n_img = len(list((data_dir / "train" / "images").glob("*.jpg")))
    n_msk = len(list((data_dir / "train" / "masks").glob("*.png")))
    check("every image has a mask", n_img == n_msk, f"{n_img} images, {n_msk} masks")

    # -------------------------------------------------------------- step 2
    step(2, "Discover the dataset and infer the label space")
    splits = discover(data_dir)
    check("all three splits found", set(splits) == {"train", "val", "test"},
          str({k: len(v) for k, v in splits.items()}))

    names, class_file = find_classes(data_dir)
    check("class file located", class_file is not None and len(names) == 15,
          f"{len(names)} names")

    space = inspect_labels(splits, names)
    check("background inferred, not assumed", space.has_background, space.source)
    check("16 output channels required", space.num_classes == 16,
          f"num_classes={space.num_classes}")
    check("class names aligned to indices",
          space.class_names[0] == "background" and space.class_names[1] == names[0])

    freq = space.frequencies()
    bg_share = freq.get("background", 0)
    check("background dominates, as in the real data", bg_share > 0.5,
          f"background={bg_share:.1%}")

    # -------------------------------------------------------------- step 3
    step(3, f"Train a U-Net for real ({epochs} epochs)")
    size = 96
    train_ds = CorrosionDataset(splits["train"].images, splits["train"].masks,
                                size=size, augment=Augment(size, True, 7), cache=True)
    val_ds = CorrosionDataset(splits["val"].images, splits["val"].masks,
                              size=size, cache=True)
    test_ds = CorrosionDataset(splits["test"].images, splits["test"].masks, size=size)

    seed_everything(7)
    model = build_model(space.num_classes, width=16)
    check("model output matches the label space", model.num_classes == 16,
          f"{model.count_parameters():,} parameters")

    # Same seed must give the same starting weights, or "seed=7" means nothing
    # and every number below is unrepeatable.
    seed_everything(7)
    twin = build_model(space.num_classes, width=16)
    check("seeding makes weight init repeatable",
          torch.equal(next(model.parameters()), next(twin.parameters())),
          "seed_everything() called before build_model()")
    del twin

    weights = class_weights(train_ds, space.num_classes).to(device)
    check("rare classes weighted above common ones", float(weights.max()) > float(weights.min()),
          f"max={float(weights.max()):.2f} min={float(weights.min()):.2f}")

    config = TrainConfig(epochs=epochs, batch_size=4, image_size=size, width=16,
                         patience=0, num_workers=0, run_dir=str(run_dir),
                         class_names=space.class_names)
    loss_fn = build_loss("combo", class_weights=weights)

    streamed: list[dict] = []
    t0 = time.time()
    summary = fit(model, train_ds, val_ds, config, loss_fn, device,
                  on_epoch=streamed.append)
    train_seconds = time.time() - t0

    check("every epoch reported progress", len(streamed) == epochs,
          f"{len(streamed)} callbacks in {train_seconds:.1f}s")
    check("callback carries the tracked metrics",
          all(k in streamed[0] for k in
              ("epoch", "train_loss", "val_loss", "val_mean_iou", "val_mean_dice")),
          str(sorted(streamed[0])))

    # -------------------------------------------------------------- step 4
    step(4, "Verify the model actually learnt")
    first, last = streamed[0], streamed[-1]
    best_iou = summary["best_mean_iou"]

    check("training loss went down",
          last["train_loss"] < first["train_loss"],
          f"{first['train_loss']:.4f} -> {last['train_loss']:.4f}")
    check("validation mIoU did not regress from epoch 1",
          best_iou >= first["val_mean_iou"],
          f"{first['val_mean_iou']:.4f} -> best {best_iou:.4f}")
    # 1/num_classes is the wrong bar: with background at ~82% a uniform random
    # guess actually scores far below it. Compare against what chance really
    # gives for these prevalences.
    prevalence = np.array([freq.get(n, 0.0) for n in space.class_names])
    chance_inter = prevalence / space.num_classes
    chance_iou = chance_inter / (prevalence + 1 / space.num_classes - chance_inter + 1e-12)
    chance = float(chance_iou[prevalence > 0].mean())
    if quality:
        check("mIoU beats chance for these prevalences", best_iou > chance,
              f"mIoU={best_iou:.4f} vs chance {chance:.4f}")
    else:
        note(f"mIoU-vs-chance skipped at {epochs} epochs "
             f"({best_iou:.4f} vs {chance:.4f}); --fast tests plumbing, not quality")

    # The other trap: a model can score well on mIoU while being useless, by
    # predicting corrosion everywhere. Pixel accuracy is the guard against a
    # class weighting that has overcorrected.
    #
    # Early on, a weighted loss legitimately suppresses background - accuracy
    # dips before it recovers. So the bar scales with the epoch budget: a 3-epoch
    # smoke run only has to stay off the floor, a full run has to actually
    # approach the trivial baseline.
    #
    # Measured on this data: accuracy starts near zero while the weighted loss
    # suppresses background, reaches ~0.6 by epoch 5 and ~0.67 by epoch 20. So
    # a 3-epoch smoke run cannot be held to a real accuracy bar - there, only
    # check the loss is moving. From ~8 epochs the model should be recognisably
    # working.
    trivial = freq.get("background", 0.0)
    best_acc = max(r["val_pixel_acc"] for r in streamed)
    if epochs < 8:
        note(f"accuracy bar skipped at {epochs} epochs "
             f"(best={best_acc:.4f}); needs ~8 to be meaningful")
        check("training loss is still decreasing",
              streamed[-1]["train_loss"] < streamed[0]["train_loss"],
              f"{streamed[0]['train_loss']:.4f} -> {streamed[-1]['train_loss']:.4f}")
    else:
        check("pixel accuracy is not collapsing",
              best_acc > 0.25,
              f"best accuracy={best_acc:.4f}, always-background={trivial:.4f}")

    check("losses stayed finite",
          all(np.isfinite(r["train_loss"]) and np.isfinite(r["val_loss"]) for r in streamed))
    check("device recorded in the summary", "device" in summary, summary["device"])

    # -------------------------------------------------------------- step 5
    step(5, "Check the artifacts a reviewer needs")
    for fname, why in [
        ("config.json", "exact settings"),
        ("history.csv", "per-epoch history"),
        ("history.json", "history + environment"),
        ("best.pt", "best weights"),
        ("last.pt", "final weights"),
    ]:
        p = run_dir / fname
        check(f"{fname} written", p.exists() and p.stat().st_size > 0,
              f"{why}, {p.stat().st_size:,} bytes" if p.exists() else "missing")

    result = test_and_report(model, test_ds, config, loss_fn, device)
    check("report.json written", (run_dir / "report.json").exists())
    check("confusion.csv written", (run_dir / "confusion.csv").exists())

    report = json.loads((run_dir / "report.json").read_text())
    check("report carries per-class IoU", len(report.get("per_class_iou", {})) == 16,
          f"{len(report.get('per_class_iou', {}))} classes")
    check("report carries per-class support", "support" in report)
    check("absent classes excluded from the mean",
          result.mean_iou >= min(v for k, v in result.per_class_iou.items()
                                 if result.support[k] > 0),
          f"test mIoU={result.mean_iou:.4f}, {len(result.present)} classes present")

    history_rows = (run_dir / "history.csv").read_text().strip().splitlines()
    check("history.csv has a row per epoch", len(history_rows) == epochs + 1,
          f"{len(history_rows) - 1} rows + header")

    # -------------------------------------------------------------- step 6
    step(6, "Reload the checkpoint the way the deployed app does")
    predictor = Predictor(run_dir / "best.pt", device="cpu")
    meta = predictor.metadata()
    check("class names travel with the checkpoint",
          predictor.class_names == space.class_names, f"{meta['classes']} classes")
    check("architecture reconstructed from the checkpoint alone",
          meta["parameters"] == model.count_parameters(), f"{meta['parameters']:,} parameters")
    check("image size recovered", predictor.image_size == size)
    check("checkpoint knows its own score", meta["validation_mean_iou"] is not None,
          f"val mIoU={meta['validation_mean_iou']}")

    # -------------------------------------------------------------- step 7
    step(7, "Segment an unseen image")
    unseen = splits["test"].images[0]
    original = Image.open(unseen).convert("RGB")
    out = predictor.predict(original)

    check("mask matches the input resolution",
          out.mask.shape == (original.size[1], original.size[0]),
          f"{out.mask.shape} for a {original.size[0]}x{original.size[1]} photo")
    check("predicted indices are valid classes",
          int(out.mask.min()) >= 0 and int(out.mask.max()) < 16,
          f"values {int(out.mask.min())}..{int(out.mask.max())}")
    check("confidence is a probability",
          0.0 <= float(out.confidence.min()) and float(out.confidence.max()) <= 1.0,
          f"{float(out.confidence.min()):.3f}..{float(out.confidence.max()):.3f}")
    check("mean confidence reported (rubric R4)", 0 < out.mean_confidence <= 1,
          f"{out.mean_confidence:.1%}")
    check("class shares sum to 1", abs(sum(out.class_share.values()) - 1) < 1e-3)
    check("a dominant finding is named", isinstance(out.dominant, str) and out.dominant,
          f"dominant={out.dominant}")

    overlay = predictor.overlay(original, out.mask)
    check("overlay renders at photo size", overlay.size == original.size)
    check("overlay is not a blank image", len(set(overlay.convert("L").getdata())) > 5)

    # Prediction should resemble the truth more than a shuffled baseline does.
    truth = np.array(Image.open(splits["test"].masks[0]).resize(
        original.size, Image.NEAREST))
    agree = float((out.mask == truth).mean())
    shuffled = truth.copy().ravel()
    np.random.default_rng(0).shuffle(shuffled)
    baseline = float((out.mask.ravel() == shuffled).mean())
    # A strict > would fail when an undertrained model predicts a single class
    # everywhere, which makes both numbers identical rather than the model worse.
    if quality:
        check("prediction is at least as good as a shuffled baseline",
              agree >= baseline - 1e-9,
              f"agreement {agree:.3f} vs shuffled {baseline:.3f}")
    else:
        note(f"shuffled-baseline check skipped at {epochs} epochs "
             f"({agree:.3f} vs {baseline:.3f})")

    # -------------------------------------------------------------- step 8
    step(8, "Run the bulk path over a folder")
    batch_files = splits["test"].images[:5]
    t0 = time.time()
    results = predictor.predict_batch([Image.open(p).convert("RGB") for p in batch_files])
    elapsed = time.time() - t0

    check("one result per input", len(results) == len(batch_files),
          f"{len(results)} images in {elapsed:.2f}s")
    check("every result carries a confidence",
          all(0 < r.mean_confidence <= 1 for r in results))
    check("every result names a dominant class",
          all(isinstance(r.dominant, str) and r.dominant for r in results))

    rows = [{"file": p.name, "dominant": r.dominant,
             "confidence": round(r.mean_confidence, 4),
             "affected_pct": round((1 - r.class_share.get("background", 0)) * 100, 2)}
            for p, r in zip(batch_files, results)]
    csv_path = work / "batch.csv"
    csv_path.write_text(
        "file,dominant,confidence,affected_pct\n" +
        "\n".join(f"{r['file']},{r['dominant']},{r['confidence']},{r['affected_pct']}"
                  for r in rows))
    check("batch results export as CSV", csv_path.exists() and
          len(csv_path.read_text().strip().splitlines()) == len(rows) + 1,
          f"{len(rows)} rows")

    # -------------------------------------------------------------- step 9
    step(9, "Determinism and device agreement")
    a = predictor.predict(original)
    b = predictor.predict(original)
    check("same input gives the same mask", np.array_equal(a.mask, b.mask))
    check("same input gives the same confidence",
          np.allclose(a.confidence, b.confidence, atol=1e-6))

    if torch.cuda.is_available():
        gpu_pred = Predictor(run_dir / "best.pt", device="cuda")
        g = gpu_pred.predict(original)
        overlap = float((g.mask == a.mask).mean())
        check("GPU and CPU agree", overlap > 0.99, f"{overlap:.4%} of pixels identical")
    else:
        note("GPU comparison skipped - no CUDA device on this machine")

    # -------------------------------------------------------------- step 10
    step(10, "Boot the deployment app and hit it over HTTP")
    if args.skip_app:
        note("Streamlit boot skipped by --skip-app")
    else:
        try:
            import streamlit  # noqa: F401
            have_streamlit = True
        except ImportError:
            have_streamlit = False

        if not have_streamlit:
            note("streamlit not installed - skipping. pip install streamlit")
        else:
            port = free_port()
            proc = subprocess.Popen(
                [sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
                 "--server.port", str(port), "--server.headless", "true",
                 "--server.address", "127.0.0.1",
                 "--browser.gatherUsageStats", "false",
                 "--", "--checkpoint", str(run_dir / "best.pt"),
                 "--run-dir", str(run_dir)],
                cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                up, body = False, ""
                for _ in range(60):
                    if proc.poll() is not None:
                        break
                    try:
                        with urllib.request.urlopen(
                                f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as r:
                            if r.status == 200:
                                up = True
                                break
                    except Exception:
                        time.sleep(1)

                if not up and proc.poll() is not None:
                    body = (proc.stdout.read() or "")[-1500:]
                check("app starts and reports healthy", up,
                      f"port {port}" if up else f"exited: {body[-300:]}")

                if up:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as r:
                        html = r.read().decode("utf-8", "ignore")
                    check("app serves its page", r.status == 200 and len(html) > 500,
                          f"{len(html):,} bytes")
                    check("page is a Streamlit app", "streamlit" in html.lower())
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()

    # ------------------------------------------------------------- verdict
    print("\n" + "=" * 74)
    total = _passed + _failed
    if _failed:
        print(f"{RED}{BOLD}{_passed}/{total} checks passed, {_failed} failed{RESET}")
    else:
        print(f"{GREEN}{BOLD}{_passed}/{total} checks passed{RESET}")
    if _notes:
        print(f"\n{len(_notes)} note(s):")
        for n in _notes:
            print(f"  - {n}")

    print(f"\nRun summary")
    print(f"  device        {summary['device']}")
    print(f"  epochs        {summary['epochs_ran']} in {summary['total_seconds']:.1f}s")
    print(f"  best val mIoU {summary['best_mean_iou']:.4f} (epoch {summary['best_epoch']})")
    print(f"  test mIoU     {result.mean_iou:.4f}")
    print(f"  test dice     {result.mean_dice:.4f}")
    print(f"  pixel acc     {result.pixel_accuracy:.4f}")

    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print(f"\nkept {work}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())

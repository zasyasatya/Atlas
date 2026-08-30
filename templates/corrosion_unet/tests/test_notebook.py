#!/usr/bin/env python3
"""Execute all five playground notebooks, cell by cell, against real data.

A notebook that renders is not proof of anything. This pulls the code cells
straight out of `notebook_factory.CORROSION_NOTEBOOKS`, runs them in order in
one work folder - exactly as an intern would - and checks what they produced.

It covers the three things that actually break:

  * a cell raises, so the notebook an intern opens is dead on arrival
  * the notebooks disagree about the data or the checkpoint format, so stage 3
    cannot read what stage 2 wrote
  * training does not resume after an interruption, which is the whole point of
    the Colab-safe checkpointing

Run:
    python tests/test_notebook.py            # real dataset if it is on disk
    python tests/test_notebook.py --fast     # fewer images, 1 epoch
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATLAS_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ATLAS_ROOT / "backend"))

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


class AtlasStub:
    """Stands in for the bridge ATLAS injects as cell 0."""

    def __init__(self, dataset_zip: Path | None = None):
        self._zip = dataset_zip
        self.logs: list[str] = []
        self.metrics: list[dict] = []
        self.artifacts: list[str] = []
        self.status: str | None = None

    def log(self, *args):
        line = " ".join(str(a) for a in args)
        self.logs.append(line)

    def metric(self, **kw):
        self.metrics.append(kw)

    def dataset(self):
        return str(self._zip) if self._zip else None

    def artifact(self, path):
        self.artifacts.append(str(path))

    def finish(self, status="succeeded", error=""):
        self.status = status

    def said(self, needle: str) -> bool:
        return any(needle in line for line in self.logs)


def build_subset(dest: Path, per_split: dict, fast: bool) -> Path:
    """A small real dataset: the actual export if it is on disk, else synthetic.

    Real photographs and real masks matter here - the mask-encoding logic is
    what these notebooks are mostly made of, and synthetic masks would not
    exercise the background-class decision the same way.
    """
    sys.path.insert(0, str(ROOT))
    import corrosion_kit as ck

    source = ck.find_local_dataset("corrovision-dataset-v1_semantic_export",
                                   start=ATLAS_ROOT)
    if source is None:
        print(f"  {DIM}real export not found - using a synthetic stand-in{RESET}")
        return Path(ck.make_sample_dataset(dest, count=per_split["train"], size=96))

    print(f"  {DIM}subsetting {source}{RESET}")
    splits = ck.discover(source)
    dest.mkdir(parents=True, exist_ok=True)
    classes = source / "classes.txt"
    if classes.exists():
        shutil.copy(classes, dest / "classes.txt")

    for name, count in per_split.items():
        split = splits.get(name)
        if not split:
            continue
        (dest / name / "images").mkdir(parents=True, exist_ok=True)
        (dest / name / "masks").mkdir(parents=True, exist_ok=True)
        # Spread the picks across the split so several classes appear.
        step = max(1, len(split.images) // count)
        for image, mask in list(zip(split.images, split.masks))[::step][:count]:
            shutil.copy(image, dest / name / "images" / image.name)
            shutil.copy(mask, dest / name / "masks" / mask.name)
    return dest


def code_cells(notebook: dict) -> list[str]:
    return ["".join(cell["source"]) for cell in notebook["cells"]
            if cell["cell_type"] == "code"]


def shrink(source: str, epochs: int) -> str:
    """Make the notebook's own settings small enough to run in a test."""
    return (source
            .replace("IMAGE_SIZE      = 320 if IS_GPU else 160", "IMAGE_SIZE      = 96")
            .replace("WIDTH           = 32 if IS_GPU else 16", "WIDTH           = 8")
            .replace("MAX_EPOCHS      = 40 if IS_GPU else 6", f"MAX_EPOCHS      = {epochs}")
            .replace("BATCH_SIZE      = 8 if IS_GPU else 4", "BATCH_SIZE      = 2")
            .replace("TIME_BUDGET_MIN = 90 if IS_GPU else 45", "TIME_BUDGET_MIN = 30")
            .replace("batch_size=4, shuffle=False", "batch_size=2, shuffle=False"))


def run_notebook(name: str, notebook: dict, atlas: AtlasStub, work: Path,
                 epochs: int = 2, extra_env: dict | None = None) -> tuple[bool, dict]:
    """Execute every code cell in order. Returns (ok, namespace)."""
    namespace: dict = {"atlas": atlas, "__name__": "__notebook__"}
    for key, value in (extra_env or {}).items():
        os.environ[key] = value

    started = time.time()
    for index, source in enumerate(code_cells(notebook)):
        if source.lstrip().startswith("!pip"):
            continue
        try:
            exec(compile(shrink(source, epochs), f"<{name} cell {index}>", "exec"), namespace)
        except SystemExit as exc:
            check(f"{name}: cell {index} runs", False, f"SystemExit: {exc}")
            return False, namespace
        except Exception as exc:  # noqa: BLE001
            check(f"{name}: cell {index} runs", False, f"{type(exc).__name__}: {exc}")
            import traceback
            traceback.print_exc()
            return False, namespace
    check(f"{name}: every code cell runs", True,
          f"{len(code_cells(notebook))} cells in {time.time() - started:.1f}s")
    return True, namespace


def main() -> int:
    fast = "--fast" in sys.argv
    epochs = 1 if fast else 2

    from app.services import notebook_factory as nf

    work_root = ROOT / ".nbtest"
    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir()
    work = work_root / "work"
    work.mkdir()

    print(f"{BOLD}Corrosion playground: five notebooks, executed{RESET}")
    print("=" * 78)

    data = build_subset(work_root / "data",
                        {"train": 12 if fast else 24, "val": 6, "test": 6}, fast)
    check("dataset available", any((data / s).is_dir() for s in ("train", "val", "test")),
          str(data))

    os.environ["ATLAS_WORK"] = str(work)
    os.environ["CORROSION_DATA"] = str(data)
    builders = {slug: builder for slug, _, _, builder in nf.CORROSION_NOTEBOOKS}
    check("five notebooks are shipped", len(builders) == 5, ", ".join(builders))

    cwd = Path.cwd()
    os.chdir(work_root)
    try:
        # ---------------------------------------------------------- 1. EDA
        print(f"\n{BOLD}1. Preprocessing & EDA{RESET}")
        eda = AtlasStub()
        ok, namespace = run_notebook("eda", builders["corrosion-1-eda"](), eda, work, epochs)
        if ok:
            check("dataset was discovered", eda.said("dataset root:"),
                  next((line for line in eda.logs if "dataset root" in line), ""))
            check("label space was inferred",
                  namespace["space"].num_classes >= 2,
                  f"{namespace['space'].num_classes} classes, "
                  f"background={namespace['space'].has_background}")
            check("manifest written for the next notebook", (work / "manifest.json").exists())
            check("class distribution charted",
                  (work / "reports" / "class_distribution.png").exists())
            check("sample overlays rendered",
                  (work / "reports" / "sample_overlays.png").exists())
            check("class weights are normalised and damped",
                  abs(float(namespace["weights"][namespace["weights"] > 0].mean()) - 1.0) < 0.05,
                  f"mean {float(namespace['weights'][namespace['weights'] > 0].mean()):.3f}")
            check("EDA finished cleanly", eda.status == "succeeded")

        # ---------------------------------------------------------- 2. training
        print(f"\n{BOLD}2. Training{RESET}")
        train = AtlasStub()
        ok, namespace = run_notebook("training", builders["corrosion-2-training"](),
                                     train, work, epochs)
        if ok:
            check("training streamed per-epoch metrics", len(train.metrics) >= epochs,
                  f"{len(train.metrics)} metric calls")
            epoch_rows = [m for m in train.metrics if "epoch" in m]
            if epoch_rows:
                check("metrics carry the tracked fields",
                      all(k in epoch_rows[0] for k in
                          ("epoch", "train_loss", "val_loss", "val_mean_iou", "val_mean_dice")),
                      str(sorted(epoch_rows[0])))
            check("best checkpoint written", (work / "checkpoints" / "best.pt").exists())
            check("resumable state written", (work / "checkpoints" / "last.pt").exists())
            check("history exported", (work / "history.csv").exists()
                  and (work / "history.json").exists())
            check("training curve rendered", (work / "reports" / "training_curve.png").exists())
            check("reused the manifest rather than re-scanning",
                  train.said("manifest loaded from notebook 1"))

        # ------------------------------------------------- 2b. resume after a kill
        print(f"\n{BOLD}2b. Resuming after a disconnect{RESET}")
        resumed = AtlasStub()
        ok, namespace = run_notebook("training-resume", builders["corrosion-2-training"](),
                                     resumed, work, epochs + 1)
        if ok:
            check("picked up from the saved epoch instead of restarting",
                  resumed.said("resuming from epoch"),
                  next((line for line in resumed.logs if "resuming" in line), "no resume log"))
            check("history kept the earlier epochs",
                  len(namespace.get("history", [])) == epochs + 1,
                  f"{len(namespace.get('history', []))} rows after {epochs}+1 epochs")

        # ---------------------------------------------------------- 3. evaluation
        print(f"\n{BOLD}3. Evaluation{RESET}")
        evaluate = AtlasStub()
        ok, namespace = run_notebook("evaluation", builders["corrosion-3-evaluation"](),
                                     evaluate, work, epochs)
        if ok:
            check("test metrics computed",
                  any("test_mean_iou" in m for m in evaluate.metrics),
                  str(next((m for m in evaluate.metrics if "test_mean_iou" in m), {})))
            check("per-class report written", (work / "reports" / "report.json").exists())
            check("confusion matrix exported", (work / "reports" / "confusion.csv").exists())
            check("failure cases rendered", (work / "reports" / "failure_cases.png").exists())
            check("per-image scores kept", (work / "reports" / "per_image_iou.json").exists())
            check("loaded the checkpoint training wrote",
                  evaluate.said("evaluating checkpoint from epoch"))

        # ---------------------------------------------------------- 4. inference
        print(f"\n{BOLD}4. Inference{RESET}")
        infer = AtlasStub()
        ok, namespace = run_notebook("inference", builders["corrosion-4-inference"](),
                                     infer, work, epochs)
        if ok:
            check("predictor loaded the checkpoint", infer.said("predictor ready"),
                  next((line for line in infer.logs if "predictor ready" in line), ""))
            check("single-image confidence reported",
                  any("single_image_confidence" in m for m in infer.metrics))
            check("batch predictions exported",
                  (work / "reports" / "batch_predictions.csv").exists())
            check("prediction figure rendered",
                  (work / "reports" / "inference_single.png").exists())
            prediction = namespace.get("pred")
            check("prediction is at the photograph's own resolution",
                  prediction is not None
                  and prediction.mask.shape[::-1] == namespace["image"].size,
                  f"mask {getattr(prediction, 'mask', None) is not None and prediction.mask.shape}")

        # ---------------------------------------------------------- 5. deployment
        print(f"\n{BOLD}5. Deployment{RESET}")
        deploy = AtlasStub()
        ok, namespace = run_notebook("deployment", builders["corrosion-5-deployment"](),
                                     deploy, work, epochs)
        if ok:
            bundle = work / "deploy" / "corrosion-segmentation-app"
            for name in ("app.py", "corrosion_kit.py", "best.pt", "requirements.txt"):
                check(f"bundle carries {name}", (bundle / name).exists())
            check("evaluation report shipped with the app", (bundle / "report.json").exists())
            check("bundle self-check passed every automatable rule",
                  namespace.get("failed") == [],
                  str(namespace.get("failed")))
            check("bundle was zipped for upload",
                  namespace.get("archive") is not None and Path(namespace["archive"]).exists(),
                  f"{Path(namespace['archive']).stat().st_size:,} bytes"
                  if namespace.get("archive") else "")
            check("the app's own Predictor loads the shipped checkpoint",
                  namespace.get("probe_ok") is True)
            check("deployment finished cleanly", deploy.status == "succeeded")

        # ------------------------------------------------- standalone (no bridge)
        print(f"\n{BOLD}Standalone: no ATLAS bridge injected{RESET}")
        standalone: dict = {"__name__": "__notebook__"}
        boot = code_cells(builders["corrosion-1-eda"]())[0]
        try:
            exec(compile(boot, "<standalone boot>", "exec"), standalone)
            check("bootstrap supplies its own atlas stand-in",
                  "atlas" in standalone and hasattr(standalone["atlas"], "metric"))
            check("and still finds the dataset",
                  standalone["resolve_dataset"]().exists())
        except Exception as exc:  # noqa: BLE001
            check("bootstrap runs without a bridge", False, f"{type(exc).__name__}: {exc}")
    finally:
        os.chdir(cwd)
        os.environ.pop("CORROSION_DATA", None)
        os.environ.pop("ATLAS_WORK", None)

    keep = "--keep" in sys.argv
    if not keep:
        shutil.rmtree(work_root, ignore_errors=True)

    total = _passed + _failed
    print()
    if _failed:
        print(f"{RED}{BOLD}=== {_passed}/{total} passed, {_failed} failed ==={RESET}")
    else:
        print(f"{GREEN}{BOLD}=== {_passed}/{total} passed ==={RESET}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Execute the ATLAS playground notebook's real code against a real dataset.

A notebook that only renders is not proof of anything. This pulls the code cells
straight out of `notebook_factory.corrosion_segmentation_notebook()`, stubs the
`atlas` bridge the platform injects, points it at a small generated dataset and
runs them in order.

If a cell raises, the notebook an intern opens is broken, and this fails.

    python tests/test_notebook.py
"""
from __future__ import annotations

import shutil
import sys
import types
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

    def __init__(self, dataset_zip: Path):
        self._zip = dataset_zip
        self.logs: list[str] = []
        self.metrics: list[dict] = []
        self.artifacts: list[str] = []
        self.status: str | None = None

    def log(self, *args):
        self.logs.append(" ".join(str(a) for a in args))

    def metric(self, **kw):
        self.metrics.append(kw)

    def dataset(self):
        return str(self._zip)

    def artifact(self, path):
        self.artifacts.append(str(path))

    def finish(self, status="succeeded"):
        self.status = status


def main() -> int:
    from make_sample_data import generate

    work = ROOT / ".nbtest"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()

    print(f"{BOLD}Notebook execution test{RESET}")
    print("=" * 74)

    # ---- a dataset zip, exactly as a student would upload -----------------
    raw = work / "raw"
    generate(raw, count=24, size=64, seed=11)
    zip_path = shutil.make_archive(str(work / "dataset"), "zip", str(raw))
    check("dataset zip built", Path(zip_path).exists(),
          f"{Path(zip_path).stat().st_size:,} bytes")

    # ---- pull the code cells out of the generator -------------------------
    from app.services import notebook_factory as nf

    nb = nf.corrosion_segmentation_notebook()
    cells = [("".join(c["source"]), c["cell_type"]) for c in nb["cells"]]
    code_cells = [src for src, kind in cells if kind == "code"]
    check("notebook generates cells", len(cells) >= 20,
          f"{len(cells)} cells, {len(code_cells)} of them code")

    # ---- run them ---------------------------------------------------------
    atlas = AtlasStub(Path(zip_path))
    env: dict = {
        "atlas": atlas,
        "device": "cpu",
        "__name__": "__notebook__",
    }

    cwd = Path.cwd()
    import os
    os.chdir(work)
    try:
        for i, src in enumerate(code_cells):
            # The pip cell and the torch/CUDA banner are environment setup, not
            # logic. Skip installs; run everything else for real.
            if src.lstrip().startswith("!pip"):
                continue
            if "torch.cuda.is_available()" in src and "atlas.log(\"torch\"" in src:
                continue
            # Shrink the training loop so this finishes in seconds.
            src = src.replace("EPOCHS = 40", "EPOCHS = 2")
            src = src.replace("SIZE = 512", "SIZE = 64")
            src = src.replace("width=64", "width=8")
            src = src.replace("num_workers=2", "num_workers=0")
            try:
                exec(compile(src, f"<cell {i}>", "exec"), env)
            except Exception as exc:  # noqa: BLE001
                check(f"cell {i} runs", False, f"{type(exc).__name__}: {exc}")
                import traceback
                traceback.print_exc()
                break
        else:
            check("every code cell runs", True, f"{len(code_cells)} cells")
    finally:
        os.chdir(cwd)

    # ---- did it do the right things? --------------------------------------
    check("dataset was discovered",
          any("image/mask pairs" in m for m in atlas.logs),
          next((m for m in atlas.logs if "pairs" in m), "no pair log"))

    check("label space was inferred",
          any("NUM_CLASSES" in m for m in atlas.logs),
          next((m for m in atlas.logs if "NUM_CLASSES" in m), ""))

    check("background was detected, not assumed",
          any("unlisted background" in m for m in atlas.logs),
          next((m for m in atlas.logs if "background" in m and "unlisted" in m), ""))

    check("model reports its shape",
          any("shape check" in m for m in atlas.logs),
          next((m for m in atlas.logs if "shape check" in m), ""))

    check("training streamed metrics", len(atlas.metrics) >= 2,
          f"{len(atlas.metrics)} metric calls")

    if atlas.metrics:
        first = atlas.metrics[0]
        check("metrics carry the tracked fields",
              all(k in first for k in ("epoch", "train_loss", "val_loss",
                                       "val_mean_iou", "val_mean_dice")),
              str(sorted(first)))

    check("a checkpoint was written",
          (work / "corrosion_unet_best.pt").exists(),
          f"{(work / 'corrosion_unet_best.pt').stat().st_size:,} bytes"
          if (work / "corrosion_unet_best.pt").exists() else "missing")

    check("per-class report written", (work / "report.json").exists())
    check("preview images written",
          (work / "previews").is_dir() and any((work / "previews").iterdir()))
    check("artifacts registered", len(atlas.artifacts) >= 2, str(atlas.artifacts[:4]))
    check("run finished cleanly", atlas.status == "succeeded", f"status={atlas.status}")

    # The checkpoint the notebook saves must load in the deployment app.
    ckpt = work / "corrosion_unet_best.pt"
    if ckpt.exists():
        from corrosion.inference import Predictor
        from PIL import Image
        import numpy as np

        p = Predictor(ckpt, device="cpu")
        check("notebook checkpoint loads in the app",
              len(p.class_names) >= 15, f"{len(p.class_names)} classes")
        out = p.predict(Image.fromarray(
            (np.random.rand(70, 90, 3) * 255).astype(np.uint8)))
        check("and produces a prediction",
              out.mask.shape == (70, 90) and 0 < out.mean_confidence <= 1,
              f"mask {out.mask.shape}, confidence {out.mean_confidence:.1%}")

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

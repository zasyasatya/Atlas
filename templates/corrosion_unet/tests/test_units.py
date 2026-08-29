#!/usr/bin/env python3
"""Unit tests for the corrosion package.

These check the pieces in isolation, with hand-built inputs whose correct answer
is known by arithmetic rather than by running the model. Run:

    python tests/test_units.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import torch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corrosion import (  # noqa: E402
    Augment, ConfusionMatrix, CorrosionDataset, DiceLoss, build_loss,
    build_model, class_weights, discover, find_classes, inspect_labels,
    split_flat,
)
from corrosion.data import Split  # noqa: E402
from corrosion.inference import Predictor  # noqa: E402

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"
_passed = _failed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global _passed, _failed
    if ok:
        _passed += 1
        print(f"  {GREEN}[PASS]{RESET} {name} {DIM}{detail}{RESET}")
    else:
        _failed += 1
        print(f"  {RED}[FAIL]{RESET} {name} {DIM}{detail}{RESET}")


def near(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) < tol


# --------------------------------------------------------------------------
def test_metrics() -> None:
    print("\n-- metrics --")

    # Perfect prediction: IoU must be exactly 1 for every class present.
    cm = ConfusionMatrix(3, ["bg", "a", "b"])
    truth = np.array([[0, 0, 1], [1, 2, 2]])
    cm.update(truth, truth)
    r = cm.compute()
    check("perfect prediction scores IoU 1.0", near(r.mean_iou, 1.0), f"mIoU={r.mean_iou}")
    check("perfect prediction scores accuracy 1.0", near(r.pixel_accuracy, 1.0))

    # Hand-computable case: 4 pixels, one wrong.
    #   truth [0,0,1,1]  pred [0,0,0,1]
    #   class0: tp=2 fp=1 fn=0 -> 2/3;  class1: tp=1 fp=0 fn=1 -> 1/2
    cm = ConfusionMatrix(2, ["bg", "a"])
    cm.update(np.array([0, 0, 1, 1]), np.array([0, 0, 0, 1]))
    r = cm.compute()
    check("IoU matches hand calculation",
          near(r.per_class_iou["bg"], 2 / 3) and near(r.per_class_iou["a"], 0.5),
          f"bg={r.per_class_iou['bg']:.4f} a={r.per_class_iou['a']:.4f}")
    check("mean IoU averages the two", near(r.mean_iou, (2 / 3 + 0.5) / 2))
    check("pixel accuracy is 3/4", near(r.pixel_accuracy, 0.75))

    # A class nobody annotated must not drag the mean down.
    cm = ConfusionMatrix(3, ["bg", "a", "never"])
    cm.update(np.array([0, 1]), np.array([0, 1]))
    r = cm.compute()
    check("absent classes excluded from the mean", near(r.mean_iou, 1.0),
          f"mIoU={r.mean_iou}, present={r.present}")
    check("absent class still reported with 0 support", r.support["never"] == 0)

    # Accumulation across batches must equal one big batch.
    a = ConfusionMatrix(2, ["x", "y"])
    a.update(np.array([0, 1]), np.array([0, 0]))
    a.update(np.array([1, 1]), np.array([1, 0]))
    b = ConfusionMatrix(2, ["x", "y"])
    b.update(np.array([0, 1, 1, 1]), np.array([0, 0, 1, 0]))
    check("batched accumulation equals one pass", np.array_equal(a.matrix, b.matrix))

    # Out-of-range labels are dropped, not crashed on.
    cm = ConfusionMatrix(2, ["x", "y"])
    cm.update(np.array([0, 1, 99]), np.array([0, 1, 1]))
    check("out-of-range labels ignored", int(cm.matrix.sum()) == 2, f"counted {int(cm.matrix.sum())}")

    # torch tensors accepted directly
    cm = ConfusionMatrix(2, ["x", "y"])
    cm.update(torch.tensor([0, 1]), torch.tensor([0, 1]))
    check("accepts torch tensors", near(cm.compute().mean_iou, 1.0))


def test_model() -> None:
    print("\n-- model --")
    m = build_model(num_classes=16, width=16)
    x = torch.randn(2, 3, 128, 128)
    y = m(x)
    check("output keeps input resolution", y.shape == (2, 16, 128, 128), str(tuple(y.shape)))
    check("output has one channel per class", y.shape[1] == 16)

    check("odd input sizes survive skip padding",
          m(torch.randn(1, 3, 150, 150)).shape == (1, 16, 150, 150))
    check("non-square input works",
          m(torch.randn(1, 3, 224, 160)).shape == (1, 16, 224, 160))

    pred = m.predict(torch.randn(1, 3, 64, 64))
    check("predict returns class indices", pred.shape == (1, 64, 64) and pred.dtype == torch.int64)
    check("predicted indices stay in range", bool((pred >= 0).all() and (pred < 16).all()))

    small, big = build_model(16, width=16), build_model(16, width=32)
    check("wider model has more parameters",
          big.count_parameters() > small.count_parameters() * 3,
          f"{small.count_parameters():,} vs {big.count_parameters():,}")

    # Gradients must reach the first layer, or the encoder is not learning.
    m.zero_grad()
    m(torch.randn(1, 3, 64, 64)).mean().backward()
    first = next(m.inc.parameters())
    check("gradients reach the first layer",
          first.grad is not None and bool(first.grad.abs().sum() > 0))


def test_losses() -> None:
    print("\n-- losses --")
    logits_perfect = torch.zeros(1, 3, 4, 4)
    target = torch.zeros(1, 4, 4, dtype=torch.long)
    target[0, :2] = 1
    for c in range(3):
        logits_perfect[0, c][target[0] == c] = 20.0

    dice = DiceLoss()
    good = dice(logits_perfect, target)
    check("dice near zero when prediction is right", good.item() < 0.02, f"loss={good.item():.5f}")

    wrong = torch.zeros(1, 3, 4, 4)
    wrong[0, 2] = 20.0
    bad = dice(wrong, target)
    # Not 1.0: with smooth=1 and 8 pixels per class the best a fully wrong
    # prediction can score is 1 - (2*0+1)/(8+1) = 0.8889. The smoothing term
    # is deliberate - it keeps the gradient finite when a class is absent.
    check("dice high when prediction is wrong", bad.item() > 0.85, f"loss={bad.item():.5f}")
    check("smoothing is what caps it below 1.0",
          near(DiceLoss(smooth=1e-8)(wrong, target).item(), 1.0, 1e-4),
          f"unsmoothed={DiceLoss(smooth=1e-8)(wrong, target).item():.5f}")
    check("wrong scores worse than right", bad.item() > good.item())

    combo = build_loss("combo")
    cl = combo(logits_perfect, target)
    check("combo loss is finite and non-negative", torch.isfinite(cl) and cl.item() >= 0,
          f"loss={cl.item():.5f}")

    check("ce loss builds", isinstance(build_loss("ce"), torch.nn.CrossEntropyLoss))
    try:
        build_loss("nonsense")
        check("unknown loss name rejected", False)
    except ValueError:
        check("unknown loss name rejected", True)

    # Loss must be differentiable.
    lg = torch.randn(1, 3, 8, 8, requires_grad=True)
    build_loss("combo")(lg, torch.randint(0, 3, (1, 8, 8))).backward()
    check("combo loss is differentiable", lg.grad is not None and bool(lg.grad.abs().sum() > 0))


def test_data_discovery() -> None:
    print("\n-- data discovery --")
    tmp = Path(tempfile.mkdtemp())
    try:
        # split layout: root/train/images + root/train/masks
        for split, n in (("train", 4), ("val", 2)):
            (tmp / split / "images").mkdir(parents=True)
            (tmp / split / "masks").mkdir(parents=True)
            for i in range(n):
                Image.fromarray(np.zeros((8, 8, 3), np.uint8)).save(tmp / split / "images" / f"i{i}.jpg")
                m = np.zeros((8, 8), np.uint8)
                m[0, 0] = 3
                Image.fromarray(m).save(tmp / split / "masks" / f"i{i}.png")

        splits = discover(tmp)
        check("finds train and val", set(splits) == {"train", "val"}, str(sorted(splits)))
        check("pairs the right counts", len(splits["train"]) == 4 and len(splits["val"]) == 2)
        check("matches .jpg to .png", splits["train"].masks[0].suffix == ".png")

        # "valid" must normalise to "val"
        (tmp / "valid" / "images").mkdir(parents=True)
        (tmp / "valid" / "masks").mkdir(parents=True)
        Image.fromarray(np.zeros((8, 8, 3), np.uint8)).save(tmp / "valid" / "images" / "z.jpg")
        Image.fromarray(np.zeros((8, 8), np.uint8)).save(tmp / "valid" / "masks" / "z.png")
        check("'valid' is normalised to 'val'", "val" in discover(tmp))

        check("missing directory returns empty", discover(tmp / "nope") == {})
    finally:
        shutil.rmtree(tmp)

    # flat layout gets split on request
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "images").mkdir()
        (tmp / "masks").mkdir()
        for i in range(20):
            Image.fromarray(np.zeros((8, 8, 3), np.uint8)).save(tmp / "images" / f"i{i}.jpg")
            Image.fromarray(np.zeros((8, 8), np.uint8)).save(tmp / "masks" / f"i{i}.png")
        flat = discover(tmp)
        check("flat layout reads as 'all'", set(flat) == {"all"}, str(sorted(flat)))

        out = split_flat(flat, (0.8, 0.1, 0.1))
        total = sum(len(s) for s in out.values())
        check("flat split keeps every image", total == 20, f"{total} of 20")
        check("flat split makes three parts", set(out) == {"train", "val", "test"})

        overlap = set(out["train"].images) & set(out["test"].images)
        check("splits do not overlap", not overlap)

        again = split_flat(discover(tmp), (0.8, 0.1, 0.1))
        check("split is deterministic", [p.name for p in again["test"].images]
              == [p.name for p in out["test"].images])
    finally:
        shutil.rmtree(tmp)


def test_class_detection() -> None:
    print("\n-- class detection --")
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "train" / "images").mkdir(parents=True)
        (tmp / "train" / "masks").mkdir(parents=True)
        names = [f"c{i}" for i in range(15)]
        (tmp / "classes.txt").write_text("\n".join(names))
        for i in range(3):
            Image.fromarray(np.zeros((8, 8, 3), np.uint8)).save(tmp / "train" / "images" / f"i{i}.jpg")
            m = np.zeros((8, 8), np.uint8)
            m[0, :] = 15          # highest index present
            m[1, :] = 7
            Image.fromarray(m).save(tmp / "train" / "masks" / f"i{i}.png")

        found, src = find_classes(tmp)
        check("reads classes.txt", found == names, f"{len(found)} names from {src.name if src else None}")

        space = inspect_labels(discover(tmp), found)
        check("infers unlisted background", space.has_background, space.source)
        check("network needs 16 channels", space.num_classes == 16, f"num_classes={space.num_classes}")
        check("background prepended to names", space.class_names[0] == "background")
        check("original names shift by one", space.class_names[1] == "c0")

        freq = space.frequencies()
        check("frequencies sum to 1", near(sum(freq.values()), 1.0, 1e-6), f"sum={sum(freq.values()):.6f}")
    finally:
        shutil.rmtree(tmp)

    # 15 values, no background: 0..14 all real classes
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "images").mkdir()
        (tmp / "masks").mkdir()
        names = [f"c{i}" for i in range(15)]
        (tmp / "classes.txt").write_text("\n".join(names))
        for i in range(2):
            Image.fromarray(np.zeros((8, 8, 3), np.uint8)).save(tmp / "images" / f"i{i}.jpg")
            m = np.full((8, 8), 14, np.uint8)
            m[0, 0] = 0
            Image.fromarray(m).save(tmp / "masks" / f"i{i}.png")
        space = inspect_labels(discover(tmp), names)
        check("15 values means no background", not space.has_background, space.source)
        check("network needs 15 channels", space.num_classes == 15, f"num_classes={space.num_classes}")
    finally:
        shutil.rmtree(tmp)

    # JSON class list
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "classes.json").write_text('{"names": ["alpha", "beta"]}')
        found, _ = find_classes(tmp)
        check("reads classes.json", found == ["alpha", "beta"], str(found))
    finally:
        shutil.rmtree(tmp)

    # data.yaml inline list
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "data.yaml").write_text("nc: 2\nnames: [rust, weld]\n")
        found, _ = find_classes(tmp)
        check("reads data.yaml", found == ["rust", "weld"], str(found))
    finally:
        shutil.rmtree(tmp)


def test_dataset() -> None:
    print("\n-- dataset --")
    tmp = Path(tempfile.mkdtemp())
    try:
        imgs, msks = [], []
        for i in range(6):
            ip = tmp / f"i{i}.jpg"
            mp = tmp / f"m{i}.png"
            Image.fromarray((np.random.rand(40, 40, 3) * 255).astype(np.uint8)).save(ip)
            arr = np.zeros((40, 40), np.uint8)
            arr[10:20, 10:20] = 5
            Image.fromarray(arr).save(mp)
            imgs.append(ip)
            msks.append(mp)

        ds = CorrosionDataset(imgs, msks, size=32)
        x, y = ds[0]
        check("image tensor is CHW float", x.shape == (3, 32, 32) and x.dtype == torch.float32,
              str(tuple(x.shape)))
        check("mask tensor is HW long", y.shape == (32, 32) and y.dtype == torch.int64)
        check("mask keeps exact class indices", set(y.unique().tolist()) <= {0, 5},
              str(sorted(y.unique().tolist())))
        check("image is normalised, not 0-1", float(x.min()) < -0.5)
        check("length matches input", len(ds) == 6)

        # Resizing a mask must never invent a class between two indices.
        big = CorrosionDataset(imgs, msks, size=97)
        check("odd resize keeps indices valid", set(big[0][1].unique().tolist()) <= {0, 5},
              str(sorted(big[0][1].unique().tolist())))

        aug = CorrosionDataset(imgs, msks, size=32, augment=Augment(32, train=True, seed=1))
        xa, ya = aug[0]
        check("augmented shapes unchanged", xa.shape == (3, 32, 32) and ya.shape == (32, 32))
        check("augmentation keeps class indices", set(ya.unique().tolist()) <= {0, 5})

        try:
            CorrosionDataset(imgs, msks[:3], size=32)
            check("mismatched lengths rejected", False)
        except ValueError:
            check("mismatched lengths rejected", True)

        w = class_weights(ds, num_classes=8)
        check("class weights sized to classes", w.shape == (8,), str(tuple(w.shape)))
        check("absent classes weigh zero", float(w[7]) == 0.0)
        check("rarer class outweighs common one", float(w[5]) > float(w[0]),
              f"w[5]={float(w[5]):.3f} w[0]={float(w[0]):.3f}")
        check("weights are capped", float(w.max()) <= 10.0)
    finally:
        shutil.rmtree(tmp)


def test_inference_contract() -> None:
    print("\n-- inference --")
    tmp = Path(tempfile.mkdtemp())
    try:
        names = ["background"] + [f"c{i}" for i in range(15)]
        model = build_model(num_classes=16, width=16)
        ckpt = tmp / "best.pt"
        torch.save({"model": model.state_dict(), "class_names": names,
                    "config": {"image_size": 64, "width": 16, "depth": 4},
                    "epoch": 3, "mean_iou": 0.42}, ckpt)

        p = Predictor(ckpt, device="cpu")
        check("checkpoint restores class names", p.class_names == names, f"{len(p.class_names)} names")
        check("checkpoint restores image size", p.image_size == 64)

        # numpy is (H, W); PIL .size is (W, H). An array of (80, 50, 3) is an
        # image 50 wide and 80 tall, so the mask array must be (80, 50).
        img = Image.fromarray((np.random.rand(80, 50, 3) * 255).astype(np.uint8))
        check("test image is 50 wide, 80 tall", img.size == (50, 80), str(img.size))
        out = p.predict(img)
        check("mask returned at input resolution", out.mask.shape == (80, 50),
              f"{out.mask.shape} for a {img.size[0]}x{img.size[1]} (WxH) image")
        check("confidence matches mask shape", out.confidence.shape == out.mask.shape)
        check("confidence is a probability", 0.0 <= out.confidence.min() <= out.confidence.max() <= 1.0)
        check("every class gets a share", len(out.class_share) == 16)
        check("shares sum to 1", near(sum(out.class_share.values()), 1.0, 1e-3),
              f"sum={sum(out.class_share.values()):.5f}")
        check("dominant excludes background", not out.dominant.startswith("background"),
              f"dominant={out.dominant}")

        ov = p.overlay(img, out.mask)
        check("overlay matches the photo size", ov.size == img.size, f"{ov.size} vs {img.size}")
        check("legend covers every class", len(p.legend()) == 16)
        check("metadata reports parameters", p.metadata()["parameters"] > 0)

        try:
            Predictor(tmp / "missing.pt")
            check("missing checkpoint raises", False)
        except FileNotFoundError:
            check("missing checkpoint raises", True)
    finally:
        shutil.rmtree(tmp)


def main() -> int:
    print("Unit tests: corrosion U-Net")
    print("=" * 74)
    test_metrics()
    test_model()
    test_losses()
    test_data_discovery()
    test_class_detection()
    test_dataset()
    test_inference_contract()
    test_app_source()

    total = _passed + _failed
    print()
    if _failed:
        print(f"{RED}=== {_passed}/{total} passed, {_failed} failed ==={RESET}")
    else:
        print(f"{GREEN}=== {_passed}/{total} passed ==={RESET}")
    return 1 if _failed else 0



# ---------------------------------------------------------------- app.py
def test_app_source() -> None:
    """Streamlit executes app.py top to bottom, so a helper called at module
    level must be defined above its call site. A function defined at the bottom
    and called inside a `with tab:` block raises NameError the moment the user
    clicks that widget - and only then, which is how it slipped past the
    end-to-end test."""
    import ast
    src = (Path(__file__).resolve().parents[1] / "app.py").read_text()

    try:
        tree = ast.parse(src)
        ok = True
    except SyntaxError as exc:
        ok = False
        check("app.py parses", False, str(exc))
        return
    check("app.py parses", ok)

    # module-level definitions and the line they appear on
    defined_at: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined_at[node.name] = node.lineno
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    defined_at.setdefault(t.id, node.lineno)

    # line ranges of every function body - calls in there run later, so they
    # are allowed to reference names defined further down
    bodies = [(n.lineno, getattr(n, "end_lineno", n.lineno))
              for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name, line = node.func.id, node.lineno
            if name in defined_at and line < defined_at[name]:
                inside_function = any(a <= line <= b for a, b in bodies)
                if not inside_function:
                    problems.append(f"{name}() used on line {line}, "
                                    f"defined on line {defined_at[name]}")
    check("every helper is defined before it runs", not problems,
          "; ".join(problems) if problems else "no forward references")

    names = [n.name for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    check("_png_bytes is a module-level helper", "_png_bytes" in names,
          f"{len(names)} module-level functions")

    # the rubric requires both input modes and all four doc sections
    check("app offers single and bulk input",
          "file_uploader" in src and "accept_multiple_files" in src)
    low = src.lower()
    for section in ("model limitations", "dataset details",
                    "model architecture", "evaluation results"):
        check(f"documentation covers {section}", section in low)
    check("app reports a confidence score", "confidence" in src.lower())

if __name__ == "__main__":
    sys.exit(main())

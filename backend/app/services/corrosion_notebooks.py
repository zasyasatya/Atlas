"""The five playground notebooks for Topic 6 - corrosion type segmentation.

One notebook per stage, because one notebook that does everything cannot be
re-run: an intern who wants to look at a prediction should not have to sit
through training again, and a Colab session that dies during evaluation should
not lose the trained model.

    1. corrosion-1-eda           preprocessing + exploratory analysis
    2. corrosion-2-training      U-Net training, resumable
    3. corrosion-3-evaluation    test metrics, per class, failure cases
    4. corrosion-4-inference     load a checkpoint and segment new photographs
    5. corrosion-5-deployment    assemble, self-check and ship the web app

Every notebook shares one bootstrap cell that makes it run in three places
without edits:

  * **ATLAS run** - the platform injects its bridge cell above ours, so
    ``atlas.log``/``metric``/``artifact`` stream into the run timeline.
  * **Local Jupyter** - no bridge, so the bootstrap defines a stand-in and finds
    the dataset by walking up the directory tree.
  * **Plain Colab** - the bootstrap mounts Drive, keeps every checkpoint and
    every artifact there, and resumes from them after a disconnect.

The shared library the notebooks import (`corrosion_kit.py`) is a real file in
`templates/corrosion_unet/`, embedded here at build time. That way the notebook
carries its own copy - it works on a Colab that cannot reach this server - while
there is still exactly one source of truth to maintain and test.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

KIT_PATH = (Path(__file__).resolve().parents[3] / "templates" / "corrosion_unet"
            / "corrosion_kit.py")
APP_PATH = (Path(__file__).resolve().parents[3] / "templates" / "corrosion_app" / "app.py")

DATASET_NAME = "corrovision-dataset-v1_semantic_export"


def _read(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if "'''" in text:
        # The bootstrap embeds this file inside an r'''...''' literal.
        raise ValueError(f"{path.name} must not contain a triple single-quote")
    return text


# --------------------------------------------------------------------------
# nbformat helpers
# --------------------------------------------------------------------------
def _cell_id() -> str:
    return uuid.uuid4().hex[:12]


def _md(source: str) -> dict[str, Any]:
    return {"id": _cell_id(), "cell_type": "markdown", "metadata": {},
            "source": source.strip().splitlines(keepends=True)}


def _code(source: str) -> dict[str, Any]:
    return {"id": _cell_id(), "cell_type": "code", "metadata": {}, "execution_count": None,
            "outputs": [], "source": source.strip().splitlines(keepends=True)}


def _nb(cells: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11"},
            "accelerator": "GPU",
            "colab": {"provenance": [], "gpuType": "T4"},
            "atlas": {"generated": True, "topic": "corrosion-segmentation"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


# --------------------------------------------------------------------------
# the shared bootstrap
# --------------------------------------------------------------------------
_HEADER = """# {title}

**ATLAS playground - Topic 6, Corrosion Type Segmentation - notebook {index} of 5**

| # | Notebook | What it does |
|---|---|---|
| 1 | Preprocessing & EDA | find the data, read the masks, decide the preprocessing |
| 2 | Training | train the U-Net, resumable after a disconnect |
| 3 | Evaluation | per-class IoU on the test split, and where it fails |
| 4 | Inference | segment new photographs, single and in bulk |
| 5 | Deployment | build the web app and ship it to the portal |

{lead}

**Runs anywhere.** Launched from ATLAS, the platform injects its bridge and this
notebook streams logs, metrics and artifacts into your run timeline. Downloaded
and opened in local Jupyter, or opened straight in Colab, the first cell
supplies a stand-in and everything still works.
"""

_BOOT_TAIL = '''
import json, os, shutil, subprocess, sys, time, zipfile
from pathlib import Path

NOTEBOOK = "{notebook}"
DATASET_NAME = "{dataset}"
IN_COLAB = "google.colab" in sys.modules

# --------------------------------------------------------------------------
# 1. The ATLAS bridge, or a stand-in for it.
# --------------------------------------------------------------------------
# The platform prepends a bridge cell when it dispatches a run. Nothing injects
# it when you open this file in local Jupyter or straight in Colab, so every
# atlas.* call below would raise NameError. This shim keeps the notebook honest
# in both worlds: same code, output goes to the screen instead of the timeline.
if "atlas" not in dir():
    class _StandaloneAtlas:
        def __init__(self):
            self.metrics = {{}}

        def log(self, *parts):
            print(*parts)

        def metric(self, **kwargs):
            self.metrics.update(kwargs)
            print("[metric] " + "  ".join("%s=%s" % kv for kv in kwargs.items()))

        def dataset(self):
            return None                 # no run, so no attached dataset

        def artifact(self, path):
            print("[artifact] %s" % path)

        def finish(self, status="succeeded", error=""):
            print("[run] %s %s" % (status, error))

    atlas = _StandaloneAtlas()
    print("No ATLAS bridge - running standalone. Metrics print here instead.")

# --------------------------------------------------------------------------
# 2. Where work is kept, so a dropped connection costs nothing.
# --------------------------------------------------------------------------
# On Colab everything under /content is wiped when the runtime recycles - which
# it does on idle, on a browser refresh, and after 12 hours no matter what. So
# checkpoints, reports and manifests go to Google Drive, and every notebook
# reads the same folder. Reconnect, re-run, carry on from the last epoch.
def _drive_work():
    if not IN_COLAB:
        return None
    try:
        from google.colab import drive
        drive.mount("/content/drive", force_remount=False)
        path = Path("/content/drive/MyDrive/atlas_corrosion")
        path.mkdir(parents=True, exist_ok=True)
        return path
    except Exception as exc:
        print("Drive not mounted (%s) - work stays on this runtime and is lost "
              "when it recycles." % exc)
        return None

if os.environ.get("ATLAS_WORK"):
    WORK = Path(os.environ["ATLAS_WORK"]).expanduser().resolve()
else:
    WORK = _drive_work() or Path("atlas_corrosion").resolve()
WORK.mkdir(parents=True, exist_ok=True)

CKPT_DIR = WORK / "checkpoints"
REPORT_DIR = WORK / "reports"
CACHE_DIR = Path("/content/corrosion_data") if IN_COLAB else (WORK / "data")
for folder in (CKPT_DIR, REPORT_DIR, CACHE_DIR):
    folder.mkdir(parents=True, exist_ok=True)

BEST_CKPT = CKPT_DIR / "best.pt"
LAST_CKPT = CKPT_DIR / "last.pt"
MANIFEST = WORK / "manifest.json"

# --------------------------------------------------------------------------
# 3. Dependencies. Colab already has torch; a bare local kernel may not.
# --------------------------------------------------------------------------
def _ensure(module, pip_args=None):
    try:
        __import__(module)
        return True
    except ImportError:
        pass
    args = pip_args or [module]
    print("installing %s ..." % " ".join(args))
    code = subprocess.call([sys.executable, "-m", "pip", "install", "-q"] + args)
    try:
        __import__(module)
        return True
    except ImportError:
        print("could not install %s (pip exit %s)" % (module, code))
        return False

_ensure("numpy")
_ensure("PIL", ["pillow"])
_ensure("torch", ["torch", "--index-url", "https://download.pytorch.org/whl/cpu"]
        if not IN_COLAB else ["torch"])
_ensure("matplotlib")

# --------------------------------------------------------------------------
# 4. The shared library, written next to this notebook and imported.
# --------------------------------------------------------------------------
# Every notebook and the deployed app use these same functions. Writing the file
# rather than pasting the code into five notebooks is what stops them drifting
# apart - and the deployment notebook ships this exact file inside the bundle.
KIT_FILE = WORK / "corrosion_kit.py"
KIT_FILE.write_text(KIT_SOURCE, encoding="utf-8")
if str(WORK) not in sys.path:
    sys.path.insert(0, str(WORK))
for _stale in [m for m in list(sys.modules) if m == "corrosion_kit"]:
    del sys.modules[_stale]
import corrosion_kit as ck

# --------------------------------------------------------------------------
# 5. The dataset, from whichever of the five places it turns out to live in.
# --------------------------------------------------------------------------
def resolve_dataset():
    # a) an explicit path wins, always
    env = os.environ.get("CORROSION_DATA", "")
    if env and ck.looks_like_dataset(env):
        atlas.log("dataset: CORROSION_DATA -> %s" % env)
        return Path(env)

    # b) already unpacked by an earlier notebook or an earlier session
    for candidate in (CACHE_DIR / DATASET_NAME, CACHE_DIR, WORK / "data" / DATASET_NAME):
        if ck.looks_like_dataset(candidate):
            atlas.log("dataset: reusing %s" % candidate)
            return Path(candidate)

    # c) sitting in the checkout next to the notebook (the local case)
    local = ck.find_local_dataset(DATASET_NAME)
    if local:
        atlas.log("dataset: found on disk -> %s" % local)
        return Path(local)

    # d) a zip parked in the work folder - on Colab, drop the export in
    #    Drive/atlas_corrosion once and every future session reuses it
    zips = sorted(WORK.glob("*.zip")) + sorted((WORK / "data").glob("*.zip"))
    if zips:
        atlas.log("dataset: unpacking %s" % zips[0].name)
        return Path(ck.extract_zip(zips[0], CACHE_DIR))

    # e) the dataset attached to this ATLAS run
    downloaded = atlas.dataset()
    if downloaded and Path(downloaded).exists():
        cached = WORK / ("%s.zip" % DATASET_NAME)
        try:
            if not cached.exists():
                shutil.copy(downloaded, cached)      # keep it for next session
        except OSError:
            cached = Path(downloaded)
        atlas.log("dataset: downloaded from ATLAS -> unpacking")
        return Path(ck.extract_zip(cached, CACHE_DIR))

    # f) a plain URL, for a cohort sharing one link
    url = os.environ.get("CORROSION_DATA_URL", "")
    if url:
        import urllib.request
        target = WORK / ("%s.zip" % DATASET_NAME)
        if not target.exists():
            atlas.log("dataset: downloading %s" % url)
            urllib.request.urlretrieve(url, target)
        return Path(ck.extract_zip(target, CACHE_DIR))

    # g) nothing found: run on a synthetic stand-in rather than fail
    atlas.log("NO DATASET FOUND - generating a small synthetic stand-in so this "
              "notebook still runs. Numbers from it mean nothing.")
    atlas.log("Fix: attach the dataset in ATLAS, put the export zip in %s, or "
              "set CORROSION_DATA to its folder." % WORK)
    return Path(ck.make_sample_dataset(CACHE_DIR / "synthetic", count=40, size=96))

atlas.log("notebook %s | work dir %s | colab=%s" % (NOTEBOOK, WORK, IN_COLAB))
'''


def _boot_cell(notebook: str) -> str:
    """The bootstrap cell: the kit source, then the setup that uses it."""
    kit = _read(KIT_PATH)
    return ("# --- ATLAS corrosion pipeline: shared setup (safe to re-run) -----------------\n"
            "# corrosion_kit.py, written to the work folder and imported below. Read it\n"
            "# there, or in ATLAS under Pipeline Library -> Corrosion U-Net.\n"
            "KIT_SOURCE = r'''\n" + kit + "'''\n"
            + _BOOT_TAIL.format(notebook=notebook, dataset=DATASET_NAME))


_COLAB_MD = """## Running this on Colab without losing your work

Colab disconnects. Idle timeouts, a closed laptop lid, a browser refresh, the
12-hour ceiling - all of them wipe `/content`. The bootstrap cell above is built
around that instead of hoping it will not happen:

| Problem | What the notebook does |
|---|---|
| Runtime recycles | Everything lands in `Drive/MyDrive/atlas_corrosion`, not `/content` |
| Training dies mid-run | A checkpoint is written **every epoch**, with optimiser and scheduler state |
| Re-running wastes hours | The training cell resumes from the last epoch instead of starting over |
| A save is interrupted | Checkpoints are written to a temp file and renamed, so a killed session cannot leave a corrupt one |
| Re-downloading the dataset | The export zip is cached in Drive and unpacked to fast local disk each session |
| Colab's 12-hour ceiling | `TIME_BUDGET_MIN` stops the loop cleanly before it hits; re-run the cell to continue |

So the recovery procedure after a disconnect is: **reconnect, Runtime -> Run
all, wait.** The bootstrap remounts Drive, the training cell picks up at the
epoch it reached, and nothing is repeated.

Two habits that make disconnects rarer:

1. **Runtime -> Change runtime type -> T4 GPU** before you start. A GPU run
   finishes in minutes what a CPU run takes hours over - and a shorter run is a
   run that has less time to drop.
2. Keep the tab visible. Colab reclaims idle runtimes; the keepalive below
   helps, but a backgrounded tab on a sleeping laptop still dies.
"""

_KEEPALIVE = '''
# Colab reclaims a runtime it thinks is idle. This clicks the reconnect button
# for you every minute, which keeps a long training cell alive through a coffee
# break. It is not magic: a closed laptop or a lost network still ends the
# session - that is what the checkpoints are for.
if IN_COLAB:
    try:
        from IPython.display import Javascript, display
        display(Javascript(
            "function AtlasKeepAlive(){"
            "  const b = document.querySelector('colab-connect-button');"
            "  if (b && b.shadowRoot) {"
            "    const c = b.shadowRoot.querySelector('#connect');"
            "    if (c) { c.click(); }"
            "  }"
            "}"
            "setInterval(AtlasKeepAlive, 60000);"))
        print("keepalive armed - reconnect is clicked every 60s while this tab is open")
    except Exception as exc:
        print("keepalive not armed: %s" % exc)
else:
    print("not on Colab - no keepalive needed")
'''


# --------------------------------------------------------------------------
# 1. preprocessing and EDA
# --------------------------------------------------------------------------
def eda_notebook() -> dict[str, Any]:
    return _nb([
        _md(_HEADER.format(
            title="1. Preprocessing & Exploratory Analysis", index=1,
            lead="Before a single epoch: what is actually in this dataset, what do the "
                 "mask files mean, and which preprocessing decisions does that force?")),

        _code(_boot_cell("01-eda")),

        _md("""## 1. Find the data, and say where it came from

The bootstrap looked in five places, in order: an explicit `CORROSION_DATA`
path, a copy already unpacked in the work folder, the checkout on disk, a zip
parked in the work folder, and the dataset attached to this ATLAS run. Whichever
one hit, the run log now says so - which matters, because "the model got worse"
is very often "the notebook silently picked up different data"."""),

        _code("""DATA_ROOT = resolve_dataset()

splits = ck.split_flat(ck.discover(DATA_ROOT))
class_names_file, class_file_path = ck.find_classes(DATA_ROOT)
space = ck.inspect_labels(splits, class_names_file)

print(ck.summarise(splits, space))
print()
print("class list file:", class_file_path or "none found - classes inferred from the masks")
atlas.log("dataset root:", DATA_ROOT)
atlas.metric(train_images=len(splits.get("train", [])),
             val_images=len(splits.get("val", [])),
             test_images=len(splits.get("test", [])),
             num_classes=space.num_classes)"""),

        _md("""### What just happened to the class list

The exporter wrote 15 names. The masks contain values 0-15, which is 16 distinct
labels. One more value than names means index `0` is a background nobody bothered
to list, so the notebook prepends it - and the network needs **16** output
channels, not 15.

Get this wrong in the other direction and every prediction is shifted by one
class: `crevice_mild` gets reported as `crevice_moderate`, the metrics look
plausible, and nothing tells you. That is why this is checked against the pixels
rather than assumed."""),

        _md("""## 2. Is every pair actually usable?

Four failures are common in an annotation export, and all four are silent:

* an image with no mask (or the reverse) - the pair is dropped, and you never
  notice your training set shrank
* a mask whose dimensions do not match its image - the labels are offset
* a mask saved as RGB or with a palette, so pixel values are colours, not indices
* a class in `classes.txt` that no annotator ever drew

Check now. Finding these after a six-hour training run is expensive."""),

        _code("""from PIL import Image
import numpy as np

problems = []
checked = 0
sample_pairs = list(zip(splits["train"].images, splits["train"].masks))[:200]

for img_path, msk_path in sample_pairs:
    try:
        with Image.open(img_path) as im:
            iw, ih = im.size
        with Image.open(msk_path) as mk:
            mw, mh = mk.size
            mode = mk.mode
    except Exception as exc:
        problems.append("%s unreadable: %s" % (img_path.name, exc))
        continue
    checked += 1
    if (iw, ih) != (mw, mh):
        problems.append("%s: image %dx%d but mask %dx%d" % (img_path.name, iw, ih, mw, mh))
    if mode not in ("L", "P", "I", "I;16"):
        problems.append("%s: mask mode is %s - values may be colours, not class indices"
                        % (msk_path.name, mode))

print("checked %d pairs" % checked)
if problems:
    print("%d problem(s):" % len(problems))
    for line in problems[:10]:
        print("  -", line)
else:
    print("no size or mode problems in the sample")

unused = [space.class_names[i] for i in range(space.num_classes)
          if space.pixel_counts.get(i, 0) == 0]
print("classes never drawn in the sampled masks:", unused or "none")
atlas.metric(pairs_checked=checked, pair_problems=len(problems))"""),

        _md("""## 3. The imbalance, which decides almost everything downstream

Read the percentages below before doing anything else. Background takes roughly
three quarters of every photograph, and the fifteen real classes split what is
left - unevenly, so the rarest class is a fraction of a percent.

Two consequences, and both change the code you write later:

1. **Accuracy is the wrong metric.** Predict "background" everywhere and you
   score ~74% while detecting nothing. Notebook 3 reports IoU per class for
   exactly this reason.
2. **The loss needs help.** Left alone, gradient descent takes the easy win.
   Class weights and a Dice term are what stop it."""),

        _code("""import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

freq = space.frequencies()
ordered = sorted(freq.items(), key=lambda kv: -kv[1])

print("%-46s%12s%10s" % ("class", "pixels", "share"))
print("-" * 68)
for name, share in ordered:
    idx = space.class_names.index(name)
    print("%-46s%12s%9.2f%%" % (name, format(space.pixel_counts.get(idx, 0), ","), share * 100))

fig, ax = plt.subplots(figsize=(9, 5))
names = [n for n, _ in ordered if not ck.is_background(n)]
shares = [freq[n] * 100 for n in names]
colours = ["#%02x%02x%02x" % ck.PALETTE[space.class_names.index(n) % len(ck.PALETTE)]
           for n in names]
ax.barh(range(len(names)), shares, color=colours)
ax.set_yticks(range(len(names)))
ax.set_yticklabels(names, fontsize=8)
ax.invert_yaxis()
ax.set_xlabel("share of all pixels (%)  -  background excluded")
ax.set_title("Class imbalance: %.1f%% of pixels are background"
             % (freq.get("background", 0) * 100))
fig.tight_layout()
chart = REPORT_DIR / "class_distribution.png"
fig.savefig(chart, dpi=110)
plt.close(fig)
print("\\nsaved", chart)
atlas.artifact(str(chart))
atlas.metric(background_share=round(freq.get("background", 0), 4),
             rarest_class_share=round(min(s for n, s in freq.items()
                                          if not ck.is_background(n)), 6))"""),

        _md("""## 4. Photograph geometry

Inspection photographs come off phones and inspection cameras at whatever
resolution the technician had. The model needs one fixed square input, so
something has to give. Measure the spread before picking the number."""),

        _code("""sizes = []
for img_path in splits["train"].images[:200]:
    with Image.open(img_path) as im:
        sizes.append(im.size)

widths = np.array([w for w, _ in sizes])
heights = np.array([h for _, h in sizes])
ratios = widths / np.maximum(heights, 1)

print("width  : min %d  median %d  max %d" % (widths.min(), np.median(widths), widths.max()))
print("height : min %d  median %d  max %d" % (heights.min(), np.median(heights), heights.max()))
print("aspect : min %.2f  median %.2f  max %.2f" % (ratios.min(), np.median(ratios), ratios.max()))
print()
print("Resizing to a square distorts anything that is not 1:1. That is acceptable")
print("here - corrosion texture survives a modest stretch, and the alternative")
print("(pad to square) feeds the network a border of dead pixels in every batch.")
atlas.metric(median_width=int(np.median(widths)), median_height=int(np.median(heights)))"""),

        _md("""## 5. Look at the photographs

Numbers do not tell you whether the annotator drew what you think they drew.
Overlay a few masks on their images and check with your own eyes."""),

        _code("""def overlay_pair(img_path, msk_path, size=256):
    photo = Image.open(img_path).convert("RGB").resize((size, size), Image.BILINEAR)
    mask = np.asarray(Image.open(msk_path).resize((size, size), Image.NEAREST))
    if mask.ndim == 3:
        mask = mask[..., 0]
    return photo, mask

picked = []
seen = set()
for img_path, msk_path in zip(splits["train"].images, splits["train"].masks):
    mask = ck.read_mask(msk_path)
    present = [int(v) for v in np.unique(mask) if v > 0]
    if present and present[0] not in seen:
        seen.add(present[0])
        picked.append((img_path, msk_path, present[0]))
    if len(picked) == 6:
        break

fig, axes = plt.subplots(2, len(picked), figsize=(3 * len(picked), 6.4))
for col, (img_path, msk_path, cls) in enumerate(picked):
    photo, mask = overlay_pair(img_path, msk_path)
    axes[0][col].imshow(photo)
    axes[0][col].set_title(space.class_names[cls][:26], fontsize=8)
    axes[1][col].imshow(ck.overlay(photo, mask, alpha=0.55))
    for row in (0, 1):
        axes[row][col].axis("off")
axes[0][0].set_ylabel("photo")
fig.suptitle("Top: inspection photograph.  Bottom: annotated mask overlaid.", fontsize=10)
fig.tight_layout()
grid = REPORT_DIR / "sample_overlays.png"
fig.savefig(grid, dpi=110)
plt.close(fig)
print("saved", grid)
atlas.artifact(str(grid))"""),

        _md("""## 6. The preprocessing decisions, written down

Everything above forces four choices. Notebook 2 applies them; here is why they
are what they are.

**Resize masks with NEAREST, never bilinear.** Smoothing interpolation averages
neighbouring values, and halfway between class 3 and class 4 is 3.5 - not a
class. Bilinear resizing of a mask silently invents labels along every boundary.

**Normalise with ImageNet statistics.** Not because the encoder is pretrained
here, but because the deployed app must scale its input identically. A mismatch
between training and serving is invisible in every metric you compute and ruins
every prediction a user sees.

**Augment conservatively.** Flips, 90-degree rotations and mild brightness or
contrast jitter model the things that genuinely vary - camera angle, time of
day, work lighting. Blur and elastic warping rewrite *texture*, and texture is
how `mild` is distinguished from `moderate`. Augmenting that away teaches the
model that the difference does not matter.

**Damp the class weights.** Median-frequency balancing is the textbook recipe
and it overcorrects badly here: background ends up weighted ~68x below the rest
and the model answers by painting corrosion everywhere. Square-rooting the ratio
and clamping the spread to 8:1 boosts rare classes without collapsing the
majority one."""),

        _code("""weights = ck.class_weights(splits["train"].masks, space.num_classes,
                          size=256, sample=150)

pairs = sorted(zip(space.class_names, weights.tolist()), key=lambda kv: -kv[1])
print("%-46s%10s" % ("class", "weight"))
print("-" * 58)
for name, weight in pairs:
    print("%-46s%10.3f" % (name, weight))
print()
print("background weight  %.3f" % weights[0].item())
print("spread (max/min)   %.1fx" % (weights.max().item() /
                                    max(weights[weights > 0].min().item(), 1e-9)))
print("mean               %.3f  <- normalised, so the learning rate need not change"
      % weights[weights > 0].mean().item())"""),

        _md("""## 7. Hand the next notebook everything it needs

The manifest records which files are in which split, what the classes are, and
the weights computed above. Notebook 2 reads it instead of re-scanning three
thousand masks - and, more importantly, it trains on *exactly* the split
analysed here. Recomputing a split in each notebook is how test images end up in
the training set."""),

        _code("""manifest_path = ck.write_manifest(
    MANIFEST, splits, space, DATA_ROOT,
    extra={"class_weights": weights.tolist(), "kit_version": ck.__version__,
           "created": time.strftime("%Y-%m-%d %H:%M:%S")})

print("wrote", manifest_path, "(%s bytes)" % format(manifest_path.stat().st_size, ","))
print()
print("Next: notebook 2, Training. It reads this manifest, so run it from the")
print("same work folder (%s)." % WORK)
atlas.artifact(str(manifest_path))
atlas.finish("succeeded")"""),
    ])


# --------------------------------------------------------------------------
# 2. training
# --------------------------------------------------------------------------
def training_notebook() -> dict[str, Any]:
    return _nb([
        _md(_HEADER.format(
            title="2. Training the U-Net", index=2,
            lead="Train the segmentation model, and survive a Colab disconnect while "
                 "doing it. Every epoch is checkpointed; re-running the training cell "
                 "resumes rather than restarts.")),

        _code(_boot_cell("02-training")),

        _md(_COLAB_MD),

        _code(_KEEPALIVE),

        _md("""## 1. Settings

The defaults are sized for a **Colab T4**: 320px inputs, a 32-channel U-Net,
40 epochs. On CPU they are far too heavy - drop `IMAGE_SIZE` to 160, `WIDTH` to
16 and `MAX_EPOCHS` to about 6, and expect roughly ten minutes per epoch on the
full training set.

`TIME_BUDGET_MIN` is the anti-disconnect setting. The loop stops cleanly when
the budget runs out, leaving a checkpoint behind; re-running the cell continues
from there. Set it comfortably under Colab's ceiling so a session never ends
mid-epoch."""),

        _code("""import torch

device = ck.pick_device()
IS_GPU = device.type == "cuda"

IMAGE_SIZE      = 320 if IS_GPU else 160   # square side the photographs are resized to
WIDTH           = 32 if IS_GPU else 16     # channels at the first U-Net level
DEPTH           = 4                        # downsampling steps
BATCH_SIZE      = 8 if IS_GPU else 4
MAX_EPOCHS      = 40 if IS_GPU else 6
LEARNING_RATE   = 3e-4
TIME_BUDGET_MIN = 90 if IS_GPU else 45     # stop cleanly before Colab does
TRAIN_LIMIT     = 0                        # >0 trains on a subset, for a fast smoke test
SEED            = 42

print("device:", ck.describe_device(device))
if not IS_GPU:
    print("No GPU. Colab: Runtime -> Change runtime type -> T4 GPU, then re-run.")
atlas.log("training config: %dpx, width %d, batch %d, up to %d epochs, budget %d min"
          % (IMAGE_SIZE, WIDTH, BATCH_SIZE, MAX_EPOCHS, TIME_BUDGET_MIN))"""),

        _md("""## 2. Data

Read the manifest notebook 1 wrote. If it is missing - because you jumped
straight here - the dataset is re-scanned, and the split will match as long as
the export ships its own train/val/test folders (this one does)."""),

        _code("""record = ck.read_manifest(MANIFEST)
if record:
    DATA_ROOT = Path(record["root"])
    splits, space = record["splits"], record["space"]
    weights_list = record["raw"].get("class_weights")
    atlas.log("manifest loaded from notebook 1: %s" % MANIFEST)
else:
    atlas.log("no manifest - re-scanning the dataset (run notebook 1 first for the EDA)")
    DATA_ROOT = resolve_dataset()
    splits = ck.split_flat(ck.discover(DATA_ROOT))
    names, _ = ck.find_classes(DATA_ROOT)
    space = ck.inspect_labels(splits, names)
    weights_list = None

if "val" not in splits and "train" in splits:
    # Training blind is worse than training on slightly less data.
    train = splits["train"]
    cut = max(1, len(train) // 10)
    splits["val"] = ck.Split("val", train.images[:cut], train.masks[:cut])
    splits["train"] = ck.Split("train", train.images[cut:], train.masks[cut:])
    atlas.log("no validation split in the export - held out %d training images" % cut)

train_split, val_split = splits["train"], splits["val"]
if TRAIN_LIMIT:
    train_split = ck.Split("train", train_split.images[:TRAIN_LIMIT],
                           train_split.masks[:TRAIN_LIMIT])

NUM_CLASSES = space.num_classes
CLASS_NAMES = space.class_names

train_ds = ck.CorrosionDataset(train_split.images, train_split.masks, size=IMAGE_SIZE,
                               augment=ck.Augment(IMAGE_SIZE, train=True, seed=SEED))
val_ds = ck.CorrosionDataset(val_split.images, val_split.masks, size=IMAGE_SIZE)

print("train %d | val %d | classes %d" % (len(train_ds), len(val_ds), NUM_CLASSES))
atlas.log("train %d, val %d, %d classes" % (len(train_ds), len(val_ds), NUM_CLASSES))"""),

        _md("""## 3. The network

The U-Net is defined in `corrosion_kit.py`, which the bootstrap wrote next to
this notebook - the same file the evaluation, inference and deployment notebooks
import, and the same one that ships inside the deployed app. Read it there in
full; the cell below prints the two classes that matter so you can read them
here too.

```
input ---> 64 ---------------------------------> 64 ---> output
            |                                    ^
            v                                    |
           128 ------------------------------> 128
            |                                    ^
            v                                    |
           256 --------------------------> 256
            |                              ^
            v                              |
                       512 (bottleneck)
```

The left side downsamples: each step halves the resolution and doubles the
channels, answering *what is in this image* while discarding *exactly where*.
The right side climbs back to full resolution. The horizontal arrows are skip
connections, and they are the entire trick - they hand the encoder's sharp early
feature maps straight across, so the decoder can combine "this region is
pitting" with "the edge is exactly here". For a weld-line attack a few pixels
wide, that is the difference between a usable prediction and a smear."""),

        _code("""import inspect

print(inspect.getsource(ck.Up))
print(inspect.getsource(ck.UNet))"""),

        _code("""ck.seed_everything(SEED)     # before build_model: weight init draws from this RNG

model = ck.build_model(NUM_CLASSES, width=WIDTH, depth=DEPTH).to(device)
print("U-Net: %s parameters, %d output channels"
      % (format(model.count_parameters(), ","), NUM_CLASSES))

# The output must be the same height and width as the input. If this line ever
# prints a smaller shape, the decoder is not climbing all the way back up.
with torch.no_grad():
    probe = model(torch.randn(1, 3, 128, 128, device=device))
print("shape check:", tuple(probe.shape), "<- (batch, classes, H, W)")
atlas.metric(parameters=model.count_parameters(), num_classes=NUM_CLASSES)"""),

        _md("""## 4. The loss

Cross-entropy alone optimises average per-pixel correctness, and with ~74%
background the cheapest way to raise that average is to predict background more
often. Two corrections, used together:

**Damped class weights** - rare classes count for more, but the correction is
square-rooted and clamped to an 8:1 spread. Raw median-frequency balancing puts
background ~68x below everything else, and the model responds by spraying
corrosion across the whole frame.

**Dice loss** - cross-entropy counts pixels; Dice measures region overlap, which
is what IoU actually scores and far less sensitive to imbalance. Early in
training Dice is nearly flat while cross-entropy still gives a usable gradient;
later, Dice is what pushes boundaries into place. Summing them at 0.5/0.5 gets
both behaviours."""),

        _code("""if weights_list:
    class_weight = torch.tensor(weights_list, dtype=torch.float32)
    atlas.log("class weights from the manifest")
else:
    class_weight = ck.class_weights(train_split.masks, NUM_CLASSES, size=IMAGE_SIZE)
    atlas.log("class weights computed here")

class_weight = class_weight.to(device)
loss_fn = ck.build_loss("combo", class_weights=class_weight)

top = sorted(zip(CLASS_NAMES, class_weight.tolist()), key=lambda kv: -kv[1])[:3]
print("loss = 0.5 * weighted cross-entropy + 0.5 * dice")
print("background weight %.3f | heaviest: %s"
      % (class_weight[0].item(), ", ".join("%s=%.2f" % kv for kv in top)))"""),

        _md("""## 5. Train - interruptible, and resumable

The loop below is written to be killed. After every epoch it writes
`checkpoints/last.pt` containing the weights **and** the optimiser, scheduler
and scaler state, the epoch number, the best score so far and the full history.
`checkpoints/best.pt` is written whenever validation mIoU improves.

Both go to the work folder, which is Google Drive on Colab. Saves are atomic - a
temp file, then a rename - so a session that dies mid-write leaves the previous
checkpoint intact rather than a truncated one.

Consequences worth being explicit about:

* Disconnected at epoch 12 of 40? Re-run this cell: it prints "resuming from
  epoch 13" and carries on.
* Hit `TIME_BUDGET_MIN`? Same thing - the loop stops between epochs, on purpose.
* Want to start over? Delete `checkpoints/last.pt`, or set `RESUME = False`.
* Mixed precision is on for CUDA only. It halves memory and speeds training up
  by running most operations in 16-bit while keeping 32-bit weights; the
  `GradScaler` inflates the loss before backprop so small gradients survive the
  narrower format. On CPU it is a slowdown, so it stays off."""),

        _code("""from torch.utils.data import DataLoader

RESUME = True

workers = 2 if (IS_GPU and len(train_ds) > 64) else 0
train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,
                          num_workers=workers, pin_memory=IS_GPU, drop_last=False)
val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False,
                        num_workers=workers, pin_memory=IS_GPU)

optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4)
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=MAX_EPOCHS)
scaler = torch.amp.GradScaler("cuda") if IS_GPU else None

start_epoch, best_iou, history = 1, -1.0, []
state = ck.load_checkpoint(LAST_CKPT, map_location=device) if RESUME else None
if state and state.get("num_classes") == NUM_CLASSES and state.get("width") == WIDTH:
    model.load_state_dict(state["model"])
    optimizer.load_state_dict(state["optimizer"])
    scheduler.load_state_dict(state["scheduler"])
    if scaler is not None and state.get("scaler"):
        scaler.load_state_dict(state["scaler"])
    start_epoch = int(state["epoch"]) + 1
    best_iou = float(state.get("best_iou", -1.0))
    history = list(state.get("history", []))
    atlas.log("resuming from epoch %d (best mIoU so far %.4f)" % (start_epoch, best_iou))
elif state:
    atlas.log("existing checkpoint has a different geometry - starting fresh")

def save_state(epoch):
    ck.save_checkpoint(LAST_CKPT, {
        "model": model.state_dict(), "optimizer": optimizer.state_dict(),
        "scheduler": scheduler.state_dict(),
        "scaler": scaler.state_dict() if scaler is not None else None,
        "epoch": epoch, "best_iou": best_iou, "history": history,
        "class_names": CLASS_NAMES, "num_classes": NUM_CLASSES, "width": WIDTH,
        "config": {"image_size": IMAGE_SIZE, "width": WIDTH, "depth": DEPTH,
                   "batch_size": BATCH_SIZE, "lr": LEARNING_RATE, "seed": SEED},
    })

print("epochs %d..%d | checkpoints -> %s" % (start_epoch, MAX_EPOCHS, CKPT_DIR))"""),

        _code("""deadline = time.time() + TIME_BUDGET_MIN * 60
stopped_early = False

for epoch in range(start_epoch, MAX_EPOCHS + 1):
    epoch_started = time.time()

    model.train()
    running, seen = 0.0, 0
    for x, y in train_loader:
        x = x.to(device, non_blocking=True)
        y = y.to(device, non_blocking=True)
        optimizer.zero_grad(set_to_none=True)
        if scaler is not None:
            with torch.autocast("cuda", dtype=torch.float16):
                loss = loss_fn(model(x), y)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
        else:
            loss = loss_fn(model(x), y)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        running += loss.item() * x.size(0)
        seen += x.size(0)
    scheduler.step()

    model.eval()
    matrix = ck.ConfusionMatrix(NUM_CLASSES, CLASS_NAMES)
    val_running, val_seen = 0.0, 0
    with torch.no_grad():
        for x, y in val_loader:
            x = x.to(device, non_blocking=True)
            y = y.to(device, non_blocking=True)
            logits = model(x)
            val_running += loss_fn(logits, y).item() * x.size(0)
            val_seen += x.size(0)
            matrix.update(y, logits.argmax(1))
    result = matrix.compute()

    row = {"epoch": epoch,
           "train_loss": round(running / max(seen, 1), 4),
           "val_loss": round(val_running / max(val_seen, 1), 4),
           "val_mean_iou": round(result["mean_iou"], 4),
           "val_mean_dice": round(result["mean_dice"], 4),
           "val_pixel_acc": round(result["pixel_acc"], 4),
           "seconds": round(time.time() - epoch_started, 1)}
    history.append(row)
    atlas.metric(**row)

    improved = result["mean_iou"] > best_iou
    if improved:
        best_iou = result["mean_iou"]
        ck.save_checkpoint(BEST_CKPT, {
            "model": model.state_dict(), "class_names": CLASS_NAMES,
            "epoch": epoch, "mean_iou": best_iou,
            "config": {"image_size": IMAGE_SIZE, "width": WIDTH, "depth": DEPTH},
        })
    save_state(epoch)

    atlas.log("epoch %d/%d  train %.4f  val %.4f  mIoU %.4f%s  (%.0fs)"
              % (epoch, MAX_EPOCHS, row["train_loss"], row["val_loss"],
                 row["val_mean_iou"], "  <- best" if improved else "", row["seconds"]))

    if time.time() > deadline and epoch < MAX_EPOCHS:
        stopped_early = True
        atlas.log("time budget of %d min reached at epoch %d. Nothing is lost - "
                  "re-run this cell to continue from epoch %d."
                  % (TIME_BUDGET_MIN, epoch, epoch + 1))
        break

(WORK / "history.json").write_text(json.dumps(history, indent=2))
with open(WORK / "history.csv", "w", newline="") as fh:
    if history:
        fh.write(",".join(history[0].keys()) + "\\n")
        for row in history:
            fh.write(",".join(str(v) for v in row.values()) + "\\n")

print()
print("best validation mIoU %.4f | %d epoch(s) recorded" % (best_iou, len(history)))
print("checkpoint:", BEST_CKPT)
if stopped_early:
    print("Stopped on the time budget - re-run the cell above to continue.")"""),

        _md("""## 6. Read the curve, not just the last number

Three things to look for:

* **Validation loss rising while training loss falls** - the model is memorising
  the training photographs. More augmentation, fewer epochs, or a smaller `WIDTH`.
* **mIoU flat near zero after several epochs** - almost always the loss: either
  the class weights collapsed, or the label space is wrong (check the background
  decision in notebook 1).
* **mIoU still climbing at the last epoch** - the run was cut short. Raise
  `MAX_EPOCHS` and re-run this notebook; it resumes rather than restarts."""),

        _code("""import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

if history:
    epochs = [r["epoch"] for r in history]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))
    ax1.plot(epochs, [r["train_loss"] for r in history], label="train")
    ax1.plot(epochs, [r["val_loss"] for r in history], label="validation")
    ax1.set_xlabel("epoch"); ax1.set_ylabel("loss"); ax1.legend(); ax1.set_title("Loss")
    ax2.plot(epochs, [r["val_mean_iou"] for r in history], color="#8C5B4F", label="mean IoU")
    ax2.plot(epochs, [r["val_mean_dice"] for r in history], color="#4F7D8C", label="mean Dice")
    ax2.set_xlabel("epoch"); ax2.set_ylabel("score"); ax2.legend()
    ax2.set_title("Validation quality")
    fig.tight_layout()
    curve = REPORT_DIR / "training_curve.png"
    fig.savefig(curve, dpi=110)
    plt.close(fig)
    print("saved", curve)
    atlas.artifact(str(curve))

    last = history[-1]
    print("last epoch: train %.4f | val %.4f | mIoU %.4f"
          % (last["train_loss"], last["val_loss"], last["val_mean_iou"]))
else:
    print("no history yet - run the training cell")"""),

        _code("""atlas.metric(best_val_mean_iou=round(best_iou, 4), epochs_completed=len(history))
if BEST_CKPT.exists():
    atlas.artifact(str(BEST_CKPT))
    print("uploaded %s (%s bytes)" % (BEST_CKPT.name, format(BEST_CKPT.stat().st_size, ",")))
print()
print("Next: notebook 3, Evaluation - per-class IoU on the held-out test split.")
atlas.finish("succeeded")"""),
    ])


# --------------------------------------------------------------------------
# 3. evaluation
# --------------------------------------------------------------------------
def evaluation_notebook() -> dict[str, Any]:
    return _nb([
        _md(_HEADER.format(
            title="3. Evaluation", index=3,
            lead="Score the trained model on the held-out test split, per class, and "
                 "find out where it fails. A good mean can hide a class the model "
                 "never gets right.")),

        _code(_boot_cell("03-evaluation")),

        _md("""## 1. Load the checkpoint

`best.pt` carries its own class names and geometry, so nothing here has to be
told how the model was trained. If this cell cannot find a checkpoint, run
notebook 2 first - or point `CHECKPOINT` at a `.pt` you downloaded from an
ATLAS run."""),

        _code("""import torch

CHECKPOINT = BEST_CKPT

state = ck.load_checkpoint(CHECKPOINT, map_location="cpu")
if state is None:
    raise SystemExit("No checkpoint at %s - run notebook 2 (Training) first." % CHECKPOINT)

device = ck.pick_device()
model, CLASS_NAMES, config = ck.model_from_checkpoint(state, device)
IMAGE_SIZE = int(config.get("image_size", 256))
NUM_CLASSES = len(CLASS_NAMES)

print("checkpoint      :", CHECKPOINT)
print("trained epoch   :", state.get("epoch"))
print("validation mIoU : %.4f" % (state.get("mean_iou") or 0.0))
print("classes         :", NUM_CLASSES)
print("input size      : %dpx" % IMAGE_SIZE)
print("device          :", ck.describe_device(device))
atlas.log("evaluating checkpoint from epoch %s" % state.get("epoch"))"""),

        _md("""## 2. The test split

The test split is the only honest number in this notebook. Validation guided
training - every "keep this checkpoint" decision looked at it - so validation
mIoU is mildly optimistic by construction. Test data the model has never been
scored on is what you report."""),

        _code("""record = ck.read_manifest(MANIFEST)
if record:
    splits = record["splits"]
    DATA_ROOT = Path(record["root"])
else:
    DATA_ROOT = resolve_dataset()
    splits = ck.split_flat(ck.discover(DATA_ROOT))

test_split = splits.get("test") or splits.get("val")
if test_split is None:
    raise SystemExit("No test or validation split found.")

test_ds = ck.CorrosionDataset(test_split.images, test_split.masks, size=IMAGE_SIZE)
print("evaluating on the %s split: %d images" % (test_split.name, len(test_ds)))"""),

        _code("""from torch.utils.data import DataLoader

matrix = ck.ConfusionMatrix(NUM_CLASSES, CLASS_NAMES)
loader = DataLoader(test_ds, batch_size=4, shuffle=False)

model.eval()
with torch.no_grad():
    for i, (x, y) in enumerate(loader, start=1):
        matrix.update(y, model(x.to(device)).argmax(1).cpu())
        if i % 20 == 0:
            print("  %d/%d batches" % (i, len(loader)))

result = matrix.compute()
print()
print(matrix.table())

atlas.metric(test_mean_iou=round(result["mean_iou"], 4),
             test_mean_dice=round(result["mean_dice"], 4),
             test_pixel_acc=round(result["pixel_acc"], 4))"""),

        _md("""### How to read that table

**Pixel accuracy is the decoy.** Predicting background everywhere scores ~0.74
on it. If pixel accuracy is high and mean IoU is near zero, the model has learned
to say nothing.

**Per class is where the answer is.** A class with a high IoU is genuinely
detected. A class at 0.00 with non-zero support is a class the model never
finds - and if that class is `pitting`, the model is not fit for purpose no
matter what the mean says.

**Rare classes swing wildly.** A class with a few thousand test pixels can move
0.2 IoU between runs. Read it alongside the support column, not on its own.

**Confusion within a family is expected**; confusion across families is not.
Mistaking `general_moderate` for `general_severe` is a severity judgement humans
also argue about. Mistaking `pitting` for `general` is a real failure - they
imply different repairs."""),

        _code("""import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

report_path = REPORT_DIR / "report.json"
payload = dict(result)
payload["checkpoint"] = str(CHECKPOINT)
payload["split"] = test_split.name
payload["images"] = len(test_ds)
payload["image_size"] = IMAGE_SIZE
report_path.write_text(json.dumps(payload, indent=2))

confusion_path = REPORT_DIR / "confusion.csv"
confusion_path.write_text(matrix.to_csv())

names = [n for n in CLASS_NAMES if result["support"][n] > 0]
scores = [result["per_class_iou"][n] for n in names]
order = np.argsort(scores)
fig, ax = plt.subplots(figsize=(9, 5))
ax.barh(range(len(names)), [scores[i] for i in order],
        color=["#%02x%02x%02x" % ck.PALETTE[CLASS_NAMES.index(names[i]) % len(ck.PALETTE)]
               for i in order])
ax.set_yticks(range(len(names)))
ax.set_yticklabels([names[i] for i in order], fontsize=8)
ax.set_xlabel("IoU on the test split")
ax.set_title("Per-class IoU - mean %.3f" % result["mean_iou"])
fig.tight_layout()
iou_chart = REPORT_DIR / "per_class_iou.png"
fig.savefig(iou_chart, dpi=110)
plt.close(fig)

normalised = matrix.m / np.maximum(matrix.m.sum(axis=1, keepdims=True), 1)
fig, ax = plt.subplots(figsize=(8, 7))
im = ax.imshow(normalised, cmap="magma", vmin=0, vmax=1)
ax.set_xticks(range(NUM_CLASSES)); ax.set_yticks(range(NUM_CLASSES))
ax.set_xticklabels(CLASS_NAMES, rotation=90, fontsize=6)
ax.set_yticklabels(CLASS_NAMES, fontsize=6)
ax.set_xlabel("predicted"); ax.set_ylabel("ground truth")
ax.set_title("Confusion, row-normalised")
fig.colorbar(im, ax=ax, shrink=0.8)
fig.tight_layout()
confusion_chart = REPORT_DIR / "confusion.png"
fig.savefig(confusion_chart, dpi=110)
plt.close(fig)

for path in (report_path, confusion_path, iou_chart, confusion_chart):
    print("saved", path)
    atlas.artifact(str(path))"""),

        _md("""## 3. Where does it actually fail?

Aggregate metrics summarise; they do not explain. Score each test image on its
own, then look at the worst ones. Failures cluster, and the cluster tells you
what to fix: if the bad images are all dark, that is a lighting gap in the
training set, not a model architecture problem."""),

        _code("""per_image = []
with torch.no_grad():
    for i in range(len(test_ds)):
        x, y = test_ds[i]
        pred = model(x.unsqueeze(0).to(device)).argmax(1)[0].cpu()
        single = ck.ConfusionMatrix(NUM_CLASSES, CLASS_NAMES).update(y, pred).compute()
        truth = [CLASS_NAMES[int(v)] for v in np.unique(y.numpy()) if v > 0]
        per_image.append({"index": i,
                          "image": test_ds.images[i].name,
                          "mean_iou": round(single["mean_iou"], 4),
                          "truth": ", ".join(truth) or "background only"})

per_image.sort(key=lambda r: r["mean_iou"])
print("%-42s%10s   %s" % ("worst images", "mIoU", "ground truth"))
print("-" * 96)
for row in per_image[:8]:
    print("%-42s%10.4f   %s" % (row["image"][:40], row["mean_iou"], row["truth"][:44]))
print()
print("%-42s%10s   %s" % ("best images", "mIoU", "ground truth"))
print("-" * 96)
for row in per_image[-5:][::-1]:
    print("%-42s%10.4f   %s" % (row["image"][:40], row["mean_iou"], row["truth"][:44]))

(REPORT_DIR / "per_image_iou.json").write_text(json.dumps(per_image, indent=2))
atlas.artifact(str(REPORT_DIR / "per_image_iou.json"))"""),

        _code("""from PIL import Image

worst = per_image[:3]
best = per_image[-3:][::-1]
picks = worst + best

fig, axes = plt.subplots(3, len(picks), figsize=(3.1 * len(picks), 9))
for col, row in enumerate(picks):
    i = row["index"]
    x, y = test_ds[i]
    with torch.no_grad():
        pred = model(x.unsqueeze(0).to(device)).argmax(1)[0].cpu().numpy().astype(np.uint8)
    photo = Image.open(test_ds.images[i]).convert("RGB").resize((IMAGE_SIZE, IMAGE_SIZE))
    axes[0][col].imshow(photo)
    axes[0][col].set_title("%s\\nmIoU %.3f" % (row["image"][:22], row["mean_iou"]), fontsize=8)
    axes[1][col].imshow(ck.colorise(y.numpy().astype(np.uint8), NUM_CLASSES))
    axes[2][col].imshow(ck.colorise(pred, NUM_CLASSES))
    for r in range(3):
        axes[r][col].axis("off")
axes[0][0].set_ylabel("photo"); axes[1][0].set_ylabel("truth"); axes[2][0].set_ylabel("predicted")
fig.suptitle("Worst three, then best three.  Rows: photograph / ground truth / prediction",
             fontsize=10)
fig.tight_layout()
failures = REPORT_DIR / "failure_cases.png"
fig.savefig(failures, dpi=110)
plt.close(fig)
print("saved", failures)
atlas.artifact(str(failures))"""),

        _md("""## 4. Is it good enough to ship?

There is no universal threshold - it depends on what the app is for. For a
screening tool that flags photographs for a human inspector, useful behaviour
looks like:

* mean IoU clearly above zero and stable between runs
* the frequent, dangerous classes (`pitting`, `general`, `crevice`) individually
  detected rather than carried by background
* failures that are severity confusions inside a family, not family swaps

If a class is at zero, say so in the app's limitations rather than hiding it
behind the mean. A model that admits what it cannot see is usable; one that
quietly misses pitting is not."""),

        _code("""detectable = {n: v for n, v in result["per_class_iou"].items()
              if result["support"][n] > 0 and not ck.is_background(n)}
missed = [n for n, v in detectable.items() if v < 0.01]

print("mean IoU (all present classes) : %.4f" % result["mean_iou"])
print("mean IoU (corrosion only)      : %.4f"
      % (sum(detectable.values()) / max(len(detectable), 1)))
print("classes never detected         : %s" % (", ".join(missed) if missed else "none"))
print()
print("Record these in the app's Documentation tab - notebook 5 copies report.json")
print("into the bundle so the deployed app shows them without you retyping anything.")
atlas.metric(corrosion_mean_iou=round(sum(detectable.values()) / max(len(detectable), 1), 4),
             classes_never_detected=len(missed))
atlas.finish("succeeded")"""),
    ])


# --------------------------------------------------------------------------
# 4. inference
# --------------------------------------------------------------------------
def inference_notebook() -> dict[str, Any]:
    return _nb([
        _md(_HEADER.format(
            title="4. Inference", index=4,
            lead="Point the trained model at photographs it has never seen: one at a "
                 "time, then a whole folder. This is the code the deployed app runs.")),

        _code(_boot_cell("04-inference")),

        _md("""## 1. The Predictor

`ck.Predictor` is the only thing the deployed app imports from this stack. It
loads a checkpoint, rebuilds the network from the geometry stored inside it, and
returns a prediction at the **caller's** resolution - the model works at 256 or
320px internally, but an overlay has to line up with the original photograph.

Everything it needs is in the checkpoint. Nothing here has to be told how the
model was trained, which is what stops a deployment from silently loading a
model with the wrong class list."""),

        _code("""predictor = ck.Predictor(BEST_CKPT, device="cpu")
meta = predictor.metadata()

for key in ("checkpoint", "classes", "image_size", "parameters",
            "trained_epoch", "validation_mean_iou"):
    print("%-22s %s" % (key, meta[key]))
print()
print("legend:")
for row in predictor.legend():
    if row["index"]:
        print("  %2d  %-46s %s" % (row["index"], row["name"], row["color"]))
atlas.log("predictor ready: %d classes, %dpx input" % (meta["classes"], meta["image_size"]))"""),

        _md("""## 2. One photograph

Pick an image the model has not been trained on. The test split is right there;
to use your own, set `IMAGE_PATH` to a file - on Colab, drag it into the file
browser first, or upload it into the work folder on Drive."""),

        _code("""from PIL import Image
import numpy as np

record = ck.read_manifest(MANIFEST)
splits = record["splits"] if record else ck.split_flat(ck.discover(resolve_dataset()))
gallery = (splits.get("test") or splits.get("val") or splits.get("train"))

IMAGE_PATH = None            # set this to your own photograph
image_path = Path(IMAGE_PATH) if IMAGE_PATH else gallery.images[0]

image = Image.open(image_path).convert("RGB")
started = time.time()
pred = predictor.predict(image)
elapsed = time.time() - started

print("image            :", image_path.name)
print("size             : %dx%d" % image.size)
print("dominant class   :", pred.dominant)
print("confidence       : %.1f%% on the dominant class, %.1f%% mean over the image"
      % (pred.dominant_confidence * 100, pred.mean_confidence * 100))
print("corroded area    : %.1f%%" % (float((pred.mask > 0).mean()) * 100))
print("inference        : %.2fs on %s" % (elapsed, meta["device"]))
print()
print("%-46s%10s%12s" % ("class", "area %", "pixels"))
print("-" * 70)
for row in pred.rows(0.001):
    if not ck.is_background(row["class"]):
        print("%-46s%10.2f%12s" % (row["class"], row["share_percent"],
                                   format(row["pixels"], ",")))
atlas.metric(single_image_confidence=round(pred.mean_confidence, 4),
             single_image_seconds=round(elapsed, 3))"""),

        _code("""import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 4, figsize=(16, 4.4))
axes[0].imshow(image); axes[0].set_title("photograph")
axes[1].imshow(predictor.colorise(pred.mask)); axes[1].set_title("predicted classes")
axes[2].imshow(predictor.overlay(image, pred.mask, 0.5)); axes[2].set_title("overlay")
conf = axes[3].imshow(pred.confidence, cmap="viridis", vmin=0, vmax=1)
axes[3].set_title("confidence")
fig.colorbar(conf, ax=axes[3], shrink=0.8)
for ax in axes:
    ax.axis("off")
fig.tight_layout()
single = REPORT_DIR / "inference_single.png"
fig.savefig(single, dpi=110)
plt.close(fig)
print("saved", single)
atlas.artifact(str(single))"""),

        _md("""### Read the confidence map, not just the number

Dark bands trace class boundaries - the model is genuinely unsure exactly where
one class stops. That is honest and expected.

A large dark *region* is different: the model has assigned a class it does not
believe in. In the app that is the case to route to a human. Note also that
softmax confidence is not a calibrated probability: 90% means "this class won
comfortably", not "right nine times out of ten"."""),

        _md("""## 3. A whole folder

Real use is a batch: an inspector comes back with sixty photographs from one
round. Run them all, produce one row per image, and sort by what needs attention
first. This is exactly what the app's bulk tab does."""),

        _code("""batch_paths = list(gallery.images[:12])
rows = []
started = time.time()

for path in batch_paths:
    prediction = predictor.predict(path)
    rows.append({
        "image": path.name,
        "dominant_class": prediction.dominant,
        "confidence": round(prediction.dominant_confidence, 4),
        "mean_confidence": round(prediction.mean_confidence, 4),
        "corroded_area_percent": round(float((prediction.mask > 0).mean()) * 100, 2),
    })

total = time.time() - started
rows.sort(key=lambda r: -r["corroded_area_percent"])

print("%-40s%-30s%8s%10s" % ("image", "dominant", "conf", "area %"))
print("-" * 92)
for row in rows:
    print("%-40s%-30s%8.1f%%%9.1f%%"
          % (row["image"][:38], row["dominant_class"][:28],
             row["confidence"] * 100, row["corroded_area_percent"]))
print()
print("%d images in %.1fs (%.2fs each)" % (len(rows), total, total / max(len(rows), 1)))

csv_path = REPORT_DIR / "batch_predictions.csv"
with open(csv_path, "w", newline="") as fh:
    fh.write(",".join(rows[0].keys()) + "\\n")
    for row in rows:
        fh.write(",".join(str(v) for v in row.values()) + "\\n")
print("saved", csv_path)
atlas.artifact(str(csv_path))
atlas.metric(batch_images=len(rows), seconds_per_image=round(total / max(len(rows), 1), 3))"""),

        _md("""## 4. Which results need a human?

A screening tool earns its keep by being honest about its own uncertainty. Two
simple rules cover most of it:

* **Low confidence** - under about 60% on the dominant class, send it for review.
* **Tiny detections** - a class covering a fraction of a percent of the frame is
  as likely to be noise as a real pit. The app hides those behind an area
  threshold rather than reporting them as findings.

Both thresholds are judgement calls, so they are sliders in the app rather than
constants buried in the code."""),

        _code("""LOW_CONFIDENCE = 0.60
MIN_AREA_PERCENT = 0.1

review = [r for r in rows if r["confidence"] < LOW_CONFIDENCE]
findings = [r for r in rows if r["corroded_area_percent"] >= MIN_AREA_PERCENT]

print("%d/%d images have a finding above %.1f%% area"
      % (len(findings), len(rows), MIN_AREA_PERCENT))
print("%d/%d images fall below %.0f%% confidence and need a human look"
      % (len(review), len(rows), LOW_CONFIDENCE * 100))
for row in review[:5]:
    print("  - %s (%.0f%% on %s)" % (row["image"], row["confidence"] * 100,
                                     row["dominant_class"]))
print()
print("Next: notebook 5, Deployment - the same Predictor behind a web app.")
atlas.metric(low_confidence_images=len(review))
atlas.finish("succeeded")"""),
    ])


# --------------------------------------------------------------------------
# 5. deployment
# --------------------------------------------------------------------------
def deployment_notebook() -> dict[str, Any]:
    app_source = _read(APP_PATH)
    app_cell = ("# The Streamlit app that ships. Read it: it is the whole deliverable.\n"
                "# Also browsable in ATLAS under Pipeline Library -> Corrosion app.\n"
                "APP_SOURCE = r'''\n" + app_source + "'''\n"
                "print('app source: %d lines' % len(APP_SOURCE.splitlines()))")

    return _nb([
        _md(_HEADER.format(
            title="5. Deployment", index=5,
            lead="Turn the checkpoint into the web application the internship is graded "
                 "on: assemble the bundle, self-check it against the five rubric rules, "
                 "and ship it to the ATLAS portal.")),

        _code(_boot_cell("05-deployment")),

        _md("""## 1. What ships

A deployment bundle is a folder, zipped. Six things go in it:

| File | Why |
|---|---|
| `app.py` | the Streamlit interface |
| `corrosion_kit.py` | model + inference, the same file the notebooks used |
| `best.pt` | the trained weights |
| `report.json` | per-class test IoU, so the Documentation tab shows real numbers |
| `history.csv` | the training curve, same reason |
| `requirements.txt` | pinned enough to build, CPU wheels only |

What does **not** go in: the dataset, the notebooks, `last.pt` (it carries
optimiser state and is twice the size for no benefit at serving time), and
anything under `__pycache__`."""),

        _code(app_cell),

        _code("""BUNDLE = WORK / "deploy" / "corrosion-segmentation-app"
if BUNDLE.exists():
    shutil.rmtree(BUNDLE)
BUNDLE.mkdir(parents=True)

(BUNDLE / "app.py").write_text(APP_SOURCE, encoding="utf-8")
shutil.copy(KIT_FILE, BUNDLE / "corrosion_kit.py")

if not BEST_CKPT.exists():
    raise SystemExit("No checkpoint at %s - run notebook 2 (Training) first." % BEST_CKPT)
shutil.copy(BEST_CKPT, BUNDLE / "best.pt")

for name, source in (("report.json", REPORT_DIR / "report.json"),
                     ("history.csv", WORK / "history.csv")):
    if source.exists():
        shutil.copy(source, BUNDLE / name)
    else:
        print("note: %s missing - the Documentation tab will show less "
              "(run notebooks 2 and 3)." % name)

(BUNDLE / "requirements.txt").write_text(
    "--extra-index-url https://download.pytorch.org/whl/cpu\\n"
    "torch>=2.0\\nnumpy>=1.24\\npillow>=10.0\\nstreamlit>=1.36\\npandas>=2.0\\n")

# A handful of example photographs, so a reviewer can click something the
# moment the app opens instead of hunting for a test image.
record = ck.read_manifest(MANIFEST)
if record:
    gallery = record["splits"].get("test") or record["splits"].get("val")
    if gallery:
        (BUNDLE / "examples").mkdir(exist_ok=True)
        for path in gallery.images[:4]:
            shutil.copy(path, BUNDLE / "examples" / path.name)

for path in sorted(BUNDLE.rglob("*")):
    if path.is_file():
        print("  %-34s %10s bytes" % (path.relative_to(BUNDLE).as_posix(),
                                      format(path.stat().st_size, ",")))"""),

        _md("""## 2. Self-check against the rubric

ATLAS scores the bundle the moment you upload it, against five rules. Running
the same checks here means a failure costs seconds instead of a deploy cycle.

| Rule | What it looks for |
|---|---|
| R1 | Streamlit or Gradio in the source |
| R2 | single-entry widgets **and** a bulk file upload |
| R3 | documentation covering limitations, dataset, architecture, evaluation |
| R4 | a confidence score **and** a chart |
| R5 | a Whimsical board URL - attached on the deployment record, not in the code |

R5 is the one that cannot be satisfied from here: paste your board link into the
deployment form. The other four should all pass below."""),

        _code("""import re

source = "\\n".join(p.read_text(errors="ignore") for p in BUNDLE.rglob("*")
                   if p.suffix in {".py", ".md", ".txt", ".json"})

checks = {
    "R1 framework":        r"import\\s+streamlit|streamlit\\s+as\\s+st",
    "R2 single input":     r"st\\.(number_input|text_input|selectbox|slider|form|radio)",
    "R2 bulk input":       r"st\\.file_uploader",
    "R3 limitations":      r"limitation|constraint|out\\s+of\\s+scope",
    "R3 dataset":          r"dataset|data\\s+source",
    "R3 architecture":     r"architecture|unet|u-net",
    "R3 evaluation":       r"\\biou\\b|dice|evaluation|accuracy",
    "R4 confidence":       r"confidence|softmax|probability",
    "R4 chart":            r"st\\.(bar_chart|line_chart|area_chart|pyplot)",
}

failed = []
for label, pattern in checks.items():
    ok = re.search(pattern, source, re.I) is not None
    print("  %-20s %s" % (label, "pass" if ok else "FAIL"))
    if not ok:
        failed.append(label)

print()
if failed:
    print("Fix before deploying:", ", ".join(failed))
else:
    print("4 of 5 rules satisfied by the bundle. R5 needs your Whimsical URL on the")
    print("deployment record - ATLAS asks for it in the deploy form.")
atlas.metric(rubric_checks_passed=len(checks) - len(failed))"""),

        _md("""## 3. Does it actually start?

A bundle that passes the rubric can still fail to boot - a missing import, a
checkpoint that will not load. Two seconds of checking here saves a failed
deployment.

The Streamlit UI itself is not exercised (there is no browser in a notebook),
but the two things that break in practice are: the app's imports, and the
checkpoint loading into the app's Predictor."""),

        _code("""sys.path.insert(0, str(BUNDLE))
probe_ok = True
try:
    probe = ck.Predictor(BUNDLE / "best.pt", device="cpu")
    print("checkpoint loads:", len(probe.class_names), "classes,",
          "%dpx input" % probe.image_size)

    from PIL import Image
    import numpy as np
    demo = Image.fromarray((np.random.rand(96, 128, 3) * 255).astype("uint8"))
    out = probe.predict(demo)
    print("prediction runs :", out.mask.shape, "| confidence %.1f%%"
          % (out.mean_confidence * 100))
except Exception as exc:
    probe_ok = False
    print("BUNDLE IS BROKEN:", type(exc).__name__, exc)

import ast
try:
    ast.parse((BUNDLE / "app.py").read_text(encoding="utf-8"))
    print("app.py parses   : yes")
except SyntaxError as exc:
    probe_ok = False
    print("app.py is invalid:", exc)

print()
print("bundle is deployable" if probe_ok else "fix the errors above before deploying")"""),

        _code("""archive = shutil.make_archive(str(WORK / "corrosion-segmentation-app"), "zip", str(BUNDLE))
archive = Path(archive)
print("zipped:", archive, "(%s bytes)" % format(archive.stat().st_size, ","))
atlas.artifact(str(archive))"""),

        _md("""## 4. Ship it

Two routes. Both end with the app running and listed in the App Portal.

**Through the interface** (what most people do): **Deployment -> New app**,
framework Streamlit, entrypoint `app.py`, paste your Whimsical URL, upload the
zip, press **Deploy**. ATLAS generates a Dockerfile, starts the app, re-runs the
rubric and publishes it to the portal.

**From here**, if this notebook can reach the platform: fill in the three
settings below. It creates the deployment, uploads the bundle, deploys it and
prints the public URL. Credentials are read from the environment when present -
never hard-code them into a notebook you are going to share."""),

        _code("""import getpass
import urllib.request

ATLAS_URL = os.environ.get("ATLAS_PUBLIC_URL", "http://127.0.0.1:8000")
ATLAS_EMAIL = os.environ.get("ATLAS_EMAIL", "")
WHIMSICAL_URL = os.environ.get("WHIMSICAL_URL", "https://whimsical.com/atlas-corrosion-segmentation")
APP_NAME = "Corrosion Segmentation"
DEPLOY_FROM_NOTEBOOK = False        # set True to actually push

def _api(path, data=None, token=None, method=None, headers=None):
    request = urllib.request.Request(ATLAS_URL.rstrip("/") + path, data=data,
                                     method=method or ("POST" if data else "GET"))
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    if token:
        request.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read().decode()
    return json.loads(body) if body else {}

if not DEPLOY_FROM_NOTEBOOK:
    print("DEPLOY_FROM_NOTEBOOK is False - upload %s through the Deployment tab."
          % archive.name)
else:
    email = ATLAS_EMAIL or input("ATLAS email: ")
    password = os.environ.get("ATLAS_PASSWORD") or getpass.getpass("ATLAS password: ")
    auth = _api("/api/auth/login",
                data=json.dumps({"email": email, "password": password}).encode(),
                headers={"Content-Type": "application/json"})
    token = auth["access_token"]

    topics = _api("/api/topics", token=token)
    topic = next(t for t in topics if t["slug"] == "corrosion-segmentation")

    deployment = _api("/api/deployments", token=token,
                      data=json.dumps({"topic_id": topic["id"], "name": APP_NAME,
                                       "framework": "streamlit", "entrypoint": "app.py",
                                       "whimsical_url": WHIMSICAL_URL}).encode(),
                      headers={"Content-Type": "application/json"})
    atlas.log("deployment %s created" % deployment["id"])

    boundary = "----atlasbundle"
    body = (("--%s\\r\\nContent-Disposition: form-data; name=\\"file\\"; "
             "filename=\\"%s\\"\\r\\nContent-Type: application/zip\\r\\n\\r\\n"
             % (boundary, archive.name)).encode()
            + archive.read_bytes()
            + ("\\r\\n--%s--\\r\\n" % boundary).encode())
    _api("/api/deployments/%s/bundle" % deployment["id"], data=body, token=token,
         headers={"Content-Type": "multipart/form-data; boundary=" + boundary})

    result = _api("/api/deployments/%s/deploy" % deployment["id"], data=b"", token=token)
    atlas.log("status %s | readiness %s%% | url %s"
              % (result["status"], result["readiness_score"], result.get("url")))
    for check in result.get("checks", []):
        print("  %-4s %-8s %s" % (check["rule_id"], check["status"], check["detail"][:70]))
    print()
    print("Portal:", ATLAS_URL.rstrip("/") + "/portal")"""),

        _md("""## 5. Before you call it done

- [ ] The app opens and segments a photograph you upload.
- [ ] The bulk tab handles a zip of images.
- [ ] The Documentation tab shows **your** numbers, not the placeholder text -
      that means `report.json` from notebook 3 is in the bundle.
- [ ] Limitations name the classes your model actually misses. Check notebook 3
      for the ones at zero IoU.
- [ ] The deployed URL is on your Whimsical board, and the board URL is on the
      deployment record. That is R5, and it is the rule people forget.
- [ ] The app appears in the **App Portal**."""),

        _code("""print("bundle   :", BUNDLE)
print("zip      :", archive)
print("portal   :", os.environ.get("ATLAS_PUBLIC_URL", "http://127.0.0.1:8000") + "/portal")
print()
print("Everything for this topic lives in %s - checkpoints, reports and the" % WORK)
print("bundle. On Colab that folder is Drive, so it outlives the runtime.")
atlas.finish("succeeded")"""),
    ])


NOTEBOOKS = [
    ("corrosion-1-eda", "1. Preprocessing & EDA",
     "Find the dataset, read what the masks actually mean, measure the class "
     "imbalance and fix the preprocessing decisions the rest of the pipeline depends on.",
     eda_notebook),
    ("corrosion-2-training", "2. Training the U-Net",
     "Train the segmentation model with per-epoch checkpoints on Google Drive, so a "
     "Colab disconnect costs nothing: re-running resumes from the last epoch.",
     training_notebook),
    ("corrosion-3-evaluation", "3. Evaluation",
     "Per-class IoU on the held-out test split, a confusion matrix, and the worst "
     "predictions laid next to their ground truth.",
     evaluation_notebook),
    ("corrosion-4-inference", "4. Inference",
     "Segment new photographs one at a time and in bulk, with confidence maps - the "
     "same code path the deployed app runs.",
     inference_notebook),
    ("corrosion-5-deployment", "5. Deployment",
     "Assemble the Streamlit bundle, self-check it against the five rubric rules and "
     "ship it to the ATLAS portal.",
     deployment_notebook),
]

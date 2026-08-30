"""Learning material for Topic 6 - Corrosion Type Segmentation with U-Net.

Six lessons taking someone from "I can write a Python loop" to a deployed
segmentation model. Written for an audience that is not expected to have seen a
convolutional network before, but is comfortable with Python.

Block payloads follow the contract in frontend/app/components/BlockRenderer.tsx:

    text         body            markdown-ish: one line per paragraph,
                                 "- " bullets, **bold**, *italic*, `code`
    callout      tone            quest | warning | info | success
                 title, body
    architecture title, nodes    nodes: [{id, label, note}] rendered as
                                 numbered steps; note shows when tapped
    quiz         question, options, answer (index), explanation
    flashcard    cards           [{front, back}]
    code         code, language, caption

Everything here is editable from the CMS; the seed only guarantees the material
exists on day one.
"""
from __future__ import annotations

import json

from app.domain.enums import LessonBlockType as B
from app.domain.models import LessonBlock


def _blocks(*items: tuple[B, dict]) -> list[LessonBlock]:
    return [LessonBlock(order_index=i, block_type=t,
                        payload_json=json.dumps(p, ensure_ascii=False))
            for i, (t, p) in enumerate(items)]


def _lesson(slug, title, hook, minutes, xp, order, blocks) -> dict:
    return {"slug": slug, "title": title, "hook": hook, "duration_minutes": minutes,
            "xp_reward": xp, "order_index": order, "blocks": blocks}


# ---------------------------------------------------------------------------
# 1. The problem
# ---------------------------------------------------------------------------
def _lesson_problem() -> dict:
    return _lesson(
        "problem", "Stage 1 - Why pixels, not labels",
        "An inspector does not need to be told there is rust. They need to know where, "
        "what kind, and how much.", 12, 20, 0,
        _blocks(
            (B.TEXT, {"body":
                "Three different questions a computer-vision model can answer about the "
                "same photograph of a corroded pipe.\n"
                "- **Classification** - *this image contains corrosion*. One label for the "
                "whole picture.\n"
                "- **Object detection** - *there is corrosion inside this box*. A rectangle "
                "around each finding.\n"
                "- **Semantic segmentation** - *these exact pixels are pitting, those are "
                "general corrosion*. A label for every single pixel.\n"
                "Corrosion is not box-shaped. It creeps along a weld, pools in a crevice and "
                "speckles a surface. A bounding box around an irregular rust patch is mostly "
                "clean metal, so the box cannot tell you how much material is affected. That "
                "is why this topic uses segmentation.\n"
                "The output is also directly useful: count the pixels of each class and you "
                "have the percentage of surface affected, which is what actually goes into a "
                "repair decision."}),

            (B.CALLOUT, {"tone": "info", "title": "What a mask really is",
                         "body": "A segmentation label is not a picture, it is a grid of "
                                 "numbers the same size as the photo. Pixel value 7 means "
                                 "*class 7 here*. Opened in an image viewer a mask looks "
                                 "almost black, because the values are 0-15 out of a "
                                 "possible 255. That is correct, not a corrupt file."}),

            (B.TEXT, {"body":
                "**The fifteen classes**\n"
                "Five corrosion families, each labelled at three severities. The family tells "
                "you the mechanism - *why* the metal is failing - and that drives the repair.\n"
                "- **general** - even rust across a broad area. Predictable metal loss; plan "
                "a coating renewal.\n"
                "- **pitting** - small deep holes, often tiny on the surface. Dangerous, "
                "because a pinhole can hide deep penetration.\n"
                "- **crevice** - concentrated in gaps, under bolts and flanges. Hidden by "
                "geometry, so usually found late.\n"
                "- **galvanic** - at the join between two different metals. A design fault, "
                "not just wear.\n"
                "- **preferential weld attack** - follows the weld line. Attacks the seam "
                "holding the structure together.\n"
                "Multiply by `mild`, `moderate` and `severe` and you get fifteen. Add "
                "background - every pixel that is just clean metal - and the network needs "
                "sixteen outputs."}),

            (B.CALLOUT, {"tone": "warning", "title": "Severity is the hard part",
                         "body": "Telling pitting from crevice is a question of texture and "
                                 "location, and a model learns it well. Telling moderate from "
                                 "severe is partly a human judgement call, and annotators "
                                 "disagree with each other. Expect most of your confusion "
                                 "matrix to sit between neighbouring severities of the same "
                                 "family - that is the data, not your bug."}),

            (B.QUIZ, {"question": "Why is segmentation a better fit here than object detection?",
                      "options": [
                          "It runs faster on a GPU",
                          "Corrosion is irregular, so a box is mostly clean metal and cannot measure affected area",
                          "Detection cannot handle more than 10 classes",
                          "Segmentation needs less annotation effort"],
                      "answer": 1,
                      "explanation": "A bounding box around an irregular rust patch includes a "
                                     "lot of undamaged surface, so you cannot derive how much "
                                     "material is affected. Per-pixel labels give you that "
                                     "number directly."}),

            (B.FLASHCARD, {"cards": [
                {"front": "Semantic segmentation",
                 "back": "Assign a class to every pixel. The output has the same height and "
                         "width as the input."},
                {"front": "Why 16 outputs for 15 classes?",
                 "back": "Background is a class too - every pixel that is clean metal."},
                {"front": "What does a mask PNG store?",
                 "back": "Class indices, not colours. The pixel value is the label."},
                {"front": "Which corrosion family is most dangerous to miss?",
                 "back": "Pitting - a tiny surface mark can hide deep, through-wall "
                         "penetration."},
            ]}),
        ))


# ---------------------------------------------------------------------------
# 2. Python and tensors
# ---------------------------------------------------------------------------
def _lesson_python() -> dict:
    return _lesson(
        "tensors", "Stage 2 - Python for image data",
        "Before the network, get comfortable with the shape of the data. Most beginner bugs "
        "are shape bugs.", 15, 25, 1,
        _blocks(
            (B.TEXT, {"body":
                "An image in memory is a three-dimensional array of numbers. A 512x512 colour "
                "photograph is `(512, 512, 3)` - height, width, and three colour channels.\n"
                "PyTorch wants that transposed to **channels first**, `(3, 512, 512)`, because "
                "convolutions are implemented to slide over the last two dimensions. Add a "
                "batch dimension for several images at once and a training tensor is "
                "`(batch, channels, height, width)`.\n"
                "The mask has no channel dimension. It is `(512, 512)`, one integer per pixel."}),

            (B.CODE, {"language": "python", "caption": "inspect before you train", "code":
                "import numpy as np\n"
                "from PIL import Image\n\n"
                "img = np.array(Image.open('pipe.jpg'))       # (512, 512, 3) uint8, 0-255\n"
                "msk = np.array(Image.open('pipe_mask.png'))  # (512, 512)    uint8, 0-15\n\n"
                "print(img.shape, img.dtype, img.min(), img.max())\n"
                "print(msk.shape, msk.dtype, np.unique(msk))  # which classes are present\n\n"
                "# scale pixels to 0-1 and move channels to the front\n"
                "x = img.astype(np.float32) / 255.0\n"
                "x = x.transpose(2, 0, 1)                     # (3, 512, 512)\n"
                "print(x.shape)"}),

            (B.CALLOUT, {"tone": "warning", "title": "numpy is (H, W), PIL is (W, H)",
                         "body": "numpy arrays are indexed row-first, so shape is (height, "
                                 "width). PIL's .size is (width, height) - the other way "
                                 "round. An image 90 wide and 70 tall is numpy shape (70, 90) "
                                 "and PIL size (90, 70). Mixing these up gives silently "
                                 "transposed output, and it is the single most common bug in "
                                 "this topic."}),

            (B.TEXT, {"body":
                "**Two rules that will save you hours**\n"
                "**Resize masks with NEAREST.** Bilinear interpolation averages neighbouring "
                "pixels. Halfway between class 3 and class 4 is 3.5, which is not a class - it "
                "corrupts labels silently and your metrics quietly get worse.\n"
                "**Augment the image and the mask together.** Flip one without the other and "
                "the labels no longer line up with what they describe, so the model learns "
                "from contradictory examples."}),

            (B.CODE, {"language": "python", "caption": "the two rules in code", "code":
                "from PIL import Image\n"
                "import numpy as np\n\n"
                "SIZE = 512\n"
                "img = Image.open('pipe.jpg').resize((SIZE, SIZE), Image.BILINEAR)      # smooth\n"
                "msk = Image.open('pipe_mask.png').resize((SIZE, SIZE), Image.NEAREST)  # exact\n\n"
                "a_img, a_msk = np.array(img), np.array(msk)\n\n"
                "# horizontal flip - applied to BOTH\n"
                "if np.random.rand() < 0.5:\n"
                "    a_img = a_img[:, ::-1]\n"
                "    a_msk = a_msk[:, ::-1]   # never forget this line"}),

            (B.CALLOUT, {"tone": "info", "title": "Keep augmentation conservative here",
                         "body": "Corrosion classes are separated by texture and severity, so "
                                 "heavy blur or elastic warping can turn a genuine *mild* "
                                 "example into something a human would call *moderate* - you "
                                 "would be teaching the model wrong labels. Flips, rotations "
                                 "and mild brightness or contrast changes are safe, because "
                                 "camera angle and lighting really do vary between "
                                 "inspections."}),

            (B.QUIZ, {"question": "You resize a mask with Image.BILINEAR. What goes wrong?",
                      "options": [
                          "Nothing, it is just slower",
                          "The mask becomes a colour image",
                          "Interpolation invents class indices that do not exist, like 3.5",
                          "The mask comes out rotated"],
                      "answer": 2,
                      "explanation": "Bilinear averages neighbouring values. Between class 3 "
                                     "and class 4 it produces 3.5, which is not a valid label. "
                                     "Always use NEAREST for masks."}),
        ))


# ---------------------------------------------------------------------------
# 3. Convolutions
# ---------------------------------------------------------------------------
def _lesson_convolutions() -> dict:
    return _lesson(
        "convolutions", "Stage 3 - What a convolution actually does",
        "One small idea, repeated: slide a little window over the image and look for a "
        "pattern.", 15, 25, 2,
        _blocks(
            (B.TEXT, {"body":
                "A convolution slides a small grid of numbers - a *kernel*, usually 3x3 - "
                "across the image. At each position it multiplies the kernel against the "
                "pixels underneath and sums the result into a single output number.\n"
                "What makes it useful is that the kernel's numbers are **learned**. Nobody "
                "writes an edge detector by hand; gradient descent discovers that a particular "
                "arrangement of weights fires on edges, because doing so lowers the loss.\n"
                "Two properties fall out of this design, and both matter for corrosion.\n"
                "- **Translation invariance** - the same kernel is applied everywhere, so a "
                "pattern learned in one corner is recognised in any other. Rust in the "
                "top-left looks like rust in the bottom-right.\n"
                "- **Locality** - a 3x3 kernel only sees a 3x3 neighbourhood. Stack many "
                "layers and the region each output depends on, its *receptive field*, grows, "
                "so later layers see broader context."}),

            (B.CODE, {"language": "python", "caption": "one convolution layer", "code":
                "import torch, torch.nn as nn\n\n"
                "# 3 input channels (RGB) -> 64 feature maps, 3x3 window\n"
                "conv = nn.Conv2d(in_channels=3, out_channels=64, kernel_size=3, padding=1)\n\n"
                "x = torch.randn(1, 3, 512, 512)   # one RGB image\n"
                "y = conv(x)\n"
                "print(y.shape)                    # (1, 64, 512, 512)\n\n"
                "# padding=1 keeps height and width unchanged. Without it a 3x3 kernel\n"
                "# shaves a pixel off each edge on every layer.\n"
                "print(sum(p.numel() for p in conv.parameters()), 'learned numbers')"}),

            (B.CALLOUT, {"tone": "info", "title": "Why 64 output channels?",
                         "body": "Each output channel is a separate learned kernel looking for "
                                 "a different pattern - one might respond to horizontal edges, "
                                 "another to a rust-orange texture, another to speckle. 64 of "
                                 "them means 64 patterns detected in parallel, and the next "
                                 "layer combines them into more complex ones."}),

            (B.TEXT, {"body":
                "**The standard block**\n"
                "Convolutions are almost never used alone. The pattern repeated throughout "
                "U-Net is convolution, batch normalisation, ReLU - twice over.\n"
                "- **BatchNorm** rescales each channel to a consistent mean and variance. "
                "Without it, activations drift as they pass through layers and training "
                "becomes unstable or very slow.\n"
                "- **ReLU** replaces negatives with zero. It is what makes the network "
                "non-linear - stack a hundred convolutions with no activation between them and "
                "mathematically you still only have one linear operation."}),

            (B.CODE, {"language": "python", "caption": "the U-Net building block", "code":
                "class DoubleConv(nn.Module):\n"
                "    # (conv -> BatchNorm -> ReLU) x 2\n"
                "    def __init__(self, cin, cout):\n"
                "        super().__init__()\n"
                "        self.block = nn.Sequential(\n"
                "            nn.Conv2d(cin, cout, 3, padding=1, bias=False),\n"
                "            nn.BatchNorm2d(cout), nn.ReLU(inplace=True),\n"
                "            nn.Conv2d(cout, cout, 3, padding=1, bias=False),\n"
                "            nn.BatchNorm2d(cout), nn.ReLU(inplace=True),\n"
                "        )\n\n"
                "    def forward(self, x):\n"
                "        return self.block(x)\n\n"
                "# bias=False because BatchNorm immediately subtracts the mean,\n"
                "# which cancels any bias the convolution would have added."}),

            (B.QUIZ, {"question": "Why does a network need ReLU between convolutions?",
                      "options": [
                          "To make training faster",
                          "Without a non-linearity, stacked convolutions collapse into a single linear operation",
                          "To keep the output the same size as the input",
                          "To reduce the number of parameters"],
                      "answer": 1,
                      "explanation": "Composing linear operations just gives another linear "
                                     "operation. The non-linearity is what lets depth buy you "
                                     "expressive power."}),
        ))


# ---------------------------------------------------------------------------
# 4. U-Net
# ---------------------------------------------------------------------------
def _lesson_unet() -> dict:
    return _lesson(
        "unet", "Stage 4 - U-Net and the skip connection",
        "The architecture is named after its shape, and the shape is the whole idea.",
        20, 35, 3,
        _blocks(
            (B.TEXT, {"body":
                "An ordinary image classifier funnels a picture down to a single label. "
                "Segmentation needs a prediction for every pixel, so the network has to come "
                "back *up* to full resolution. U-Net does exactly that, and drawn out it looks "
                "like a letter U.\n"
                "Going **down** the left side, each step halves the resolution and doubles the "
                "channel count. The network trades spatial detail for semantic understanding: "
                "it increasingly knows *what* it is looking at, and increasingly less about "
                "*where*.\n"
                "Going **up** the right side, each step doubles the resolution back toward the "
                "original size.\n"
                "The horizontal arrows across the middle are the **skip connections**, and "
                "they are the reason U-Net works."}),

            (B.ARCHITECTURE, {
                "title": "U-Net, depth 4 - tap any stage",
                "nodes": [
                    {"id": "in", "label": "Input photo",
                     "note": "A 512x512 RGB inspection photograph, normalised with ImageNet "
                             "statistics. Tensor shape (batch, 3, 512, 512)."},
                    {"id": "e1", "label": "Encoder 64ch",
                     "note": "DoubleConv at full resolution. Learns fine texture - the speckle "
                             "of pitting, the grain of a weld. Its output is saved for the "
                             "skip connection into the last decoder stage."},
                    {"id": "e2", "label": "Down to 256px, 128ch",
                     "note": "MaxPool halves the resolution, then DoubleConv doubles the "
                             "channels. Half the spatial detail, twice the pattern vocabulary. "
                             "Also saved for a skip."},
                    {"id": "e3", "label": "Down to 128px, 256ch",
                     "note": "By here each output pixel summarises a large patch of the "
                             "original photo, so the features describe regions rather than "
                             "textures. Saved for a skip."},
                    {"id": "e4", "label": "Down to 64px, 512ch",
                     "note": "The deepest encoder stage. Strong semantics, weak geometry - it "
                             "knows corrosion is present but only roughly where. Saved for a "
                             "skip."},
                    {"id": "b", "label": "Bottleneck 32px",
                     "note": "Lowest resolution, widest field of view. Every unit here sees "
                             "essentially the whole image, which is what lets the model use "
                             "context - a stain near a flange is more likely crevice "
                             "corrosion."},
                    {"id": "d4", "label": "Up + skip from 64px",
                     "note": "Upsample, then concatenate the saved encoder tensor along the "
                             "channel axis before convolving. This is the skip connection: "
                             "coarse meaning from below, sharp location from the side."},
                    {"id": "d3", "label": "Up + skip from 128px",
                     "note": "Resolution doubles again and another encoder map is glued on. "
                             "Boundaries get progressively crisper as finer skips arrive."},
                    {"id": "d2", "label": "Up + skip from 256px",
                     "note": "Near-full resolution. The skip arriving here still carries "
                             "genuine texture detail, which is what separates mild from "
                             "severe."},
                    {"id": "d1", "label": "Up + skip from 512px",
                     "note": "Back at input resolution, combined with the very first encoder "
                             "output. This stage is what makes a four-pixel-wide weld line "
                             "traceable."},
                    {"id": "out", "label": "1x1 conv -> 16 classes",
                     "note": "A 1x1 convolution looks at one pixel across all channels and "
                             "emits 16 logits - one per class. Softmax turns them into "
                             "probabilities; argmax picks the class; the winning probability "
                             "is your confidence score."},
                ],
                "edges": [
                    {"from": "in", "to": "e1"}, {"from": "e1", "to": "e2"},
                    {"from": "e2", "to": "e3"}, {"from": "e3", "to": "e4"},
                    {"from": "e4", "to": "b"}, {"from": "b", "to": "d4"},
                    {"from": "d4", "to": "d3"}, {"from": "d3", "to": "d2"},
                    {"from": "d2", "to": "d1"}, {"from": "d1", "to": "out"},
                    {"from": "e4", "to": "d4", "kind": "skip"},
                    {"from": "e3", "to": "d3", "kind": "skip"},
                    {"from": "e2", "to": "d2", "kind": "skip"},
                    {"from": "e1", "to": "d1", "kind": "skip"},
                ]}),

            (B.CALLOUT, {"tone": "success", "title": "The skip connection, in one sentence",
                         "body": "Downsampling destroys the information about exactly where a "
                                 "boundary sits, so the skip connection hands the encoder's "
                                 "sharp high-resolution feature map straight across to the "
                                 "decoder, letting it combine *this region is pitting* with "
                                 "*the edge is precisely here*."}),

            (B.TEXT, {"body":
                "Without skips, the decoder has to reconstruct fine boundaries from a coarse "
                "summary, and the output is a set of vague blobs in roughly the right place. "
                "For a weld-line attack four pixels wide, roughly is useless.\n"
                "Mechanically a skip is just concatenation: take the decoder's upsampled "
                "tensor, glue the matching encoder tensor onto it along the channel dimension, "
                "then convolve the combined stack."}),

            (B.CODE, {"language": "python", "caption": "one decoder stage", "code":
                "class Up(nn.Module):\n"
                "    def __init__(self, cin, cout):\n"
                "        super().__init__()\n"
                "        self.up = nn.Upsample(scale_factor=2, mode='bilinear',\n"
                "                              align_corners=True)\n"
                "        self.conv = DoubleConv(cin, cout)\n\n"
                "    def forward(self, x, skip):\n"
                "        x = self.up(x)                     # double the resolution\n"
                "        # odd input sizes can leave x a pixel short of skip\n"
                "        dy = skip.size(-2) - x.size(-2)\n"
                "        dx = skip.size(-1) - x.size(-1)\n"
                "        if dy or dx:\n"
                "            x = F.pad(x, [dx//2, dx-dx//2, dy//2, dy-dy//2])\n"
                "        x = torch.cat([skip, x], dim=1)    # <-- the skip connection\n"
                "        return self.conv(x)"}),

            (B.TEXT, {"body":
                "The final layer is a **1x1 convolution** mapping however many channels the "
                "decoder ended with down to 16 - one per class. A 1x1 kernel looks at a single "
                "pixel across all channels, which is exactly a per-pixel classifier.\n"
                "Its output is *logits*: raw, unbounded scores. Apply softmax across the 16 "
                "channels to turn them into probabilities, then take the argmax for the "
                "predicted class. The probability of the winning class is the **confidence** - "
                "and rubric rule 4 requires you to report it."}),

            (B.QUIZ, {"question": "What would U-Net lose if you removed the skip connections?",
                      "options": [
                          "It could no longer handle colour images",
                          "It would need far more parameters",
                          "Precise boundary information, so predictions become vague blobs",
                          "It could only predict two classes"],
                      "answer": 2,
                      "explanation": "Pooling discards spatial precision. The skips carry "
                                     "high-resolution detail from encoder to decoder, which is "
                                     "what keeps predicted edges sharp."}),

            (B.FLASHCARD, {"cards": [
                {"front": "Encoder",
                 "back": "Downsampling path. Halves resolution, doubles channels. Learns what "
                         "is present."},
                {"front": "Decoder",
                 "back": "Upsampling path. Restores resolution, using skip connections to "
                         "recover detail."},
                {"front": "Bottleneck",
                 "back": "Lowest resolution, most channels. The widest field of view over the "
                         "image."},
                {"front": "Skip connection",
                 "back": "Concatenate an encoder feature map onto the matching decoder stage, "
                         "along the channel axis."},
                {"front": "1x1 convolution at the end",
                 "back": "Maps feature channels to one logit per class, per pixel."},
                {"front": "Logits vs probabilities",
                 "back": "Logits are raw scores. Softmax across classes turns them into "
                         "probabilities that sum to 1."},
            ]}),
        ))


# ---------------------------------------------------------------------------
# 5. Imbalance and metrics
# ---------------------------------------------------------------------------
def _lesson_metrics() -> dict:
    return _lesson(
        "metrics", "Stage 5 - The 82% trap",
        "A model that predicts 'background' everywhere scores 82% accuracy. Here is how not "
        "to be fooled by it.", 18, 40, 4,
        _blocks(
            (B.CALLOUT, {"tone": "warning", "title": "Read this before you trust any number",
                         "body": "In this dataset roughly 82% of pixels are clean metal. A "
                                 "model that outputs *background* for every single pixel, and "
                                 "has learned nothing at all, scores 82% pixel accuracy. If "
                                 "accuracy is your headline metric, you will ship that model."}),

            (B.TEXT, {"body":
                "**Use IoU instead**\n"
                "*Intersection over Union*, computed per class: the pixels you got right for "
                "that class, divided by every pixel that was either predicted as it or truly "
                "was it.\n"
                "`IoU = TP / (TP + FP + FN)`\n"
                "The always-background model scores IoU 0.0 on all fifteen corrosion classes, "
                "because its true positives for them are zero. The metric refuses to be "
                "fooled.\n"
                "**Dice** is the close relative: `2*TP / (2*TP + FP + FN)`. It weighs overlap "
                "slightly more generously, which makes it kinder to small regions - useful "
                "when a genuine pit is only a few dozen pixels."}),

            (B.CODE, {"language": "python", "caption": "worked example on 4 pixels", "code":
                "# truth      = [0, 0, 1, 1]\n"
                "# prediction = [0, 0, 0, 1]\n"
                "#\n"
                "# class 0 (background): TP=2  FP=1  FN=0  ->  IoU = 2/3 = 0.667\n"
                "# class 1 (corrosion) : TP=1  FP=0  FN=1  ->  IoU = 1/2 = 0.500\n"
                "#\n"
                "# mean IoU       = 0.583\n"
                "# pixel accuracy = 3/4 = 0.750    <- flattering, as usual\n\n"
                "import numpy as np\n\n"
                "def iou_per_class(truth, pred, n_classes):\n"
                "    out = {}\n"
                "    for c in range(n_classes):\n"
                "        t, p = (truth == c), (pred == c)\n"
                "        union = (t | p).sum()\n"
                "        out[c] = float((t & p).sum() / union) if union else float('nan')\n"
                "    return out   # nan = class absent from both; exclude it from the mean"}),

            (B.CALLOUT, {"tone": "info", "title": "Always report per-class, never just the mean",
                         "body": "A respectable mean IoU can hide a class the model never once "
                                 "gets right. If that class happens to be pitting - the one "
                                 "that predicts through-wall failure - the model is unfit for "
                                 "purpose no matter how good the average looks."}),

            (B.TEXT, {"body":
                "**Fixing the loss**\n"
                "Metrics tell you there is a problem; the loss function is where you fix it. "
                "Two adjustments, used together.\n"
                "- **Class weights** make rare classes count for more. The textbook recipe is "
                "`median(frequency) / frequency`, but on this distribution that weights "
                "background about 68 times lower than everything else and the model "
                "overcorrects - it sprays corrosion everywhere and pixel accuracy collapses to "
                "0.02. Taking the square root of that ratio and clamping the spread to 8:1 "
                "keeps rare classes boosted without destroying the majority class.\n"
                "- **Dice loss** measures region overlap rather than counting pixels, which is "
                "much closer to what IoU scores and far less sensitive to imbalance."}),

            (B.CODE, {"language": "python", "caption": "damped weights, combined loss", "code":
                "# see corrosion/dataset.py :: class_weights()\n"
                "freq  = pixel_counts / pixel_counts.sum()\n"
                "ratio = np.median(freq[freq > 0]) / freq\n\n"
                "w = np.sqrt(ratio)                          # damp: 68:1 becomes ~8:1\n"
                "w = np.clip(w, w[w > 0].min(), w[w > 0].min() * 8)\n"
                "w = w / w[w > 0].mean()                     # normalise, mean weight = 1\n\n"
                "# combined objective\n"
                "loss = 0.5 * weighted_cross_entropy(logits, target) \\\n"
                "     + 0.5 * dice_loss(logits, target)"}),

            (B.CALLOUT, {"tone": "info", "title": "Why combine two losses?",
                         "body": "Early in training, when predictions are near random, Dice is "
                                 "almost flat and gives a weak gradient, while cross-entropy "
                                 "still points somewhere useful. Later, Dice is what pushes "
                                 "boundaries into place. Summing them gets the benefit of both "
                                 "phases."}),

            (B.QUIZ, {"question": "Your model reports 0.88 pixel accuracy and 0.04 mean IoU. What happened?",
                      "options": [
                          "The model is excellent; IoU is just a harsher metric",
                          "It is predicting background almost everywhere and ignoring the corrosion classes",
                          "The learning rate is too low",
                          "The masks were loaded as RGB"],
                      "answer": 1,
                      "explanation": "High accuracy with near-zero IoU is the signature of a "
                                     "model that has learned the majority class and nothing "
                                     "else. Add class weighting and Dice loss."}),

            (B.FLASHCARD, {"cards": [
                {"front": "IoU", "back": "TP / (TP + FP + FN), per class. Zero for any class "
                                         "the model never predicts correctly."},
                {"front": "Dice", "back": "2*TP / (2*TP + FP + FN). Like IoU but more generous "
                                          "to small regions."},
                {"front": "Why not pixel accuracy?",
                 "back": "82% of pixels are background, so predicting nothing but background "
                         "already scores 82%."},
                {"front": "Class weighting, damped",
                 "back": "sqrt of the median-frequency ratio, clamped to an 8:1 spread and "
                         "normalised to mean 1."},
            ]}),
        ))


# ---------------------------------------------------------------------------
# 6. Train, evaluate, deploy
# ---------------------------------------------------------------------------
def _lesson_deploy() -> dict:
    return _lesson(
        "deploy", "Stage 6 - Boss fight: train on a GPU and ship it",
        "Borrow a GPU, train the real thing, then put it behind a web app that passes all "
        "five rubric rules.", 30, 50, 5,
        _blocks(
            (B.TEXT, {"body":
                "**The playground is five notebooks, run in order**\n"
                "Open the **Playground** tab on this topic and you get the whole pipeline, one "
                "stage per notebook. Run them left to right; each hands the next one its "
                "output through a shared work folder.\n"
                "1. **Preprocessing & EDA** - find the dataset, read what the mask values mean, "
                "measure the class imbalance, write the manifest.\n"
                "2. **Training the U-Net** - the real training run, checkpointed every epoch.\n"
                "3. **Evaluation** - per-class IoU on the held-out test split, confusion matrix, "
                "and the worst predictions next to their ground truth.\n"
                "4. **Inference** - segment new photographs, one at a time and in bulk.\n"
                "5. **Deployment** - assemble the app bundle, self-check the rubric, ship it.\n"
                "They run unchanged in three places: dispatched from ATLAS, opened in local "
                "Jupyter, or opened straight in Colab. Attach the **CorroVision semantic "
                "export** dataset to the run and the notebook downloads it for you."}),

            (B.TEXT, {"body":
                "**Getting a GPU**\n"
                "Training this on a laptop CPU takes hours. You do not have a local GPU and you "
                "do not need one - in the **Playground**, pick **Colab GPU** or "
                "**Kaggle GPU** as the run target, and press Run. ATLAS pushes the notebook to "
                "that machine, and the injected `atlas` bridge streams logs, metrics and "
                "artifacts back here while it trains.\n"
                "This topic is flagged as heavy compute, so the platform will not let you "
                "quietly run it on CPU and wonder why nothing ever finishes."}),

            (B.CALLOUT, {"tone": "info", "title": "When Colab disconnects - and it will",
                         "body": "Idle timeouts, a closed lid and the 12-hour ceiling all wipe "
                                 "/content. The training notebook is built for that: every "
                                 "checkpoint goes to Google Drive with the optimiser and "
                                 "scheduler state, saves are atomic so a killed session cannot "
                                 "leave a half-written file, and re-running the training cell "
                                 "prints 'resuming from epoch N' instead of starting over. "
                                 "TIME_BUDGET_MIN stops the loop cleanly before Colab does. "
                                 "The recovery procedure is: reconnect, Run all, wait."}),

            (B.CODE, {"language": "python", "caption": "the notebook checks this for you", "code":
                "import torch\n"
                "print(torch.cuda.is_available())\n"
                "if torch.cuda.is_available():\n"
                "    print(torch.cuda.get_device_name(0))\n\n"
                "device = 'cuda' if torch.cuda.is_available() else 'cpu'\n\n"
                "# mixed precision: about half the memory, noticeably faster, CUDA only\n"
                "scaler = torch.amp.GradScaler('cuda') if device == 'cuda' else None\n"
                "with torch.autocast('cuda', dtype=torch.float16):\n"
                "    loss = loss_fn(model(x), y)"}),

            (B.CALLOUT, {"tone": "info", "title": "If the GPU runs out of memory",
                         "body": "Lower the batch size first, then the image size. Batch 4 at "
                                 "512px is a reasonable starting point on a free Colab T4. "
                                 "256px trains roughly four times faster and is fine while you "
                                 "are still iterating - just do not report those numbers as "
                                 "your final result."}),

            (B.TEXT, {"body":
                "**Track every run**\n"
                "An experiment you cannot reproduce is an anecdote. Each run writes a directory "
                "containing the exact config, per-epoch history, the best and last weights, a "
                "test report with per-class IoU, and a confusion matrix. The checkpoint stores "
                "its own class names and input size, so the deployment app can rebuild the "
                "model without being told how it was trained.\n"
                "One detail that catches people out: call `seed_everything()` **before** you "
                "build the model. Weight initialisation draws from the global random generator, "
                "so seeding afterwards leaves it uncontrolled and two runs with *the same seed* "
                "will not match."}),

            (B.CODE, {"language": "python", "caption": "a reproducible run", "code":
                "from corrosion import seed_everything, build_model, fit, TrainConfig\n\n"
                "seed_everything(42)          # BEFORE build_model, or init is uncontrolled\n"
                "model = build_model(num_classes=16, width=64)\n\n"
                "config = TrainConfig(epochs=40, batch_size=4, image_size=512,\n"
                "                     run_dir='runs/corrosion-v1', class_names=names)\n\n"
                "summary = fit(model, train_ds, val_ds, config, loss_fn,\n"
                "              on_epoch=atlas.metric)   # streams live into ATLAS\n\n"
                "# runs/corrosion-v1/\n"
                "#   config.json  history.csv  history.json\n"
                "#   best.pt  last.pt  report.json  confusion.csv"}),

            (B.TEXT, {"body":
                "**The five rubric rules**\n"
                "The app notebook 5 assembles already satisfies all of them, and checks itself "
                "against them before you upload. Read it under **Pipeline Library -> Corrosion "
                "app** (`app.py`), or the fuller reference under **Corrosion U-Net**. Check "
                "each rule yourself, then deploy.\n"
                "- **R1 Framework** - Streamlit or Gradio only. The template is Streamlit.\n"
                "- **R2 Input** - single entry *and* bulk upload. The Analyse tab takes one "
                "photo, or many files, or a ZIP.\n"
                "- **R3 Documentation** - model limitations, dataset details, model "
                "architecture, evaluation results. All four are sections in the Documentation "
                "tab.\n"
                "- **R4 Output** - confidence score is mandatory for classification, and "
                "charts where applicable. The app shows mean softmax confidence per image plus "
                "bar charts of class distribution and per-class IoU.\n"
                "- **R5 Review** - attach the deployed URL in Whimsical once it is live."}),

            (B.CALLOUT, {"tone": "warning", "title": "Write the limitations section honestly",
                         "body": "Reviewers trust a model more when its documentation admits "
                                 "what it cannot do. Say that severity is the weakest axis, "
                                 "that glare on wet metal reads as corrosion, and that without "
                                 "a scale reference in frame the affected-area percentage is "
                                 "relative to the photograph rather than to the asset. All "
                                 "three are true, and all three will come up in review."}),

            (B.TEXT, {"body":
                "**Then ship it**\n"
                "Notebook 5 zips the bundle for you - app, checkpoint, evaluation report and a "
                "few example photographs. Open the **Deployment** tab, upload that zip, and "
                "press Deploy. The "
                "platform builds the container, runs the rubric check, and publishes the app to "
                "the **Portal** automatically once it reports healthy. Paste the resulting URL "
                "into Whimsical and you are done."}),

            (B.QUIZ, {"question": "Why must seed_everything() run before build_model()?",
                      "options": [
                          "It selects the GPU device",
                          "Weight initialisation draws from the global RNG, so seeding afterwards leaves it uncontrolled",
                          "It loads the dataset",
                          "It has to run before torch is imported"],
                      "answer": 1,
                      "explanation": "Constructing the model consumes random numbers to "
                                     "initialise the weights. Seed after that and the starting "
                                     "point differs on every run, no matter what seed you "
                                     "pass."}),

            (B.FLASHCARD, {"cards": [
                {"front": "Mixed precision",
                 "back": "Run most operations in float16 for speed and memory, keeping float32 "
                         "master weights. CUDA only."},
                {"front": "GradScaler",
                 "back": "Scales the loss up before backprop so small gradients do not "
                         "underflow in float16."},
                {"front": "Why save both best.pt and last.pt?",
                 "back": "best.pt is the highest validation mIoU; last.pt lets you resume or "
                         "inspect where training actually ended up."},
                {"front": "Confidence score",
                 "back": "Softmax probability of the winning class. Rubric rule 4 requires it "
                         "for classification."},
            ]}),
        ))


def corrosion_lessons() -> list[dict]:
    """The six lessons for Topic 6, in order."""
    return [
        _lesson_problem(),
        _lesson_python(),
        _lesson_convolutions(),
        _lesson_unet(),
        _lesson_metrics(),
        _lesson_deploy(),
    ]

"""U-Net, written out in full.

Interns are asked to understand this architecture, so it is spelled out rather
than imported from a library. It is the 2015 Ronneberger design with two changes
that are standard now: batch normalisation, and padded convolutions so the
output keeps the input's height and width.

The shape of it:

    input 3xHxW
      down1 -> 64      ---------------------------->  up1 -> 64 -> output KxHxW
        down2 -> 128   -------------------->  up2 -> 128
          down3 -> 256 ---------->  up3 -> 256
            down4 -> 512 -->  up4 -> 512
              bottleneck 1024

The horizontal arrows are the skip connections, and they are the whole point.
Downsampling answers "what is this?" but throws away "where exactly?". The skips
hand the precise edges back to the decoder, which is what lets the network draw
a pit boundary two pixels wide instead of a vague blob.
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class DoubleConv(nn.Module):
    """(conv 3x3 -> BN -> ReLU) x 2 - the block every U-Net level is built from."""

    def __init__(self, in_ch: int, out_ch: int, mid_ch: int | None = None):
        super().__init__()
        mid_ch = mid_ch or out_ch
        self.block = nn.Sequential(
            nn.Conv2d(in_ch, mid_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(mid_ch),
            nn.ReLU(inplace=True),
            nn.Conv2d(mid_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.block(x)


class Down(nn.Module):
    """Halve the resolution, then double the channels."""

    def __init__(self, in_ch: int, out_ch: int):
        super().__init__()
        self.pool_conv = nn.Sequential(nn.MaxPool2d(2), DoubleConv(in_ch, out_ch))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.pool_conv(x)


class Up(nn.Module):
    """Upsample, glue the skip connection on, then convolve."""

    def __init__(self, in_ch: int, out_ch: int, bilinear: bool = True):
        super().__init__()
        if bilinear:
            # Bilinear upsampling has no parameters and avoids the checkerboard
            # artefacts that transposed convolutions are prone to.
            self.up = nn.Upsample(scale_factor=2, mode="bilinear", align_corners=True)
            self.conv = DoubleConv(in_ch, out_ch, in_ch // 2)
        else:
            self.up = nn.ConvTranspose2d(in_ch, in_ch // 2, kernel_size=2, stride=2)
            self.conv = DoubleConv(in_ch, out_ch)

    def forward(self, x: torch.Tensor, skip: torch.Tensor) -> torch.Tensor:
        x = self.up(x)
        # Odd input sizes leave the upsampled tensor a pixel short; pad to match.
        dy = skip.size(-2) - x.size(-2)
        dx = skip.size(-1) - x.size(-1)
        if dy or dx:
            x = F.pad(x, [dx // 2, dx - dx // 2, dy // 2, dy - dy // 2])
        return self.conv(torch.cat([skip, x], dim=1))


class UNet(nn.Module):
    """U-Net for multi-class semantic segmentation.

    Args:
        num_classes: output channels - one score per class, per pixel.
        in_channels: 3 for RGB.
        width: channels at the first level. 64 is the paper; 32 or 16 trains
            faster and fits smaller GPUs, at some cost in accuracy.
        bilinear: bilinear upsampling instead of transposed convolutions.
        depth: number of downsampling steps. 4 means the image is reduced 16x.
    """

    def __init__(
        self,
        num_classes: int,
        in_channels: int = 3,
        width: int = 64,
        bilinear: bool = True,
        depth: int = 4,
    ):
        super().__init__()
        if depth < 1:
            raise ValueError("depth must be at least 1")
        self.num_classes = num_classes
        self.depth = depth

        self.inc = DoubleConv(in_channels, width)

        # Encoder: double the channels each step, capped at the bottleneck.
        self.downs = nn.ModuleList()
        chans = [width]
        c = width
        for i in range(depth):
            out = c * 2
            # The last step is halved when bilinear, so the decoder's channel
            # arithmetic stays exact after concatenation.
            if i == depth - 1 and bilinear:
                out = c * 2 // 2
            self.downs.append(Down(c, out))
            c = out
            chans.append(c)

        # Decoder: mirror the encoder back up.
        self.ups = nn.ModuleList()
        for i in range(depth):
            skip_ch = chans[depth - 1 - i]
            in_ch = c + skip_ch
            out_ch = skip_ch
            if i < depth - 1 and bilinear:
                out_ch = skip_ch // 2 if skip_ch > width else skip_ch
            self.ups.append(Up(in_ch, out_ch, bilinear))
            c = out_ch

        self.outc = nn.Conv2d(c, num_classes, kernel_size=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        skips = [self.inc(x)]
        for down in self.downs:
            skips.append(down(skips[-1]))

        out = skips[-1]
        for i, up in enumerate(self.ups):
            out = up(out, skips[-2 - i])
        # Raw logits: the loss applies softmax itself, which is numerically safer.
        return self.outc(out)

    @torch.no_grad()
    def predict(self, x: torch.Tensor) -> torch.Tensor:
        """Class index per pixel. Shape (B, H, W)."""
        self.eval()
        return self.forward(x).argmax(dim=1)

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)


def build_model(num_classes: int, width: int = 64, depth: int = 4, bilinear: bool = True) -> UNet:
    """Convenience constructor used by the notebook and the training script."""
    return UNet(num_classes=num_classes, width=width, depth=depth, bilinear=bilinear)

"""
Crowd density map → approximate count (sum of density).

Uses CSRNet pretrained on ShanghaiTech Part A (congested scenes). This is closer to
“how full is the crowd” than YOLO boxes in dense video, but it is still **dataset-
biased** (training domain ≠ random web video). Treat counts as **relative occupancy**,
not ground-truth census.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
import torch
from csrnet import CSRNet

# ShanghaiTech Part A pretrained (leeyee/CSRNet-pytorch README / Google Drive)
_DEFAULT_GDRIVE_ID = "1Z-atzS5Y2pOd-nEWqZRVBDMYJDreGWHH"
_WEIGHTS_NAME = "csrnet_shanghaiA.pth"

_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def default_cache_path() -> Path:
    return Path.home() / ".cache" / "stadiumonitor" / _WEIGHTS_NAME


def ensure_weights(gdrive_id: Optional[str] = None) -> Path:
    path = default_cache_path()
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    gid = (gdrive_id or os.getenv("CSRNET_GDRIVE_ID") or _DEFAULT_GDRIVE_ID).strip()
    try:
        import gdown
    except ImportError as e:
        raise RuntimeError(
            "density mode requires gdown. Install: pip install gdown"
        ) from e
    url = f"https://drive.google.com/uc?id={gid}"
    print(f"Downloading CSRNet weights to {path} (one-time, ~80MB)...")
    gdown.download(url, str(path), quiet=False)
    if not path.is_file():
        raise RuntimeError(f"Failed to download CSRNet weights to {path}")
    return path


def load_csrnet(weights_path: Path, device: torch.device) -> CSRNet:
    model = CSRNet()
    # Prefer weights_only=True (PyTorch 2.4+); many public CSRNet .pth files are legacy
    # full pickles and need weights_only=False — only use files you trust.
    try:
        ckpt = torch.load(weights_path, map_location=device, weights_only=True)
    except TypeError:
        # PyTorch < 2.4: no weights_only argument
        ckpt = torch.load(weights_path, map_location=device)
    except Exception:
        ckpt = torch.load(weights_path, map_location=device, weights_only=False)
    if isinstance(ckpt, dict):
        if "state_dict" in ckpt:
            ckpt = ckpt["state_dict"]
        elif "model" in ckpt:
            ckpt = ckpt["model"]
    ckpt = {k.replace("module.", "", 1): v for k, v in ckpt.items()}
    model.load_state_dict(ckpt, strict=True)
    model.to(device)
    model.eval()
    return model


def _resize_for_csrnet(h: int, w: int) -> Tuple[int, int]:
    """Height/width divisible by 16 (pooling + dilated stack)."""
    nh = max(16, (h // 16) * 16)
    nw = max(16, (w // 16) * 16)
    return nh, nw


def preprocess_bgr(frame_bgr: np.ndarray, max_side: int) -> torch.Tensor:
    """
    Resize for CSRNet input. Person count is **not** proportional to image area — the old
    (h0*w0)/(nh*nw) factor on density.sum() was wrong and pinned numbers to a band similar
    to bbox methods. We integrate the network output as trained: sum(density) ≈ count for
    this input resolution. Use `calibration` for domain shift (random video vs ShanghaiTech).
    """
    h0, w0 = frame_bgr.shape[:2]
    scale = min(1.0, float(max_side) / float(max(h0, w0)))
    if scale < 1.0:
        h1 = int(round(h0 * scale))
        w1 = int(round(w0 * scale))
        frame_bgr = cv2.resize(frame_bgr, (w1, h1), interpolation=cv2.INTER_AREA)
    else:
        h1, w1 = h0, w0

    nh, nw = _resize_for_csrnet(h1, w1)
    if nh != h1 or nw != w1:
        frame_bgr = cv2.resize(frame_bgr, (nw, nh), interpolation=cv2.INTER_AREA)

    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    rgb = (rgb - _IMAGENET_MEAN) / _IMAGENET_STD
    chw = np.transpose(rgb, (2, 0, 1))
    return torch.from_numpy(chw).unsqueeze(0)


def _forward_sum(model: CSRNet, frame_bgr: np.ndarray, device: torch.device, max_side: int) -> float:
    inp = preprocess_bgr(frame_bgr, max_side=max_side).to(device)
    return float(model(inp).sum().item())


@torch.inference_mode()
def estimate_count(
    model: CSRNet,
    frame_bgr: np.ndarray,
    *,
    device: torch.device,
    max_side: int = 1024,
    calibration: float = 1.0,
    multi_scale: bool = False,
) -> Tuple[int, float, float]:
    """
    Returns (rounded_count, calibrated_sum, raw_sum) where raw_sum is sum(density) before calibration.

    multi_scale: second forward pass at ~1.35× max_side (capped) and average raw sums — can help a bit
    on wide frames when tiny heads matter; ~2× slower.
    """
    raw = _forward_sum(model, frame_bgr, device, max_side)
    if multi_scale:
        h0, w0 = frame_bgr.shape[:2]
        cap = int(max(h0, w0))
        side2 = min(int(max_side * 1.35), 2048, cap)
        if side2 > max_side + 8:
            raw2 = _forward_sum(model, frame_bgr, device, side2)
            raw = 0.5 * (raw + raw2)
    s = raw * float(calibration)
    return int(round(max(0.0, s))), s, raw

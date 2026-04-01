"""
YOLOv8 person counting — v3 (overcounting fixes).
 
Three targeted fixes over v2:
─────────────────────────────────────────────────────────────────────────────
1. SOFT-NMS (Gaussian decay) instead of hard greedy NMS.
   Hard NMS zeroes out any box whose IoU with the winner exceeds a threshold.
   That's too blunt for crowds: two people standing shoulder-to-shoulder
   legitimately overlap 30-50% and get suppressed. Soft-NMS instead *decays*
   the score of nearby boxes by a Gaussian penalty — real adjacent people
   survive because their overlap is moderate; true duplicates (IoU > 0.7)
   decay to near zero and fall below the final score gate.
 
2. ASPECT RATIO FILTER.
   A standing person's bounding box is tall and narrow: width/height ~ 0.3-0.6.
   Boxes that are too wide (signs, cars, reflections) or too square/tall
   (vertical poles, stacked detections) are rejected before NMS, reducing
   false positives that inflate the count.
 
3. TWO-STAGE CONFIDENCE.
   - Per-tile inference uses a *stricter* threshold (tile_conf, default 0.50)
     to avoid junk detections that YOLO is uncertain about at crop scale.
   - After cross-tile Soft-NMS, a *relaxed* threshold (conf, default 0.35)
     is applied to the merged+decayed scores. A real person split across a
     tile boundary will have their best crop score survive above 0.35 even if
     no single crop scored above 0.50.
   Combined effect: fewer within-tile false positives, fewer missed
   boundary-straddling people.
─────────────────────────────────────────────────────────────────────────────
"""
 
from __future__ import annotations
 
import logging
import warnings
from dataclasses import dataclass
from typing import Iterator, Optional, Tuple
 
import cv2
import numpy as np
 
logger = logging.getLogger(__name__)
 
BoxArray   = np.ndarray   # (N, 4) float32, xyxy absolute pixels
ScoreArray = np.ndarray   # (N,)   float32
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Result type
# ─────────────────────────────────────────────────────────────────────────────
 
@dataclass(frozen=True)
class CountResult:
    count: int
    mean_conf: float
    boxes: BoxArray      # kept xyxy boxes (full-frame coords)
    scores: ScoreArray   # post-Soft-NMS scores for each kept box
    tiles_run: int
    tiles_skipped: int
 
    @property
    def confident_count(self) -> int:
        """Stricter count: only boxes with decayed score >= 0.5."""
        return int((self.scores >= 0.5).sum())
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Device
# ─────────────────────────────────────────────────────────────────────────────
 
def resolve_device(preference: str = "auto") -> str:
    pref = (preference or "auto").lower().strip()
    if pref not in ("auto", "cpu", "mps", "cuda"):
        warnings.warn(f"Unknown device {pref!r}; falling back to 'cpu'.")
        return "cpu"
    try:
        import torch
    except ImportError:
        if pref != "cpu":
            warnings.warn("torch not found; falling back to 'cpu'.")
        return "cpu"
    if pref == "cuda":
        return "cuda" if torch.cuda.is_available() else _fallback("cuda", "cpu")
    if pref == "mps":
        mps = getattr(torch.backends, "mps", None)
        return "mps" if (mps and mps.is_available()) else _fallback("mps", "cpu")
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps and mps.is_available():
        return "mps"
    return "cpu"
 
 
def _fallback(req: str, fb: str) -> str:
    warnings.warn(f"Device '{req}' unavailable; falling back to '{fb}'.")
    return fb
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Fix 2 — Aspect ratio filter
# ─────────────────────────────────────────────────────────────────────────────
 
def _aspect_ratio_mask(
    xyxy: BoxArray,
    min_ratio: float = 0.15,
    max_ratio: float = 0.80,
    min_height_px: int = 20,
) -> np.ndarray:
    """
    Returns a boolean mask of boxes that look like standing people.
 
    width/height must be in [min_ratio, max_ratio].
    Boxes shorter than min_height_px are rejected (noise / very distant artefacts).
 
    Default band 0.15-0.80 is deliberately wide to handle:
      - children (squatter than adults)
      - people seen from below (appear wider)
      - people leaning or sitting
 
    Typical false-positive shapes filtered out:
      - Horizontal banners / cars: ratio > 0.80
      - Thin vertical poles:       ratio < 0.15
    """
    w = xyxy[:, 2] - xyxy[:, 0]
    h = xyxy[:, 3] - xyxy[:, 1]
    ratio = np.where(h > 0, w / h, 99.0)
    return (ratio >= min_ratio) & (ratio <= max_ratio) & (h >= min_height_px)
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Fix 1 — Soft-NMS (Gaussian penalty)
# ─────────────────────────────────────────────────────────────────────────────
 
def _soft_nms(
    xyxy: BoxArray,
    scores: ScoreArray,
    sigma: float = 0.5,
    score_threshold: float = 0.001,
) -> Tuple[BoxArray, ScoreArray]:
    """
    Gaussian Soft-NMS (Bodla et al., 2017).
 
    Instead of hard-suppressing boxes above an IoU threshold, scores are
    multiplied by exp(-IoU^2 / sigma). True duplicates (IoU ~1) decay to ~0;
    adjacent real people (IoU ~0.3) barely decay at all.
 
    Returns (xyxy, scores) for boxes whose decayed score > score_threshold,
    sorted by descending decayed score.
 
    sigma: Gaussian bandwidth. Smaller = sharper penalty.
           0.5 works well for person detection at typical crowd densities.
    score_threshold: boxes decayed below this are discarded entirely.
    """
    if xyxy.shape[0] == 0:
        return xyxy, scores
 
    boxes = xyxy.copy().astype(np.float64)
    sc    = scores.copy().astype(np.float64)
    N     = boxes.shape[0]
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
 
    # Selection sort by score — O(N^2), fine for typical detection counts (<500)
    for i in range(N):
        # Swap highest-scoring remaining box into position i
        max_j = i + int(sc[i:].argmax())
        if max_j != i:
            boxes[[i, max_j]] = boxes[[max_j, i]]
            sc[[i, max_j]]    = sc[[max_j, i]]
            areas[[i, max_j]] = areas[[max_j, i]]
 
        ix1 = np.maximum(boxes[i, 0], boxes[i + 1:, 0])
        iy1 = np.maximum(boxes[i, 1], boxes[i + 1:, 1])
        ix2 = np.minimum(boxes[i, 2], boxes[i + 1:, 2])
        iy2 = np.minimum(boxes[i, 3], boxes[i + 1:, 3])
        inter = np.maximum(0.0, ix2 - ix1) * np.maximum(0.0, iy2 - iy1)
        iou   = inter / (areas[i] + areas[i + 1:] - inter + 1e-6)
 
        # Gaussian decay — the key difference from hard NMS
        sc[i + 1:] *= np.exp(-(iou ** 2) / sigma)
 
    keep = sc > score_threshold
    return boxes[keep].astype(np.float32), sc[keep].astype(np.float32)
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Tile generation
# ─────────────────────────────────────────────────────────────────────────────
 
def _iter_tiles(
    h: int, w: int,
    grid: int,
    overlap: float = 0.25,
    min_tile_px: int = 64,
) -> Iterator[Tuple[int, int, int, int]]:
    if grid <= 1:
        yield 0, 0, h, w
        return
    tile_h   = h / grid
    tile_w   = w / grid
    stride_h = tile_h * (1.0 - overlap)
    stride_w = tile_w * (1.0 - overlap)
    row = 0.0
    while True:
        y1 = int(row)
        y2 = min(h, int(row + tile_h + 0.5))
        if y1 >= h:
            break
        col = 0.0
        while True:
            x1 = int(col)
            x2 = min(w, int(col + tile_w + 0.5))
            if x1 >= w:
                break
            if (y2 - y1) < min_tile_px or (x2 - x1) < min_tile_px:
                logger.warning("Tile (%d,%d,%d,%d) < min_tile_px=%d; skipped.",
                               y1, x1, y2, x2, min_tile_px)
            else:
                yield y1, x1, y2, x2
            col += stride_w
            if x2 == w:
                break
        row += stride_h
        if y2 == h:
            break
 
 
# ─────────────────────────────────────────────────────────────────────────────
# YOLO inference (single tile / frame)
# ─────────────────────────────────────────────────────────────────────────────
 
def _predict_boxes(
    model,
    frame_bgr: np.ndarray,
    *,
    device: str,
    conf: float,
    imgsz: int,
) -> Tuple[BoxArray, ScoreArray]:
    results = model.predict(
        source=frame_bgr,
        classes=[0],
        conf=conf,
        imgsz=imgsz,
        verbose=False,
        device=device,
    )
    r = results[0]
    if r.boxes is None or len(r.boxes) == 0:
        return np.empty((0, 4), dtype=np.float32), np.empty((0,), dtype=np.float32)
    xyxy:   BoxArray   = r.boxes.xyxy.cpu().numpy().astype(np.float32)
    scores: ScoreArray = r.boxes.conf.cpu().numpy().astype(np.float32)
    return xyxy, scores
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
 
def count_people(
    model,
    frame_bgr: np.ndarray,
    *,
    device: str,
    # Fix 3: two-stage confidence — tile_conf must stay LOW for recall (wide/crowd shots
    # often yield 0.2–0.45 conf); final `conf` filters after Soft-NMS + aspect.
    conf: float      = 0.30,   # post–Soft-NMS gate
    tile_conf: float = 0.22,   # Ultralytics predict() min conf — main recall knob (not 0.5)
    imgsz: int       = 640,
    max_width: Optional[int] = None,
    tile_grid: int   = 1,
    tile_overlap: float = 0.25,
    # Fix 1: Soft-NMS params
    soft_nms_sigma: float           = 0.65,  # gentler decay — dense adjacent people keep score
    soft_nms_score_threshold: float = 0.001,
    # Fix 2: aspect ratio filter
    ar_min: float        = 0.15,
    ar_max: float        = 0.80,
    ar_min_height_px: int = 12,  # 20 drops distant figures in wide shots
    min_tile_px: int     = 64,
) -> CountResult:
    """
    Count people in a single BGR frame.
 
    Parameters
    ----------
    model       : Loaded Ultralytics YOLO instance.
    frame_bgr   : H x W x 3 uint8 numpy array.
    device      : 'cuda', 'mps', or 'cpu'.
    conf        : Final score gate AFTER Soft-NMS decay (typ. 0.25–0.35).
    tile_conf   : YOLO predict() conf (typ. 0.15–0.30). Values ~0.5 **severely undercount** crowds.
    imgsz       : YOLO inference size (longest side, pixels).
    max_width   : Optional pre-tile downscale (prefer None; let imgsz handle it).
    tile_grid   : 1 = full frame. 2 = 2x2. 3 = 3x3.
    tile_overlap: Fractional overlap between adjacent tiles (0.0-0.5).
    soft_nms_sigma            : Gaussian bandwidth for Soft-NMS. Lower = harsher.
    soft_nms_score_threshold  : Discard boxes decayed below this after Soft-NMS.
    ar_min / ar_max           : Accepted width/height ratio range for a "person".
    ar_min_height_px          : Minimum box height in pixels (filters noise).
    min_tile_px               : Skip tiles smaller than this in either dimension.
 
    Returns
    -------
    CountResult with count, mean_conf, boxes, scores, tiles_run, tiles_skipped.
    """
    h, w = frame_bgr.shape[:2]
    if max_width and max_width > 0 and w > max_width:
        scale = max_width / float(w)
        frame_bgr = cv2.resize(
            frame_bgr, (int(w * scale), int(h * scale)),
            interpolation=cv2.INTER_AREA,
        )
        h, w = frame_bgr.shape[:2]
 
    def _filter(xyxy: BoxArray, sc: ScoreArray) -> Tuple[BoxArray, ScoreArray]:
        """Aspect-ratio filter → Soft-NMS → final conf gate."""
        if xyxy.shape[0] == 0:
            return xyxy, sc
        # Fix 2
        mask = _aspect_ratio_mask(xyxy, ar_min, ar_max, ar_min_height_px)
        xyxy, sc = xyxy[mask], sc[mask]
        if xyxy.shape[0] == 0:
            return xyxy, sc
        # Fix 1
        xyxy, sc = _soft_nms(xyxy, sc, soft_nms_sigma, soft_nms_score_threshold)
        # Fix 3: final gate
        keep = sc >= conf
        return xyxy[keep], sc[keep]
 
    # ── single-tile fast path ────────────────────────────────────────────────
    if tile_grid <= 1:
        xyxy, sc = _predict_boxes(model, frame_bgr, device=device,
                                  conf=tile_conf, imgsz=imgsz)
        xyxy, sc = _filter(xyxy, sc)
        n = xyxy.shape[0]
        return CountResult(n, float(sc.mean()) if n else 0.0,
                           xyxy, sc, tiles_run=1, tiles_skipped=0)
 
    # ── tiled path ───────────────────────────────────────────────────────────
    tile_coords   = list(_iter_tiles(h, w, tile_grid, tile_overlap, min_tile_px))
    tiles_skipped = tile_grid * tile_grid - len(tile_coords)
    all_xy: list[BoxArray]   = []
    all_sc: list[ScoreArray] = []
 
    for y1, x1, y2, x2 in tile_coords:
        crop = frame_bgr[y1:y2, x1:x2]
        # Fix 3: strict threshold per tile
        xyxy, sc = _predict_boxes(model, crop, device=device,
                                  conf=tile_conf, imgsz=imgsz)
        if xyxy.shape[0] == 0:
            continue
        # Translate crop-local coords to full-frame coords
        xyxy[:, 0] += x1;  xyxy[:, 2] += x1
        xyxy[:, 1] += y1;  xyxy[:, 3] += y1
        all_xy.append(xyxy)
        all_sc.append(sc)
 
    tiles_run = len(tile_coords)
 
    if not all_xy:
        empty_b = np.empty((0, 4), dtype=np.float32)
        empty_s = np.empty((0,),   dtype=np.float32)
        return CountResult(0, 0.0, empty_b, empty_s, tiles_run, tiles_skipped)
 
    merged_xy = np.vstack(all_xy)
    merged_sc = np.concatenate(all_sc)
 
    # All three filters applied on the merged cross-tile pool
    merged_xy, merged_sc = _filter(merged_xy, merged_sc)
    n = merged_xy.shape[0]
    return CountResult(
        count=n,
        mean_conf=float(merged_sc.mean()) if n else 0.0,
        boxes=merged_xy,
        scores=merged_sc,
        tiles_run=tiles_run,
        tiles_skipped=tiles_skipped,
    )
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Visualisation helper
# ─────────────────────────────────────────────────────────────────────────────
 
def draw_boxes(
    frame_bgr: np.ndarray,
    result: CountResult,
    color: Tuple[int, int, int] = (0, 255, 80),
    thickness: int = 2,
    show_conf: bool = True,
) -> np.ndarray:
    """Return a BGR copy of frame_bgr annotated with boxes and total count."""
    out = frame_bgr.copy()
    for (x1, y1, x2, y2), sc in zip(result.boxes, result.scores):
        cv2.rectangle(out, (int(x1), int(y1)), (int(x2), int(y2)), color, thickness)
        if show_conf:
            cv2.putText(out, f"{sc:.2f}",
                        (int(x1), max(int(y1) - 4, 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    cv2.putText(out, f"People: {result.count}",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                (255, 255, 255), 2, cv2.LINE_AA)
    return out


def load_yolo(model_name_or_path: str):
    """Load Ultralytics YOLO; caller holds the model for the ingest session."""
    from ultralytics import YOLO

    return YOLO(model_name_or_path)
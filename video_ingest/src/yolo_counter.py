"""
YOLOv8 person counting for a single frame (COCO class 0 = person).

Counts **detector boxes**, not a true census. Wide/dense scenes still undercount
vs “eyeball” totals; **tiled inference** (grid > 1) runs YOLO on overlapping crops
and merges with NMS so small/distant people are seen at a larger effective scale.

On Mac: MPS when available (Apple Silicon), else CPU. CUDA when available elsewhere.
"""

from __future__ import annotations

from typing import Iterator, Optional, Tuple

import cv2
import numpy as np


def resolve_device(preference: str) -> str:
    pref = (preference or "auto").lower().strip()
    if pref in ("cpu", "mps", "cuda"):
        return pref
    if pref != "auto":
        return "cpu"
    import torch

    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def load_yolo(model_name: str):
    from ultralytics import YOLO

    return YOLO(model_name)


def _prepare_frame(frame_bgr, max_width: Optional[int]):
    h, w = frame_bgr.shape[:2]
    if max_width is not None and max_width > 0 and w > max_width:
        scale = max_width / float(w)
        frame_bgr = cv2.resize(
            frame_bgr,
            (int(w * scale), int(h * scale)),
            interpolation=cv2.INTER_AREA,
        )
    return frame_bgr


def _iter_tiles(h: int, w: int, grid: int, overlap: float) -> Iterator[Tuple[int, int, int, int]]:
    """Yield (y1, x1, y2, x2) pixel boxes for an NxN grid with fractional overlap between neighbors."""
    if grid <= 1:
        yield 0, 0, h, w
        return
    th = h / float(grid)
    tw = w / float(grid)
    oy = th * overlap
    ox = tw * overlap
    for i in range(grid):
        for j in range(grid):
            y1 = int(max(0, i * th - oy / 2))
            x1 = int(max(0, j * tw - ox / 2))
            y2 = int(min(h, (i + 1) * th + oy / 2))
            x2 = int(min(w, (j + 1) * tw + ox / 2))
            if y2 - y1 < 16 or x2 - x1 < 16:
                continue
            yield y1, x1, y2, x2


def _nms_xyxy(xyxy: np.ndarray, scores: np.ndarray, iou_th: float) -> np.ndarray:
    """Greedy NMS; returns indices to keep."""
    if xyxy.size == 0:
        return np.array([], dtype=np.int64)
    x1, y1, x2, y2 = xyxy.T
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        inds = np.where(iou <= iou_th)[0]
        order = order[inds + 1]
    return np.array(keep, dtype=np.int64)


def _predict_boxes(
    model,
    frame_bgr,
    *,
    device: str,
    conf: float,
    imgsz: int,
):
    """Returns (N,4) xyxy float32, (N,) scores or empty arrays."""
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
        return np.zeros((0, 4), dtype=np.float32), np.zeros((0,), dtype=np.float32)
    xyxy = r.boxes.xyxy.cpu().numpy().astype(np.float32)
    sc = r.boxes.conf.cpu().numpy().astype(np.float32)
    return xyxy, sc


def count_people(
    model,
    frame_bgr,
    *,
    device: str,
    conf: float,
    max_width: Optional[int],
    imgsz: int,
    tile_grid: int = 1,
    tile_overlap: float = 0.25,
    tile_nms_iou: float = 0.45,
) -> Tuple[int, float]:
    """
    Returns (person_count, mean_confidence of kept boxes), or (0, 0.0) if none.

    tile_grid: 1 = full frame once. 2 = 2x2 overlapping crops (better for wide shots;
    ~4× inference cost). 3 = 3x3 (~9× cost).
    """
    frame_bgr = _prepare_frame(frame_bgr, max_width)
    h, w = frame_bgr.shape[:2]

    if tile_grid <= 1:
        xyxy, sc = _predict_boxes(model, frame_bgr, device=device, conf=conf, imgsz=imgsz)
        if xyxy.size == 0:
            return 0, 0.0
        return int(sc.size), float(sc.mean())

    chunks_xy: list[np.ndarray] = []
    chunks_sc: list[np.ndarray] = []
    for y1, x1, y2, x2 in _iter_tiles(h, w, tile_grid, tile_overlap):
        crop = frame_bgr[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        xyxy, sc = _predict_boxes(model, crop, device=device, conf=conf, imgsz=imgsz)
        if xyxy.size == 0:
            continue
        xyxy[:, [0, 2]] += float(x1)
        xyxy[:, [1, 3]] += float(y1)
        chunks_xy.append(xyxy)
        chunks_sc.append(sc)

    if not chunks_xy:
        return 0, 0.0
    all_xy = np.vstack(chunks_xy)
    all_sc = np.concatenate(chunks_sc)
    keep = _nms_xyxy(all_xy, all_sc, tile_nms_iou)
    if keep.size == 0:
        return 0, 0.0
    kept = all_sc[keep]
    return int(kept.size), float(kept.mean())

#!/usr/bin/env python3
"""
Start one video_ingest process per camera that has feed.type == \"file\" in config/cameras.json.

  python scripts/run_video_feeds.py [--dry-run]

Optional per-camera \"ingest\" overrides (see scripts/camera.py / README).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from shared.camera_registry import default_registry_path, load_cameras  # noqa: E402

_MAIN = _REPO / "video_ingest" / "src" / "main.py"


def _append_ingest(cmd: List[str], ingest: Dict[str, Any]) -> None:
    if not ingest:
        return
    if ingest.get("people_source"):
        cmd.extend(["--people-source", str(ingest["people_source"])])
    if "density_calibration" in ingest:
        cmd.extend(["--density-calibration", str(float(ingest["density_calibration"]))])
    if "density_max_side" in ingest:
        cmd.extend(["--density-max-side", str(int(ingest["density_max_side"]))])
    if ingest.get("density_multi_scale") is True:
        cmd.append("--density-multi-scale")
    if ingest.get("density_multi_scale") is False:
        cmd.append("--no-density-multi-scale")
    if "sample_fps" in ingest:
        cmd.extend(["--sample-fps", str(float(ingest["sample_fps"]))])
    if "motion_scale" in ingest:
        cmd.extend(["--motion-scale", str(float(ingest["motion_scale"]))])
    if "max_expected_occupancy" in ingest:
        cmd.extend(["--max-expected-occupancy", str(int(ingest["max_expected_occupancy"]))])
    if "priority" in ingest:
        cmd.extend(["--priority", str(ingest["priority"])])
    if "realtime" in ingest:
        cmd.append("--realtime" if ingest["realtime"] else "--no-realtime")
    if "loop" in ingest:
        cmd.append("--loop" if ingest["loop"] else "--no-loop")
    if "yolo_min_tile_px" in ingest:
        cmd.extend(["--yolo-min-tile-px", str(int(ingest["yolo_min_tile_px"]))])
    if "yolo_conf" in ingest:
        cmd.extend(["--yolo-conf", str(float(ingest["yolo_conf"]))])
    if "yolo_tile_conf" in ingest:
        cmd.extend(["--yolo-tile-conf", str(float(ingest["yolo_tile_conf"]))])
    if "yolo_soft_nms_sigma" in ingest:
        cmd.extend(["--yolo-soft-nms-sigma", str(float(ingest["yolo_soft_nms_sigma"]))])
    if "yolo_soft_nms_score_threshold" in ingest:
        cmd.extend(["--yolo-soft-nms-score-threshold", str(float(ingest["yolo_soft_nms_score_threshold"]))])
    if "yolo_ar_min" in ingest:
        cmd.extend(["--yolo-ar-min", str(float(ingest["yolo_ar_min"]))])
    if "yolo_ar_max" in ingest:
        cmd.extend(["--yolo-ar-max", str(float(ingest["yolo_ar_max"]))])
    if "yolo_ar_min_height_px" in ingest:
        cmd.extend(["--yolo-ar-min-height-px", str(int(ingest["yolo_ar_min_height_px"]))])


def build_command(cam: Dict[str, Any]) -> Optional[List[str]]:
    feed = cam.get("feed") or {}
    if feed.get("type") != "file":
        return None
    vpath = (feed.get("path") or "").strip()
    if not vpath:
        return None
    vp = Path(vpath)
    if not vp.is_file():
        print(f"[skip] {cam.get('camera_id')}: missing video {vp}")
        return None

    cmd: List[str] = [
        sys.executable,
        str(_MAIN),
        "--video",
        str(vp.resolve()),
        "--camera-id",
        str(cam["camera_id"]),
        "--zone",
        str(cam["zone"]),
        "--max-expected-occupancy",
        str(int(cam.get("max_expected_occupancy", 220))),
        "--priority",
        str(cam.get("priority", "medium")),
    ]
    _append_ingest(cmd, cam.get("ingest") or {})
    return cmd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default="", help="Override path to cameras.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = Path(args.registry) if args.registry else default_registry_path()
    if not path.is_file():
        raise SystemExit(
            f"No registry: {path}\n"
            "Run: python scripts/camera.py init && python scripts/camera.py add ... --video path/to.mp4"
        )
    cameras = load_cameras(path)

    cmds: List[List[str]] = []
    for cam in cameras:
        cmd = build_command(cam)
        if cmd:
            cmds.append(cmd)
            print("+", " ".join(cmd))

    if not cmds:
        print("No cameras with feed.type=file and a valid path.")
        return

    if args.dry_run:
        return

    procs = [
        subprocess.Popen(cmd, cwd=str(_REPO), env={**os.environ, "PYTHONPATH": str(_REPO)})
        for cmd in cmds
    ]
    try:
        codes = [p.wait() for p in procs]
    except KeyboardInterrupt:
        for p in procs:
            p.terminate()
        raise SystemExit(130) from None
    if any(c != 0 for c in codes):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

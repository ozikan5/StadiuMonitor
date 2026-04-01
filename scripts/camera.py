#!/usr/bin/env python3
"""
Create and manage camera instances in config/cameras.json (not committed).

  python scripts/camera.py init
  python scripts/camera.py add --id CAM-001 --zone north-stand --max-occ 220 --priority high
  python scripts/camera.py add --id CAM-002 --zone plaza --max-occ 300 --video data/samples/clip.mp4
  python scripts/camera.py list
  python scripts/camera.py remove --id CAM-001
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from shared.camera_registry import (  # noqa: E402
    default_registry_path,
    load_cameras,
    parse_registry_payload,
    save_cameras,
    validate_camera,
)


def _load_or_empty(path: Path) -> list:
    if not path.is_file():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return parse_registry_payload(data)


def cmd_init(args: argparse.Namespace) -> None:
    path = default_registry_path()
    if path.is_file() and not args.force:
        print(f"Already exists: {path} (use --force to replace with empty registry)")
        return
    save_cameras([], path=path)
    print(f"Empty registry ready: {path}")


def cmd_add(args: argparse.Namespace) -> None:
    path = default_registry_path()
    cameras = _load_or_empty(path)
    cid = args.id.strip()
    if any(c.get("camera_id") == cid for c in cameras):
        raise SystemExit(f"camera_id already exists: {cid}")
    cam: dict = {
        "camera_id": cid,
        "zone": args.zone.strip(),
        "max_expected_occupancy": int(args.max_occ),
        "priority": (args.priority or "medium").strip(),
    }
    vp = (args.video or "").strip()
    if vp:
        cam["feed"] = {"type": "file", "path": vp}
    validate_camera(cam)
    cameras.append(cam)
    save_cameras(cameras, path=path)
    print(f"Added {cid} → {path}")


def cmd_list(args: argparse.Namespace) -> None:
    path = default_registry_path()
    if not path.is_file():
        print(f"No registry yet. Run: python scripts/camera.py init")
        return
    cameras = load_cameras(path)
    if not cameras:
        print("(no cameras)")
        return
    for c in cameras:
        feed = c.get("feed") or {}
        ft = feed.get("type", "none")
        fp = feed.get("path", "")
        print(f"  {c['camera_id']}  zone={c['zone']}  max_occ={c.get('max_expected_occupancy')}  feed={ft} {fp}")


def cmd_remove(args: argparse.Namespace) -> None:
    path = default_registry_path()
    if not path.is_file():
        raise SystemExit("No registry file")
    cameras = load_cameras(path)
    cid = args.id.strip()
    new_cams = [c for c in cameras if c.get("camera_id") != cid]
    if len(new_cams) == len(cameras):
        raise SystemExit(f"camera_id not found: {cid}")
    save_cameras(new_cams, path=path)
    print(f"Removed {cid}")


def cmd_path(_: argparse.Namespace) -> None:
    print(default_registry_path())


def main() -> None:
    p = argparse.ArgumentParser(description="Manage config/cameras.json")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="Create empty config/cameras.json")
    s.add_argument("--force", action="store_true", help="Overwrite with empty registry")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("add", help="Add a camera")
    s.add_argument("--id", required=True, help="camera_id, e.g. CAM-NORTH-001")
    s.add_argument("--zone", required=True)
    s.add_argument("--max-occ", type=int, required=True)
    s.add_argument("--priority", default="medium")
    s.add_argument("--video", default="", help="Optional MP4 path → run_video_feeds will use it")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("list", help="List cameras")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("remove", help="Remove by camera_id")
    s.add_argument("--id", required=True)
    s.set_defaults(fn=cmd_remove)

    s = sub.add_parser("path", help="Print registry file path")
    s.set_defaults(fn=cmd_path)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()

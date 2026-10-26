"""Aggregate CCTV counting on a permitted pre-recorded clip (Milestone 6). Aggregate counts only.

Run with the separate CV environment (never the core app venv):

    .venv-cv/Scripts/python.exe -m modules.cv.count_video --video data/raw/video/<clip>.mp4 \
        --config modules/cv/configs/<clip>.lines.json [--model yolov8n.pt] [--stride N] [--max-seconds S] [--annotate]

YOLO detects; supervision ByteTrack keeps an EPHEMERAL id per object only so one object crossing the line is counted once.
Ids are never stored, drawn or exported. No face/identity recognition. Output: data/processed/cctv_detector_counts.parquet
(+ .provenance.json). Heavy libraries are imported lazily inside ``run`` so this module imports without them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import config
from modules.cv import aggregate as AG

OUT_TABLE = config.PROCESSED_DIR / "cctv_detector_counts.parquet"
OUT_PROV = config.PROCESSED_DIR / "cctv_detector_counts.provenance.json"
ANNOT_DIR = config.PROCESSED_DIR / "cctv"
DEFAULT_MODEL = ANNOT_DIR / "yolov8n.pt"
PRIVACY_BLUR_FRACTION = 0.25  # top share of each person box that is blurred


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def blur_head_region(frame, box, fraction: float = PRIVACY_BLUR_FRACTION) -> None:
    """Gaussian-blur the top ``fraction`` of a person box in place. NOT reliable face anonymisation."""
    import cv2
    x1, y1, x2, y2 = (int(v) for v in box)
    h, w = frame.shape[:2]
    x1, x2, y1 = max(x1, 0), min(x2, w), max(y1, 0)
    y2 = min(int(y1 + (y2 - y1) * fraction) + 1, h)
    if x2 - x1 < 3 or y2 - y1 < 3:
        return
    roi = frame[y1:y2, x1:x2]
    k = max(3, (min(roi.shape[:2]) // 2) | 1)
    frame[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (k, k), 0)


def run(video: Path, cfg_path: Path, model_path: str, stride: int = 1, max_seconds: float | None = None,
        start_seconds: float = 0.0, annotate: bool = False, conf: float = 0.25, iou: float = 0.5, imgsz: int = 640,
        out_table: Path = OUT_TABLE, out_prov: Path = OUT_PROV) -> dict:
    import cv2
    import numpy as np
    import supervision as sv
    import ultralytics
    from ultralytics import YOLO

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    classes = cfg.get("classes", ["person"])
    wanted = [cid for cid, name in AG.COCO_TO_CLASS.items() if name in classes]
    t0 = time.time()
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise SystemExit(f"cannot open video: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    ln = cfg["line"]
    scale = (W, H) if ln.get("coords", "normalized") == "normalized" else (1, 1)
    a = (ln["a"][0] * scale[0], ln["a"][1] * scale[1])
    b = (ln["b"][0] * scale[0], ln["b"][1] * scale[1])
    counter = AG.LineCounter(a, b, ln.get("positive_is", "inbound"))

    model_path = Path(model_path)
    if not model_path.is_file():  # fetch official weights once into the weights folder (network use is explicit and one-off)
        import os
        model_path.parent.mkdir(parents=True, exist_ok=True)
        cwd = os.getcwd()
        os.chdir(model_path.parent)
        try:
            YOLO(model_path.name)
        finally:
            os.chdir(cwd)
    model = YOLO(str(model_path))
    eff_fps = fps / stride
    tracker = sv.ByteTrack(frame_rate=max(int(round(eff_fps)), 1))
    start_f = int(start_seconds * fps)
    end_f = total if max_seconds is None else min(total, start_f + int(max_seconds * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)

    writer = None
    annot_path = ANNOT_DIR / f"annotated_{video.stem}.mp4"
    if annotate:
        ANNOT_DIR.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(str(annot_path), cv2.VideoWriter_fourcc(*"mp4v"), eff_fps, (W, H))

    processed = 0
    detections_seen = 0
    fi = start_f
    while fi < end_f:
        ok, frame = cap.read()
        if not ok:
            break
        if (fi - start_f) % stride:
            fi += 1
            continue
        t = (fi - start_f) / fps  # seconds from the start of the processed segment
        res = model.predict(frame, conf=conf, iou=iou, imgsz=imgsz, classes=wanted, verbose=False, device="cpu")[0]
        det = sv.Detections.from_ultralytics(res)
        det = tracker.update_with_detections(det)
        detections_seen += len(det)
        pts = []
        for i in range(len(det)):
            x1, y1, x2, y2 = det.xyxy[i]
            name = AG.COCO_TO_CLASS.get(int(det.class_id[i]), "other")
            tid = int(det.tracker_id[i]) if det.tracker_id is not None else i
            pts.append((tid, ((x1 + x2) / 2, y2 if name == "person" else (y1 + y2) / 2), name))  # feet/centre anchor
        counter.update(t, pts)
        if writer is not None:
            out = frame.copy()
            for i in range(len(det)):  # blur first, then draw, so boxes stay visible
                if AG.COCO_TO_CLASS.get(int(det.class_id[i])) == "person":
                    blur_head_region(out, det.xyxy[i])
            for i in range(len(det)):
                x1, y1, x2, y2 = (int(v) for v in det.xyxy[i])
                name = AG.COCO_TO_CLASS.get(int(det.class_id[i]), "other")
                cv2.rectangle(out, (x1, y1), (x2, y2), (0, 200, 0), 2)
                cv2.putText(out, name, (x1, max(y1 - 6, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 1)
            cv2.line(out, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), (0, 0, 255), 2)
            tot = counter.totals()
            txt = "in " + str(sum(v for (d, _), v in tot.items() if d == "inbound")) + "  out " + \
                  str(sum(v for (d, _), v in tot.items() if d == "outbound")) + "  | pre-recorded clip, not live"
            cv2.putText(out, txt, (20, H - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
            writer.write(out)
        processed += 1
        fi += 1
    cap.release()
    if writer is not None:
        writer.release()

    seg_seconds = (min(fi, end_f) - start_f) / fps
    n_minutes = max(int(np.ceil(seg_seconds / 60.0)), 1)
    df = AG.tallies_to_frame(counter.tallies, cfg["location_id"], n_minutes, classes=classes)
    out_table.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_table, index=False)
    elapsed = time.time() - t0
    prov = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "measurement_method": AG.MEASUREMENT_METHOD, "source_type": AG.SOURCE_TYPE, "time_basis": AG.TIME_BASIS,
        "model": {"name": Path(model_path).name, "weights_sha256": sha256(Path(model_path)),
                  "family": "Ultralytics YOLO (COCO-pretrained)"},
        "versions": {"ultralytics": ultralytics.__version__, "supervision": sv.__version__, "opencv": cv2.__version__,
                     "python": platform.python_version()},
        "thresholds": {"conf": conf, "iou": iou, "imgsz": imgsz}, "stride": stride, "device": "cpu",
        "tracker": "supervision ByteTrack (ephemeral ids used only to avoid double counting; never stored)",
        "line_config": cfg, "line_config_file": cfg_path.name,
        "clip": {"filename": video.name, "sha256": sha256(video), "fps": fps, "width": W, "height": H,
                 "total_frames": total, "duration_s": total / fps},
        "segment": {"start_s": start_seconds, "processed_s": round(seg_seconds, 2), "full_clip": bool(
            start_seconds == 0 and (max_seconds is None or max_seconds * fps >= total))},
        "frames_processed": processed, "detections_tracked": int(detections_seen),
        "processing_seconds": round(elapsed, 1),
        "annotated_video": annot_path.name if annotate else None,
        "privacy": {"head_region_blur_fraction": PRIVACY_BLUR_FRACTION if annotate else None,
                    "note": "Upper part of person boxes is blurred in the annotated video. This is not reliable face "
                            "anonymisation: missed detections are not blurred."},
        "limitations": "COCO has no auto-rickshaw class; autos may be detected as car/two_wheeler or missed. "
                       "Counts are not validated unless a spot check is recorded.",
    }
    out_prov.write_text(json.dumps(prov, indent=2), encoding="utf-8")
    print(f"frames processed: {processed}  segment: {seg_seconds:.1f}s  time: {elapsed:.1f}s  totals: {counter.totals()}")
    return prov


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--model", default=str(DEFAULT_MODEL))
    ap.add_argument("--stride", type=int, default=1, help="process every Nth frame")
    ap.add_argument("--max-seconds", type=float, default=None)
    ap.add_argument("--start-seconds", type=float, default=0.0)
    ap.add_argument("--annotate", action="store_true")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--iou", type=float, default=0.5)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--out", type=Path, default=OUT_TABLE, help="output parquet (provenance written next to it)")
    args = ap.parse_args(argv)
    try:
        import cv2, supervision, ultralytics  # noqa: F401,E401
    except ImportError as e:
        raise SystemExit(f"CCTV detector unavailable: {e}. Install requirements-cv.txt in a separate venv (.venv-cv).")
    run(args.video, args.config, args.model, args.stride, args.max_seconds, args.start_seconds, args.annotate,
        args.conf, args.iou, args.imgsz, args.out, args.out.with_suffix(".provenance.json"))


if __name__ == "__main__":
    main()

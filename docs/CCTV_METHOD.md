# CCTV proof of concept: method, results and limits (Milestone 6)

## What was built
`python -m modules.cv.count_video` (run in the separate `.venv-cv`, CPU only) reads one permitted pre-recorded clip and a line config
(`modules/cv/configs/*.lines.json`). Ultralytics YOLO (`yolov8n.pt`, COCO-pretrained) detects person, car, motorcycle (reported as
`two_wheeler`), bus and truck. supervision `ByteTrack` gives each object an ephemeral id held in memory only so that one object crossing
the line is counted once; ids are never stored, drawn or exported. Crossings are counted by direction (inbound = moving from the negative
to the positive side of the directed line) and aggregated into **minute buckets of clip time**.
Counting/aggregation logic is in `modules/cv/aggregate.py` (pure Python, unit-tested without cv libraries).

Output (all gitignored): `data/processed/cctv_detector_counts.parquet` (`location_id, timestamp_min, clip_minute, direction, class, count,
measurement_method = actual_detector, source_type, time_basis = clip_relative`) plus `cctv_detector_counts.provenance.json` (model, weights
SHA-256, library versions, thresholds, stride, line config, clip SHA-256, segment, frames, processing time). It is a separate stream from the
synthetic `cctv_counts` and is never merged with it. Timestamps are clip-relative (1970-01-01 + clip offset is a reference, not a recording date)
because the clip's recording time is unknown.

## Environment
torch 2.14.1+cpu, ultralytics 8.4.189, supervision 0.26.1 (0.31 no longer ships `ByteTrack`), opencv-python 5.0.0, Python 3.12, Windows 11.
No DLL was blocked by the application-control policy. torch initially failed with WinError 206 (path too long) in the project folder, so the
venv lives at `C:\gsrtc_cv` and is linked as `.venv-cv`.

## The permitted clip is not CCTV footage
`a-morning-on-route-r014.mp4` (1920x1080, 60 fps, 105 s) is a produced explainer animation for this prototype: a schematic map of Rajkot
route R014, KPI cards, and a mock "CAM 02 . STAND GATE" panel with drawn green outlines. It contains no real pedestrians or vehicles (it is itself
labelled "Simulated data for demonstration"). Consequences:
- The counting line (horizontal at 50% of the frame) is a placeholder that exercises the pipeline; it is not a calibrated gate line.
- Full run: 2,100 frames (every 3rd frame, whole 105 s), 272 s on CPU, **0 detections and 0 line crossings**. At confidence 0.05, 1 low-confidence
  "person" box appeared in 35 sampled frames. Zero is the correct answer for this clip and says nothing about accuracy on real footage.
- The detector is therefore **not validated** on real scenes. No accuracy claim is made.

## Spot check
Developer spot check (AI agent examining sampled frames, not an independent human count): segment 0-30 s, 30 frames sampled at 1 s; reference
crossings 0, detector crossings 0, error undefined (zero reference); trivially in agreement for the reason above
(`data/processed/cctv_spot_check.json`). A human count is still required: use `docs/cctv_spot_check_worksheet.md`.

## Privacy blur: what was and was not verified
The annotated video blurs (Gaussian) the top 25% of each detected person box before drawing boxes; no track ids are drawn. With zero
person detections in the clip, **no real person was blurred, so blur quality on faces was not inspected**. Output frames were inspected
(box/line/counter overlay is present, no ids). The blur routine was only checked mechanically on a synthetic noise image (top 25% variance fell
from about 74 to 5, lower region unchanged). Limits that would apply on real footage: an upper-box blur is not reliable face anonymisation (heads
may fall outside the top 25%, boxes may be loose, small or occluded people are missed, and **missed detections are never blurred**). Do not
describe this output as anonymised.

## Other limitations
- COCO has no auto-rickshaw class: autos may be detected as car/two_wheeler or missed.
- Detector accuracy depends on camera angle, resolution, crowding and occlusion; ByteTrack can swap or drop ids in crowds, causing over/under counts.
- Frame stride 3 can miss fast crossings; a stand-gate camera needs its own line, stride and threshold tuning against a human count.
- Counts come from a pre-recorded clip recorded at a different time and place from the synthetic ticket data: separate evidence stream, not comparable.

# CCTV proof of concept: method, results and limits (Milestone 6)

## What was built
`python -m modules.cv.count_video` (run in the separate `.venv-cv`, CPU only) reads one permitted pre-recorded clip and a line config
(`modules/cv/configs/*.lines.json`). Ultralytics YOLO (`yolov8n.pt`, COCO-pretrained) detects person, car, motorcycle (reported as
`two_wheeler`), bus and truck. supervision `ByteTrack` gives each object an ephemeral id held in memory only so one object crossing the line
is counted once; ids are never stored, drawn or exported. A crossing is counted when the box anchor (feet for people, box centre for vehicles)
moves from one side of the line to the other. The class of a crossing is the **majority label over that track so far**, because single-frame
labels flip between car, bus and truck. Crossings are aggregated by direction into **minute buckets of clip time**.
Counting/aggregation logic is in `modules/cv/aggregate.py` (pure Python, unit-tested without cv libraries).

Output (all gitignored): `data/processed/cctv_detector_counts.parquet` (`location_id, timestamp_min, clip_minute, direction, class, count,
measurement_method = actual_detector, source_type, time_basis = clip_relative`) plus `cctv_detector_counts.provenance.json` (model, weights
SHA-256, library versions, thresholds, stride, line config, clip filename + original filename + SHA-256, segment, frames, processing time).
It is a separate stream from the synthetic `cctv_counts` and is never merged with it. Timestamps are clip-relative (1970-01-01 plus the clip
offset is a reference, not a recording date) because the clip's recording time is unknown.

## Environment
torch 2.14.1+cpu, ultralytics 8.4.189, supervision 0.26.1 (0.31 no longer ships `ByteTrack`), opencv-python 5.0.0, Python 3.12, Windows 11.
No DLL was blocked. torch failed with WinError 206 (path too long) in the project folder, so the venv lives at `C:\gsrtc_cv` and is linked
as `.venv-cv`.

## Demo clip
`data/raw/video/road_traffic_4k.mp4` is a public sample road-traffic clip (original title "4K Road traffic video for object detection and
tracking - free download now!"). Its location is not in the pilot area; it is used only to demonstrate the counting method (`location_id =
sample_road_clip`). Despite the title it is **1280x720, 30 fps, 306 s**. Fixed elevated camera over a two-carriageway road; all visible
traffic moves toward the camera.
- Counting line (`road_traffic_4k.lines.json`): horizontal at 58% of frame height (y = 418), x from 0 to 58% of the width, covering both
  carriageways and the left footpath. Downward (toward the camera) = "inbound", upward = "outbound". Here "inbound" only means toward the camera.
- Full run: whole clip, every frame (stride 1, no downscale needed, image size 640), 9,184 frames, **998 s (about 17 min) on CPU** including the
  annotated MP4.

## Counts for the whole clip (306 s, detector output, not validated beyond the spot check)
| Class | Inbound | Outbound |
|---|---|---|
| car | 284 | 4 |
| bus | 25 | 1 |
| truck | 14 | 1 |
| person | 4 | 1 |
Totals: 323 vehicles inbound, 6 outbound. The few outbound vehicles are probably tracker/jitter artefacts (the traffic only comes toward the camera).
The 5 "person" crossings are almost certainly false positives: the "person" boxes in inspected output frames sit on the black bollards along
the left footpath, while the real, very small pedestrians on the footpath were not detected. Treat person counts here as unreliable.

## Spot check (developer, AI agent; not an independent human count)
Segment 02:00-02:30 (120-150 s). I viewed 60 frames sampled every 0.5 s as crops around the line and counted vehicles whose box centre crossed it.
Reference 29 (27 cars/vans/minivans, 1 articulated bus, 1 truck), all inbound, 0 outbound. Detector for the same segment (re-run with the same settings):
30 (27 car, 3 bus), all inbound, 0 outbound.
- Total error: +1, **+3.4%**. Cars/vans match (27 vs 27). Class labels are weaker than totals: 3 buses vs 1 bus + 1 truck (bus +2, truck -1).
- Caveats: crossings were not matched one-to-one (equal totals can hide compensating errors); each vehicle is near the line in only 1-2 sampled
  frames and several box centres were within about 10 px of the line, so the reference itself is uncertain by roughly +/-2; one dense,
  one-directional 30 s segment says nothing about outbound counts, night, rain or other camera angles.
- A human count is still required: `docs/cctv_spot_check_worksheet.md` (segment pre-filled, human column blank). Results are in
  `data/processed/cctv_spot_check.json` with `human_check_completed: false`.

## Annotated video inspection
Frames from the output at about 12 s, 135 s, 144 s and others show: boxes with class names only (no track ids), the red counting line, and a running
"in N out M | pre-recorded clip, not live" counter that matches the detector totals. Observed problems: the articulated bus is sometimes boxed
twice (front and rear sections), which can inflate bus counts; vans are labelled car/truck/bus inconsistently; distant vehicles near the top are
small but detected.

## Privacy blur: what was and was not verified
The annotated video blurs (Gaussian) the top 25% of each detected person box before drawing boxes. In this clip pedestrians are tiny (about 10 by
30 px) and far from the camera; the only "person" boxes inspected were false positives on bollards, so the blur was applied to bollards and **no real
person or face was blurred or checked**. At this distance faces are not identifiable in the source anyway, but that is a property of the clip, not of
the method. The blur routine was only checked mechanically on a synthetic noise image (top 25% variance fell from about 74 to 5, rest unchanged).
On closer footage an upper-box blur would not be reliable face anonymisation (heads can fall outside the top 25%, boxes are loose, and **missed
detections are never blurred**). Do not describe this output as anonymised.

## Earlier clip
`a-morning-on-route-r014.mp4` (kept config `a-morning-on-route-r014.lines.json`) is a produced explainer animation (map, KPI cards, a mock "CAM 02" panel
of drawn outlines) with no real traffic, so the detector found nothing and the run produced zero crossings. It is no longer the demo clip.

## Other limitations
- COCO has no auto-rickshaw class: autos may be detected as car/two_wheeler or missed. This clip has none and no motorcycles were counted.
- Accuracy depends on camera angle, resolution, crowding and occlusion; ByteTrack can swap or drop ids in queues, causing over/under counts.
- A road clip is not a bus stand: it shows the method, not GSRTC footfall. Counts are a separate evidence stream, not comparable with the synthetic data.

# CCTV manual spot-check worksheet

Purpose: a human counts line crossings in a short segment of the permitted clip so the detector's count error can be calculated.
The developer spot check in `data/processed/cctv_spot_check.json` was done by an AI agent from sampled frames, is not independent,
and must not be presented as a human count.

- Clip: `data/raw/video/road_traffic_4k.mp4` (public sample road-traffic clip, location not in the pilot area; used only to demonstrate the counting method; 1280x720, 30 fps, 306 s).
- **Segment to count: 02:00 to 02:30 (30 s).** Play it at 0.5x or step through it; do not count from the detector overlay.
- Counting line: horizontal at 58% of frame height (y = 418 px of 720), from the left edge to 58% of the width (x = 742 px), covering both carriageways. Config: `modules/cv/configs/road_traffic_4k.lines.json`.
- Direction: all traffic moves toward the camera (downward in the image) = **inbound**. Upward = outbound (none expected).
- What to count: each car / van / minivan, motorcycle, bus, truck and pedestrian whose body centre crosses the line once. Count an articulated bus or a truck with trailer once. Tick the class column.
- Detector result for the same segment is on the dashboard (CCTV Analytics) only for whole clip minutes; the agent run for 02:00-02:30 is in `cctv_spot_check.json` after you finish, to avoid anchoring your count.

| Time window (mm:ss) | Class (car/van, bus, truck, two_wheeler, person) | Direction (in/out) | Number of crossings |
|---|---|---|---|
| 02:00 to 02:05 |  |  |  |
| 02:05 to 02:10 |  |  |  |
| 02:10 to 02:15 |  |  |  |
| 02:15 to 02:20 |  |  |  |
| 02:20 to 02:25 |  |  |  |
| 02:25 to 02:30 |  |  |  |

Totals (fill in):

| | Inbound | Outbound | Total |
|---|---|---|---|
| Human count | | | |
| Detector count | | | |
| Absolute error | | | |
| Error % = abs error / human count x 100 | | | |

By class (human / detector): car/van ____ / ____, bus ____ / ____, truck ____ / ____, two_wheeler ____ / ____, person ____ / ____.

Counter name and date: ______________   Tolerance you accept (e.g. +/-10%): ______
After counting, record the numbers in `data/processed/cctv_spot_check.json` (set `human_check_completed` to true).

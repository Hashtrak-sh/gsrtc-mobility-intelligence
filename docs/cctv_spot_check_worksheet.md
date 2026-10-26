# CCTV manual spot-check worksheet

Purpose: a human counts line crossings in a short segment of the permitted clip so the detector's count error can be calculated.
This is the check the acceptance tests ask for; the developer spot check in `data/processed/cctv_spot_check.json` was done by an AI
agent, is not independent, and found no real people or vehicles in the clip (so it validates nothing).

- Clip: `data/raw/video/a-morning-on-route-r014.mp4` (1920x1080, 60 fps, 105 s). Its content is a produced explainer animation.
  If you have permission to use a genuine fixed-camera clip, use that instead and copy the worksheet.
- Counting line: horizontal at 50% of frame height (y = 540 px of 1080), across the full width. Config:
  `modules/cv/configs/a-morning-on-route-r014.lines.json`. Downward movement = inbound; upward = outbound.
- Segment to count: 00:00 to 01:00 (recommended: 30-60 s; pick one and write it here: ______).
- What to count: each person / car / motorcycle (two-wheeler) / bus / truck whose body crosses the line once. A back-and-forth
  jitter counts once per genuine crossing. Ignore drawings and map icons. Pause the video if needed; do not count by detector overlay.
- Detector result for the same segment: read it from the dashboard (CCTV Analytics, clip-minute rows) or
  `data/processed/cctv_detector_counts.parquet`.

| Time (mm:ss) | Class | Direction (in/out) | Notes |
|---|---|---|---|
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |

Totals (fill in):

| | Inbound | Outbound | Total |
|---|---|---|---|
| Human count | | | |
| Detector count | | | |
| Absolute error | | | |
| Error % = abs error / human count x 100 | | | |

Counter name and date: ______________   Tolerance you accept (e.g. +/-15%): ______
After counting, record the numbers in `data/processed/cctv_spot_check.json` (set `human_check_completed` to true).

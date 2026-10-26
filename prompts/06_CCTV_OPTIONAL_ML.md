# Milestone 6 — Optional CCTV and Advanced ML

Only start when P0 end-to-end workflow is stable.

## CCTV proof of concept

- Accept a permitted local video and a configuration describing counting line(s)/zones.
- If Ultralytics YOLO and supervision are available, detect supported classes and count line crossings by direction and minute.
- Export aggregate counts and an annotated video.
- No face recognition, identity tracking, or persistent person IDs.
- Document detector class limitations, camera-angle issues, and manual spot-check results.
- Do not claim face blurring unless the output has been inspected and the implementation performs it. Person bounding-box blur is not necessarily reliable face anonymisation.
- If the model cannot be installed or weights cannot be obtained, show a clear “CCTV detector unavailable” state; never fabricate inference output.

## Advanced ML

- Add a ridership baseline model only after source and derived tables are stable.
- Compare with a naïve baseline using a defensible train/test split.
- Show metrics, target, features, data split, and synthetic-data caveats.
- Add feature importance; use SHAP only when supported by the fitted model.
- Add Prophet forecast only if sufficient synthetic history exists and the dependency is available. Otherwise retain a deterministic baseline forecast.
- If H3 is used, ensure every spatial layer shares the configured resolution and provide a non-H3 fallback.

## Verification

Run a small known video if available, manually count a sample, and report error. Test optional-module failure paths. The core app must start without optional libraries.

# Phase 4 — Computer vision, renderer, and replay

## Built

- Added a deterministic top-down factory renderer that animates machine state, spindle/press motion, conveyor stripes, operators, stack lights, and zone lighting. It streams an MP4 and frame-aligned CSV labels from the plant timeline.
- Added uniform clip transcoding to MPEG-4, 640×360, 10 fps, fixed bitrate, and deterministic low-level grain. Decode and ROI processing are streamed; frames are not saved as image files.
- Added normalized ROI motion energy, HSV stack-light fractions, panel brightness, configurable rule state classification, N-of-M hysteresis, zone luminance detection, and optional frame-feature RandomForest classification.
- Added optional YOLO person detection when a model is passed by the caller and OpenCV HOG as the offline fallback. No model weights are downloaded implicitly.
- Added the documented clip manifest, validation, source-clip-level train/validation/test assignment, and deterministic appearance augmentations on training clips only.
- Added CV metrics by class and source domain, and replay mapping that loops state-matched clips, marks transitions for crossfades, and falls back to rendered video when no clip exists.

## How to run

Install the CV dependencies with `python -m pip install -e ".[dev,api,cv]"`.

Render a short synthetic example:

```sh
python -m renderer.generate --minutes 10 \
  --video data/generated/renderer/synthetic.mp4 \
  --labels data/generated/renderer/labels.csv
```

Add at least three source videos to `data/clips/manifest.csv` and run:

```sh
python -m cv.ingest_clips --manifest data/clips/manifest.csv
```

The command splits clips by source ID before augmentation, writes normalized MP4 assets under `data/clips/normalized/`, and writes CV event Parquet under `data/generated/`. Raw decoded frames are transient in-memory objects and are not persisted.

## Verification

- Phase 4 tests cover renderer MP4/label output, normalized codec profile/cadence, streaming CV events, training-only augmentation, clip-level split integrity, state/light features, replay fallback, CV source reports, and feature-classifier output.
- `python -m pytest -q`: 28 passed.
- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: 54 files already formatted.
- `git diff --check`: passed.
- Renderer smoke: generated an MP4 and aligned labels CSV from a one-minute synthetic timeline.
- The full suite prints one existing Windows `joblib` warning when it cannot detect physical core count; it falls back to logical cores and does not affect the passing checks.

## Known gaps

- The rule classifier and OpenCV HOG detector need evaluation against a representative real clip set; no real or AI-generated clips are included in the repository.
- The YOLO path accepts a caller-provided model but does not package weights. Configure machine, station, and zone ROIs for each camera before using CV events for decisions.
- Uniform normalization uses MPEG-4 rather than H.264 to avoid requiring a specific external encoder build. The replay selector emits offsets and crossfade metadata; actual video compositing belongs to the replay UI/API phase.
- The default clip manifest contains only its schema header. CV ingestion requires at least three actual source clips.

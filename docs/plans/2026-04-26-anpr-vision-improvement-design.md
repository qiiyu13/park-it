# ANPR Vision Pipeline Improvement — Design

> **Date:** 2026-04-26  
> **Status:** Approved  
> **Target:** 95% plate recognition accuracy on Indonesian plates

## Problem

Current ANPR pipeline runs PaddleOCR on the **full camera snapshot** frame, scanning all text (signs, ads, other vehicles) and attempting to regex-match an Indonesian plate pattern. Without a plate detection stage to crop the region of interest, OCR accuracy is inherently limited to ~50-65%.

## Approach

**Two separate YOLO models** — vehicle detection and plate detection run independently.

| Model | Purpose | Source |
|-------|---------|--------|
| `yolov8n.pt` | Vehicle type detection (car/motorcycle/bus/truck) | Stock Ultralytics COCO weights (existing) |
| `license_plate_detector.pt` | License plate region detection (bounding box) | Pre-built from Roboflow Universe |

## Target Pipeline

```
Snapshot Image
     │
     ├──▶ [Vehicle YOLO (yolov8n.pt)]
     │        │
     │        ▼ vehicle_type: MOBIL/MOTOR/BUS/TRUCK
     │
     └──▶ [Plate Detector YOLO (license_plate_detector.pt)]
              │
              ▼ plate_bbox: [x1, y1, x2, y2]
              │
              ▼ [Crop image to bbox]
              │
              ▼ [PaddleOCR on crop only]
              │
              ▼ raw_text
              │
              ▼ [Character constraints + Indonesian regex]
              │
              ▼ plate_number: "B 1234 ABC" | NULL
```

## Key Design Decisions

### 1. Separate models, not combined

Vehicle detection with stock COCO already works. Plate detection needs a specialized model. Keeping them separate allows independent upgrades — swap the plate detector without touching vehicle classification.

Trade-off: Two YOLO inference passes (~300ms total) vs one (~150ms). Acceptable — gate open time is 3-5 seconds.

### 2. Pre-built model first, fine-tune only if needed

Download a community-trained license plate detector from Roboflow Universe. Test against real gate snapshots. Only train if the downloaded model performs poorly on your specific camera angle/lighting.

### 3. Crop-then-OCR, not full-frame OCR

Once the plate region is cropped, OCR sees only the plate — no competing text. This alone should take accuracy from ~50% to ~85%.

### 4. Character-level post-processing (Indonesian plates only)

Because plates are exclusively Indonesian format (A-Z, 0-9, space):

```python
# Strip non-plate characters
cleaned = re.sub(r"[^A-Z0-9 ]", "", raw_text.upper())

# Apply Indonesian plate regex
pattern = re.compile(r"([A-Z]{1,2})\s*(\d{1,4})\s*([A-Z]{0,3})")
```

No need for confusion mapping (`B/8`, `D/0`) — OCR on a clean crop with Latin-only characters is generally reliable. Only add if field testing shows specific confusion patterns.

### 5. Confidence threshold remains configurable

Default `0.8` threshold gates accepted reads. Below threshold → `plate_number = NULL`, operator fills manually. This is already correctly designed — no change needed.

### 6. Fallback: full-frame OCR if no plate detected

If the plate detector returns no detections (empty bbox), fall back to full-frame OCR as a degraded-but-better-than-nothing path. Log a warning.

## Configuration Changes

### New environment variable

```env
# ── Plate Detection ───────────────────────────────────────────
PLATE_DETECTION_MODEL=license_plate_detector    # YOLO model filename (without .pt)
```

### Add to .env.example

All vision settings currently missing from `.env.example`:

```env
# ── ANPR (Automatic Number Plate Recognition) ─────────────────
ANPR_ENABLED=false
ANPR_MODEL=paddleocr
ANPR_CONFIDENCE_THRESHOLD=0.8

# ── Vehicle Detection ─────────────────────────────────────────
VEHICLE_DETECTION_ENABLED=false
VEHICLE_DETECTION_MODEL=yolov8n
VEHICLE_DETECTION_CONFIDENCE_THRESHOLD=0.7

# ── Plate Detection ───────────────────────────────────────────
PLATE_DETECTION_MODEL=license_plate_detector

# ── Printer Paper Counter ─────────────────────────────────────
PRINTER_PAPER_COUNTER_ENABLED=false
PRINTER_PAPER_WARNING_THRESHOLD=50
PRINTER_PAPER_CRITICAL_THRESHOLD=10
```

## File Changes

| File | Change |
|------|--------|
| `services/vision.py` | Add plate detector model, crop-then-OCR, character constraints, fallback logic |
| `shared/config.py` | Add `plate_detection_model` setting |
| `.env.example` | Add all vision settings (currently missing) |
| `tests/services/test_vision.py` | Tests for plate detection, crop, constraints, fallback |
| `docs/plans/2026-04-26-anpr-vision-improvement-design.md` | This document |

## Implementation Steps

1. Add `plate_detection_model` config to `shared/config.py`
2. Add all vision settings to `.env.example`
3. Add plate detector model loader to `VisionService`
4. Modify `_extract_plate_number()` to accept plate detector results
5. Implement crop → OCR on cropped region
6. Add character constraints post-processing
7. Add full-frame OCR fallback when no plate detected
8. Write tests
9. Document model download instructions (Roboflow Universe)

## Accuracy Targets

| Stage | Expected Accuracy | Dependency |
|-------|------------------|------------|
| Plate detection model integrated | ~85-90% | Pre-built model quality |
| + Character constraints | ~90-93% | Indonesian plate format |
| + Threshold tuning on real data | ~93-96% | Field calibration |
| + IR camera/night lighting | ~95-97% | Hardware |

## Notes

- Vehicle detection code path remains untouched
- OCR engine (PaddleOCR/EasyOCR) remains configurable — no change
- All smart features remain opt-in via env vars
- Backward compatible — if `PLATE_DETECTION_MODEL` is not configured or model missing, fall back to full-frame OCR (current behavior)

# Smart Features — ANPR, Vehicle Detection, Printer Counter

> **Version**: 1.0  
> **Status**: Planned  
> **All features are configurable (on/off) via `.env` settings.**

---

## Table of Contents

1. [ANPR — Automatic Number Plate Recognition](#1-anpr--automatic-number-plate-recognition)
2. [Vehicle Type Detection](#2-vehicle-type-detection)
3. [Printer Paper Counter](#3-printer-paper-counter)
4. [Combined Vision Pipeline](#4-combined-vision-pipeline)
5. [Configuration Reference](#5-configuration-reference)

---

## 1. ANPR — Automatic Number Plate Recognition

### Purpose

Automatically read vehicle plate numbers from the entry/exit camera snapshot, eliminating manual plate entry and enabling plate-based transaction lookup.

### Configuration

```env
ANPR_ENABLED=true
ANPR_MODEL=paddleocr              # options: paddleocr, easyocr
ANPR_CONFIDENCE_THRESHOLD=0.8     # minimum confidence to accept a plate read (0.0 - 1.0)
```

### Tech Stack

| Component | Library | Model Size | Role |
|---|---|---|---|
| Plate Detection | YOLOv8-nano | ~6 MB | Locates the plate region in the snapshot |
| Text Recognition | PaddleOCR | ~15 MB | Reads text from the cropped plate region |

### Flow

```
┌──────────┐    ┌─────────────┐    ┌─────────────┐    ┌──────────────────┐
│ Snapshot  │───▶│ YOLOv8-nano │───▶│ PaddleOCR   │───▶│ plate_number     │
│ (RTSP)   │    │ plate crop  │    │ text read   │    │ stored in DB     │
└──────────┘    └─────────────┘    └─────────────┘    └──────────────────┘
```

1. Existing `snapshot_worker` captures RTSP frame
2. ANPR service receives the snapshot path
3. YOLOv8-nano detects and crops the plate region
4. PaddleOCR reads the text from the cropped image
5. Result stored in `parking_transactions.plate_number`
6. If confidence < threshold, field is left `NULL` (operator fills manually)

### Indonesian Plate Format

```
Standard:      B 1234 ABC     (DKI Jakarta)
Motorcycle:    B 1234 AB
Government:    RI 1
Military:      [varies]
```

- White/black or black/white text on contrasting background
- Consistent structure: 1–2 letters + 1–4 digits + 1–3 letters
- Well-supported by PaddleOCR pretrained models

### Hardware Requirements

- **Camera**: Existing IP camera (720p minimum, 1080p preferred). IR illumination recommended for night operation.
- **Compute**: Runs on CPU. No GPU required. ~150ms per frame on Intel N100 or similar.
- **No additional hardware needed** if cameras are already deployed.

### Plate Detection Model

For best accuracy, install a pre-trained license plate detection model:

1. Visit [Roboflow Universe](https://universe.roboflow.com)
2. Search for "license plate detection" or "plat nomor"
3. Download the YOLOv8 `.pt` weights file
4. Place it in the project root as `license_plate_detector.pt`
5. Optional: set `PLATE_DETECTION_MODEL=my_model_name` if using a different filename

**Recommended models** (community-uploaded, tested with Indonesian plates):
- `license-plate-detection-v8` (general purpose)
- Search `plat-nomor-indonesia` for country-specific models

When a plate detection model is available, the ANPR pipeline crops the plate region before OCR, significantly improving accuracy. If no model is found, the system falls back to full-frame OCR (reduced accuracy).

### Fallback When Disabled

When `ANPR_ENABLED=false`:
- `plate_number` remains `NULL` at entry
- Operator can manually enter plate at exit POS
- All other flows are unaffected

---

## 2. Vehicle Type Detection

### Purpose

Automatically classify the vehicle (car, motorcycle, truck, bus) from the camera snapshot. Prevents tariff miscalculation when vehicles use the wrong gate lane.

### Configuration

```env
VEHICLE_DETECTION_ENABLED=true
VEHICLE_DETECTION_MODEL=yolov8n                # YOLOv8-nano, pretrained on COCO
VEHICLE_DETECTION_CONFIDENCE_THRESHOLD=0.7     # minimum confidence to accept classification
```

### Supported Classes

| Class | COCO Label | Mapped To |
|---|---|---|
| Car | `car` | `MOBIL` |
| Motorcycle | `motorcycle` | `MOTOR` |
| Bus | `bus` | `BUS` |
| Truck | `truck` | `TRUCK` |

### Flow

```
┌──────────┐    ┌─────────────┐    ┌─────────────────┐
│ Snapshot  │───▶│ YOLOv8-nano │───▶│ vehicle_type_id │
│ (RTSP)   │    │ classify    │    │ stored in DB    │
└──────────┘    └─────────────┘    └─────────────────┘
```

1. Same snapshot used for ANPR (no additional camera call)
2. YOLOv8-nano classifies the dominant vehicle in the frame
3. Detected type is mapped to the `vehicle_types` table
4. If detected type ≠ gate-assigned type → operator alert generated
5. If confidence < threshold → gate-assigned type is used (no override)

### Operator Alert Example

```
⚠️ Gate MOTOR-1: Detected MOBIL (confidence 0.92)
    Expected: MOTOR
    Action: Tariff auto-corrected to MOBIL rate
```

### Fallback When Disabled

When `VEHICLE_DETECTION_ENABLED=false`:
- Vehicle type is determined by gate assignment (current behavior from V1)
- No detection alerts are generated

---

## 3. Printer Paper Counter

### Purpose

Track remaining paper for each thermal printer and alert operators before paper runs out. Prevents ticket/receipt print failures that could disrupt vehicle flow.

### Configuration

```env
PRINTER_PAPER_COUNTER_ENABLED=true
PRINTER_PAPER_WARNING_THRESHOLD=50      # yellow warning when remaining ≤ this
PRINTER_PAPER_CRITICAL_THRESHOLD=10     # red alert + Telegram notification when remaining ≤ this
```

### How It Works

#### Software Counter (Primary)

Each printer record in the database has a `paper_remaining` column:

```
┌─────────────────┐
│ printers table   │
├─────────────────┤
│ id               │
│ gate_id          │
│ type             │ ← network / serial
│ ip_address       │
│ paper_remaining  │ ← decremented on each print
│ paper_capacity   │ ← total per roll (default: 300)
│ last_refilled_at │
└─────────────────┘
```

#### Counter Logic

```python
# On each successful print
printer.paper_remaining -= 1

# Alert thresholds
if printer.paper_remaining <= CRITICAL_THRESHOLD:
    → Red alert on dashboard
    → Telegram notification to operator
    → If paper_remaining == 0:
        → Refuse to print
        → Show barcode on LED display instead
        → Log as "PRINT_SKIPPED_NO_PAPER"

elif printer.paper_remaining <= WARNING_THRESHOLD:
    → Yellow warning on dashboard
```

#### Paper Refill Flow

1. Operator loads new paper roll
2. Opens admin panel → Printers → selects printer
3. Clicks **"Paper Refilled"** button
4. Sets count (default: paper_capacity from printer config)
5. `paper_remaining` reset, `last_refilled_at` updated

#### Hardware Status (Bonus)

When the thermal printer supports ESC/POS `DLE EOT` status query:

```
DLE EOT 1 → Paper status
  Bit 5 = 1: Paper near end
  Bit 6 = 1: Paper ended
```

If supported, the `print_worker` queries this status after each print and cross-references with the software counter.

### Dashboard Display

```
┌─────────────────────────────────────────┐
│ PRINTER STATUS                          │
├──────────┬──────────┬───────┬───────────┤
│ Gate     │ Printer  │ Paper │ Status    │
├──────────┼──────────┼───────┼───────────┤
│ GATE-IN-1│ 192.168.1.10 │ 245/300│ ● OK     │
│ GATE-IN-2│ 192.168.1.11 │  42/300│ ● Warning│
│ GATE-OUT │ 192.168.1.12 │   5/300│ ● Critical│
└──────────┴──────────┴───────┴───────────┘
```

### Fallback When Disabled

When `PRINTER_PAPER_COUNTER_ENABLED=false`:
- No paper tracking or alerts
- Prints are attempted regardless
- Existing error handling catches actual print failures

---

## 4. Combined Vision Pipeline

When both ANPR and Vehicle Detection are enabled, they share a single inference pass:

```
                    ┌──────────────────────────────┐
                    │        Snapshot Image         │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │       YOLOv8-nano             │
                    │  (single model, single pass)  │
                    └──────┬───────────────┬────────┘
                           │               │
              ┌────────────▼──┐    ┌───────▼────────┐
              │ Vehicle class │    │ Plate region   │
              │ (car/motor/..)│    │ (bounding box) │
              └───────────────┘    └───────┬────────┘
                                           │
                                ┌──────────▼─────────┐
                                │    PaddleOCR        │
                                │  (text from crop)   │
                                └──────────┬─────────┘
                                           │
                                ┌──────────▼─────────┐
                                │ plate_number: str   │
                                │ vehicle_type: str   │
                                │ confidence: float   │
                                └────────────────────┘
```

**Total time**: ~150ms on CPU  
**Total model size**: ~21 MB (YOLOv8-nano 6 MB + PaddleOCR 15 MB)  
**Memory**: ~200 MB RAM peak during inference

---

## 5. Configuration Reference

### All Smart Feature Environment Variables

```env
# ── ANPR ──────────────────────────────────────────────
ANPR_ENABLED=false                          # default: disabled
ANPR_MODEL=paddleocr                        # paddleocr | easyocr
ANPR_CONFIDENCE_THRESHOLD=0.8               # 0.0 - 1.0

# ── Vehicle Detection ─────────────────────────────────
VEHICLE_DETECTION_ENABLED=false             # default: disabled
VEHICLE_DETECTION_MODEL=yolov8n             # YOLOv8-nano
VEHICLE_DETECTION_CONFIDENCE_THRESHOLD=0.7  # 0.0 - 1.0

# ── Printer Paper Counter ─────────────────────────────
PRINTER_PAPER_COUNTER_ENABLED=false         # default: disabled
PRINTER_PAPER_WARNING_THRESHOLD=50          # yellow alert
PRINTER_PAPER_CRITICAL_THRESHOLD=10         # red alert + notification
```

### Dependencies (Added to pyproject.toml)

```toml
[project.optional-dependencies]
vision = [
    "ultralytics>=8.0",     # YOLOv8
    "paddleocr>=2.7",       # PaddleOCR
    "paddlepaddle>=2.5",    # PaddlePaddle (CPU version)
]
```

Install only when vision features are needed:

```bash
pip install -e ".[vision]"
```

---

*Document Information — Created: April 2026 — E-Parking V2*

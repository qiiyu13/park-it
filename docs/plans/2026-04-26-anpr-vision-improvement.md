# ANPR Vision Pipeline Improvement — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add plate detection model stage to ANPR pipeline, enabling cropped-plate OCR with 90-95% accuracy on Indonesian plates.

**Architecture:** Two separate YOLO models — stock `yolov8n.pt` for vehicle type detection (unchanged) and a pre-built `license_plate_detector.pt` for plate bounding box detection. OCR runs on the cropped plate region with character constraints, falling back to full-frame OCR if no plate detected.

**Tech Stack:** Python 3.12+, YOLOv8 (ultralytics), PaddleOCR/EasyOCR, PIL/Pillow for image cropping, pytest-asyncio

**Design Doc:** `docs/plans/2026-04-26-anpr-vision-improvement-design.md`

---

### Task 1: Add `plate_detection_model` config to `shared/config.py`

**Files:**
- Modify: `shared/config.py:79-95`

**Step 1: Add the config field**

Insert after the ANPR section (line 84), before the Vehicle Detection section:

```python
    # ── Plate Detection (YOLO model for cropping plate region) ────────
    plate_detection_model: str = Field(
        default="license_plate_detector", alias="PLATE_DETECTION_MODEL"
    )
```

**Step 2: Verify**

Run: `python -c "from shared.config import get_settings; s = get_settings(); print(s.plate_detection_model)"`
Expected: `license_plate_detector`

**Step 3: Commit**

```bash
git add shared/config.py
git commit -m "feat: add plate_detection_model config for ANPR plate detector"
```

---

### Task 2: Add vision settings to `.env.example`

**Files:**
- Modify: `.env.example`

**Step 1: Append vision settings at end of file**

Add after the LOG_FORMAT line:

```env
# =============================================================================
# Vision
# =============================================================================
ANPR_ENABLED=false
ANPR_MODEL=paddleocr
ANPR_CONFIDENCE_THRESHOLD=0.8

VEHICLE_DETECTION_ENABLED=false
VEHICLE_DETECTION_MODEL=yolov8n
VEHICLE_DETECTION_CONFIDENCE_THRESHOLD=0.7

PLATE_DETECTION_MODEL=license_plate_detector

PRINTER_PAPER_COUNTER_ENABLED=false
PRINTER_PAPER_WARNING_THRESHOLD=50
PRINTER_PAPER_CRITICAL_THRESHOLD=10
```

**Step 2: Verify the file**

Check the file ends with the new section.

**Step 3: Commit**

```bash
git add .env.example
git commit -m "feat: add vision settings section to .env.example"
```

---

### Task 3: Add plate detector model loading to `VisionService`

**Files:**
- Modify: `services/vision.py:51-128`

**Step 1: Add plate detector instance variable**

In `__init__`, add after `self._ocr_model`:

```python
        self._plate_detector: Any | None = None
```

**Step 2: Add `_load_plate_detector()` method**

Insert after `_load_ocr()` (before line 130):

```python
    def _load_plate_detector(self) -> Any:
        """Load license plate detection YOLO model."""
        if self._plate_detector is not None:
            return self._plate_detector

        model_name = self._settings.plate_detection_model
        try:
            from ultralytics import YOLO
        except ImportError:
            raise ImportError(
                "ultralytics is required for plate detection. "
                "Install with: pip install -e '.[vision]'"
            )

        logger.info("loading_plate_detector", model=model_name)
        self._plate_detector = YOLO(f"{model_name}.pt")
        return self._plate_detector
```

**Step 3: Commit**

```bash
git add services/vision.py
git commit -m "feat: add plate detector model loading to VisionService"
```

---

### Task 4: Extract vehicle type from vehicle YOLO only (not plate detector)

**Files:**
- Modify: `services/vision.py:134-188` (`analyze_snapshot`)

**Step 1: Refactor `analyze_snapshot` to use vehicle YOLO for vehicles only**

Replace the YOLO section in `analyze_snapshot` (lines 159-162) to only run vehicle YOLO when vehicle detection is enabled (YOLO is no longer shared for ANPR — plate detector handles that separately):

```python
        # Run vehicle YOLO only if vehicle detection is enabled
        yolo_detections = []
        if detection_enabled:
            yolo_detections = self._run_yolo(str(image_path))
            result.raw_detections = yolo_detections

        # Run plate detection if ANPR is enabled
        plate_detections = []
        if anpr_enabled:
            try:
                plate_detector = self._load_plate_detector()
                plate_results = plate_detector(str(image_path), verbose=False)
                for det in plate_results[0].boxes:
                    plate_detections.append({
                        "class_name": plate_detector.names[int(det.cls)],
                        "confidence": float(det.conf),
                        "bbox": det.xyxy[0].tolist(),
                    })
            except Exception as exc:
                logger.warning("plate_detection_failed", error=str(exc))
                plate_detections = []
```

**Step 2: Commit**

```bash
git add services/vision.py
git commit -m "feat: separate plate detection from vehicle YOLO in analyze_snapshot"
```

---

### Task 5: Implement crop-then-OCR in `_extract_plate_number`

**Files:**
- Modify: `services/vision.py:229-298` (`_extract_plate_number`)

**Step 1: Rewrite `_extract_plate_number` to accept plate detections and crop**

New method signature and implementation:

```python
    def _extract_plate_number(
        self, image_path: str, plate_detections: list[dict[str, Any]]
    ) -> tuple[str | None, float]:
        """Extract plate number by cropping detected plate region, then OCR.

        If a plate detection with sufficient confidence is available, crops
        to that bounding box before OCR.  Falls back to full-frame OCR if
        no plate is detected.
        """
        import re

        ocr = self._load_ocr()

        # Try to crop to detected plate region
        crop_bbox: list[float] | None = None
        for det in plate_detections:
            if det["confidence"] >= self._settings.anpr_confidence_threshold:
                crop_bbox = det["bbox"]
                break

        # Run OCR on cropped region or full image
        ocr_image_path = image_path
        if crop_bbox is not None:
            try:
                from PIL import Image
                img = Image.open(image_path)
                cropped = img.crop(tuple(crop_bbox))
                import tempfile
                import os
                with tempfile.NamedTemporaryFile(
                    suffix=".jpg", delete=False
                ) as tmp:
                    cropped.save(tmp.name, "JPEG", quality=95)
                    ocr_image_path = tmp.name
                    tmp_path = tmp.name
                logger.info("plate_cropped_for_ocr", bbox=crop_bbox)
            except Exception as exc:
                logger.warning("plate_crop_failed", error=str(exc))
                crop_bbox = None
                ocr_image_path = image_path

        try:
            result = self._run_ocr(ocr_image_path)
        finally:
            if crop_bbox is not None:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        # Parse OCR result
        if not result:
            return None, 0.0

        raw_text, avg_conf = result
        plate = self._parse_indonesian_plate(raw_text)

        return plate, avg_conf
```

**Step 2: Add `_run_ocr` helper method**

Insert before `_extract_plate_number`:

```python
    def _run_ocr(self, image_path: str) -> tuple[str | None, float]:
        """Run OCR on an image and return concatenated text with avg confidence."""
        ocr = self._load_ocr()
        ocr_engine = self._settings.anpr_model

        if ocr_engine == "paddleocr":
            result = ocr.ocr(image_path, cls=True)
            if not result or not result[0]:
                return None, 0.0
            texts = []
            total_conf = 0.0
            for line in result[0]:
                texts.append(line[1][0])
                total_conf += line[1][1]
            avg_conf = total_conf / len(result[0]) if result[0] else 0.0
            return " ".join(texts).upper(), avg_conf

        elif ocr_engine == "easyocr":
            result = ocr.readtext(image_path)
            if not result:
                return None, 0.0
            texts = []
            total_conf = 0.0
            for _bbox, text, conf in result:
                texts.append(text)
                total_conf += conf
            avg_conf = total_conf / len(result) if result else 0.0
            return " ".join(texts).upper(), avg_conf

        return None, 0.0
```

**Step 3: Add `_parse_indonesian_plate` helper**

```python
    @staticmethod
    def _parse_indonesian_plate(text: str) -> str | None:
        """Parse Indonesian plate number from OCR text with character constraints.

        Format: 1-2 letters + 1-4 digits + 0-3 letters  (e.g. B 1234 ABC)
        """
        import re

        # Strip non-alphanumeric, uppercase
        cleaned = re.sub(r"[^A-Z0-9]", "", text.upper().strip())

        if not cleaned:
            return None

        # Try Indonesian plate pattern
        pattern = re.compile(r"([A-Z]{1,2})(\d{1,4})([A-Z]{0,3})")
        match = pattern.search(cleaned)

        if not match:
            return None

        prefix, digits, suffix = match.groups()
        plate = f"{prefix} {digits}"
        if suffix:
            plate += f" {suffix}"

        return plate
```

**Step 4: Update imports at top of file**

Add `import os` and `import tempfile` to imports if not already present.

**Step 5: Commit**

```bash
git add services/vision.py
git commit -m "feat: implement crop-then-OCR with Indonesian plate parsing"
```

---

### Task 6: Wire updated `_extract_plate_number` into `analyze_snapshot`

**Files:**
- Modify: `services/vision.py:172-178` (`analyze_snapshot`)

**Step 1: Pass plate_detections to `_extract_plate_number`**

Change line 173-174 from:

```python
            plate_text, plate_conf = self._extract_plate_number(
                str(image_path), yolo_detections
            )
```

to:

```python
            plate_text, plate_conf = self._extract_plate_number(
                str(image_path), plate_detections
            )
```

**Step 2: Commit**

```bash
git add services/vision.py
git commit -m "fix: wire plate_detections into _extract_plate_number"
```

---

### Task 7: Write tests for ANPR vision pipeline

**Files:**
- Create: `api/tests/test_vision.py`

**Step 1: Write the test file**

```python
"""Tests for vision service ANPR pipeline improvements."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestPlateParsing:
    """Indonesian plate number parsing."""

    @pytest.mark.parametrize("text,expected", [
        ("B 1234 ABC", "B 1234 ABC"),
        ("B1234ABC", "B 1234 ABC"),
        ("b1234abc", "B 1234 ABC"),
        ("  B 1234 ABC  ", "B 1234 ABC"),
        ("AB 5678 XYZ", "AB 5678 XYZ"),
        ("D 1", "D 1"),
        ("B 1234", "B 1234"),
        ("L 9999 ZZZ", "L 9999 ZZZ"),
    ])
    def test_valid_indonesian_plates(self, text, expected):
        from services.vision import VisionService
        result = VisionService._parse_indonesian_plate(text)
        assert result == expected

    @pytest.mark.parametrize("text", [
        "",
        "   ",
        "HELLO",
        "STORENAME",
        "12 3456",
        "ABC 1234",  # too many prefix letters for Indo plate
    ])
    def test_invalid_inputs_return_none(self, text):
        from services.vision import VisionService
        result = VisionService._parse_indonesian_plate(text)
        assert result is None


class TestCropOcrFallback:
    """Tests for plate detector failure fallback to full-frame OCR."""

    @pytest.fixture
    def mock_ocr(self):
        with patch("services.vision.VisionService._load_ocr") as mock:
            mock_ocr_instance = MagicMock()
            mock.return_value = mock_ocr_instance
            yield mock_ocr_instance

    @pytest.mark.asyncio
    async def test_fallback_to_full_frame_when_no_plate_detected(self):
        """When plate_detections is empty, OCR runs on full frame."""
        from services.vision import VisionService

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            # Create a minimal valid JPEG
            from PIL import Image
            img = Image.new("RGB", (100, 100), color="white")
            img.save(tmp.name, "JPEG")
            tmp_path = tmp.name

        try:
            svc = VisionService()

            # Empty plate_detections — should try full-frame OCR
            with patch.object(svc, "_run_ocr", return_value=("B 1234 AB", 0.85)) as mock_run:
                plate, conf = svc._extract_plate_number(tmp_path, [])
                assert mock_run.called
                assert mock_run.call_args[0][0] == tmp_path  # full image path
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_no_ocr_result_returns_none(self):
        """When OCR returns None, plate is None."""
        from services.vision import VisionService

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            from PIL import Image
            img = Image.new("RGB", (100, 100), color="white")
            img.save(tmp.name, "JPEG")
            tmp_path = tmp.name

        try:
            svc = VisionService()
            with patch.object(svc, "_run_ocr", return_value=(None, 0.0)):
                plate, conf = svc._extract_plate_number(tmp_path, [])
                assert plate is None
                assert conf == 0.0
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_plate_detector_loads_when_anpr_enabled(self):
        """Verifies plate detector is loaded when ANPR is enabled."""
        from services.vision import VisionService

        svc = VisionService()
        mock_yolo = MagicMock()
        mock_yolo.return_value = [MagicMock()]
        mock_yolo.return_value[0].boxes = []

        with patch("services.vision.YOLO", return_value=mock_yolo):
            detector = svc._load_plate_detector()
            assert detector is not None
            assert svc._plate_detector is not None
            # Second call returns cached instance
            detector2 = svc._load_plate_detector()
            assert detector2 is detector
```
```

**Step 1: Write test file**

Create `api/tests/test_vision.py` with the content above.

**Step 2: Run tests to verify failures on any unimplemented parts**

Run: `pytest api/tests/test_vision.py -v`
Expected: Tests that pass (plate parsing) and tests that may fail if full implementation isn't complete.

**Step 3: Install PIL if needed**

Check: `python -c "from PIL import Image"` — if fails, it should be available as a testing dependency. PIL comes with `pillow` which is pulled by `ultralytics`. If not installed, note it in test requirements.

**Step 4: Commit**

```bash
git add api/tests/test_vision.py
git commit -m "test: add ANPR vision pipeline tests"
```

---

### Task 8: Run full test suite and lint

**Files:**
- Verify: All changed files

**Step 1: Run the new vision tests**

Run: `pytest api/tests/test_vision.py -v`
Expected: All tests PASS

**Step 2: Run ruff lint**

Run: `ruff check services/vision.py shared/config.py`
Expected: No errors

**Step 3: Run mypy type check**

Run: `mypy services/vision.py`
Expected: No new errors (may have pre-existing Any types — acceptable)

**Step 4: Fix any issues and commit**

```bash
git add -A
git commit -m "chore: fix lint and type issues in vision pipeline"
```

---

### Task 9: Document model download instructions

**Files:**
- Modify: `docs/SMART_FEATURES.md`

**Step 1: Update ANPR section to document plate detector model**

Append to section 1 (ANPR) after the hardware requirements:

```markdown
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

If no model is available, the system falls back to full-frame OCR (reduced accuracy).
```

**Step 2: Commit**

```bash
git add docs/SMART_FEATURES.md
git commit -m "docs: add plate detector model download instructions to SMART_FEATURES"
```

---

## Post-Implementation Notes

1. **After downloading a plate detector model**: Place `<model_name>.pt` in the project root directory, set `ANPR_ENABLED=true` and `PLATE_DETECTION_MODEL=<model_name>` in `.env`, restart the API.

2. **If model fails to load**: Check the API logs for `loading_plate_detector` and any subsequent errors. The system will log a warning `plate_detection_failed` and fall back gracefully to full-frame OCR.

3. **Accuracy validation**: Run 10-20 real gate snapshots through the pipeline and compare plate results against manual reads. Tune `ANPR_CONFIDENCE_THRESHOLD` based on results.
```

**Files changed across all tasks:**
- `shared/config.py` — new `plate_detection_model` setting
- `.env.example` — all vision settings added
- `services/vision.py` — plate detector loading, crop-then-OCR, character constraints, fallback
- `api/tests/test_vision.py` — new test file
- `docs/SMART_FEATURES.md` — model download instructions

**Estimated total time:** 45-60 minutes (excluding model download/evaluation from Roboflow Universe)

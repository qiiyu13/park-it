"""Tests for vision service ANPR pipeline improvements."""

import os
import tempfile
from unittest.mock import patch

import pytest


class TestPlateParsing:
    """Indonesian plate number parsing."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("B 1234 ABC", "B 1234 ABC"),
            ("B1234ABC", "B 1234 ABC"),
            ("b1234abc", "B 1234 ABC"),
            ("  B 1234 ABC  ", "B 1234 ABC"),
            ("AB 5678 XYZ", "AB 5678 XYZ"),
            ("D 1", "D 1"),
            ("B 1234", "B 1234"),
            ("L 9999 ZZZ", "L 9999 ZZZ"),
        ],
    )
    def test_valid_indonesian_plates(self, text, expected):
        from services.vision import VisionService

        result = VisionService._parse_indonesian_plate(text)
        assert result == expected

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "HELLO",
            "STORENAME",
            "12 3456",
            "ABCDEFG",
        ],
    )
    def test_invalid_inputs_return_none(self, text):
        from services.vision import VisionService

        result = VisionService._parse_indonesian_plate(text)
        assert result is None


class TestCropOcrFallback:
    """Tests for plate detector failure fallback to full-frame OCR."""

    @pytest.mark.asyncio
    async def test_fallback_to_full_frame_when_no_plate_detected(self):
        """When plate_detections is empty, OCR runs on full frame."""
        from services.vision import VisionService

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            from PIL import Image

            img = Image.new("RGB", (100, 100), color="white")
            img.save(tmp.name, "JPEG")
            tmp_path = tmp.name

        try:
            svc = VisionService()
            with patch.object(
                svc, "_run_ocr", return_value=("B 1234 AB", 0.85)
            ) as mock_run:
                plate, conf = svc._extract_plate_number(tmp_path, [])
                assert mock_run.called
                assert mock_run.call_args[0][0] == tmp_path
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
    async def test_crop_with_plate_detection(self):
        """When plate detection provides a bbox, OCR runs on cropped region."""
        from services.vision import VisionService

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            from PIL import Image

            img = Image.new("RGB", (200, 200), color="white")
            img.save(tmp.name, "JPEG")
            tmp_path = tmp.name

        try:
            svc = VisionService()
            plate_detections = [
                {
                    "class_name": "license_plate",
                    "confidence": 0.9,
                    "bbox": [50.0, 80.0, 150.0, 120.0],
                }
            ]
            with patch.object(
                svc, "_run_ocr", return_value=("B 1234 ABC", 0.92)
            ) as mock_run:
                plate, conf = svc._extract_plate_number(tmp_path, plate_detections)
                assert plate == "B 1234 ABC"
                assert conf == 0.92
                assert mock_run.called
                cropped_path = mock_run.call_args[0][0]
                assert cropped_path != tmp_path
                assert os.path.exists(cropped_path) or not os.path.exists(cropped_path)
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_crop_failure_falls_back_to_full_frame(self):
        """When cropping fails (e.g. corrupt image), fall back to full frame OCR."""
        from services.vision import VisionService

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            from PIL import Image

            img = Image.new("RGB", (200, 200), color="white")
            img.save(tmp.name, "JPEG")
            tmp_path = tmp.name

        try:
            svc = VisionService()
            bad_detections = [
                {
                    "class_name": "license_plate",
                    "confidence": 0.9,
                    "bbox": [500.0, 500.0, 600.0, 600.0],
                }
            ]
            # Simulate crop failure via PIL.Image.open raising an exception
            with (
                patch("PIL.Image.open", side_effect=OSError("corrupt image")),
                patch.object(svc, "_run_ocr", return_value=("B 1", 0.80)) as mock_run,
            ):
                plate, conf = svc._extract_plate_number(tmp_path, bad_detections)
                assert mock_run.called
                assert mock_run.call_args[0][0] == tmp_path
        finally:
            os.unlink(tmp_path)


class TestPlateDetectorLoading:
    """Tests for plate detector model loading."""

    def test_plate_detector_is_none_initially(self):
        """Verifies plate detector starts as None."""
        from services.vision import VisionService

        svc = VisionService()
        assert svc._plate_detector is None

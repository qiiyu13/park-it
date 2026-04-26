"""Vision service — ANPR (plate recognition) and vehicle type detection.

This module provides a unified interface for camera-based analysis.
All models are lightweight (~27 MB total) and run on CPU.

Two YOLO models are used independently:
  - Vehicle YOLO (yolov8n) — detects car/motorcycle/bus/truck
  - Plate Detector YOLO — detects license plate regions for cropping before OCR

OCR runs on the cropped plate region when a plate detector is available,
falling back to full-frame OCR if no plate is detected.

Dependencies (optional, installed via `pip install -e ".[vision]"`):
    - ultralytics (YOLOv8)
    - paddleocr
    - paddlepaddle (CPU)
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shared.config import get_settings
from shared.logging import get_logger

logger = get_logger("vision_service")

# COCO class names → internal vehicle type codes
COCO_TO_VEHICLE_TYPE: dict[str, str] = {
    "car": "MOBIL",
    "motorcycle": "MOTOR",
    "bus": "BUS",
    "truck": "TRUCK",
}


@dataclass
class VisionResult:
    """Result from the combined vision pipeline."""

    # ANPR
    plate_number: str | None = None
    plate_confidence: float = 0.0

    # Vehicle detection
    vehicle_type: str | None = None
    vehicle_confidence: float = 0.0

    # Raw detections for debugging
    raw_detections: list[dict[str, Any]] = field(default_factory=list)


class VisionService:
    """Lazy-loading vision service.

    Models are only loaded when first needed.  Vehicle detection uses a
    dedicated YOLO model; ANPR uses a separate plate detector YOLO model
    whose output is cropped before OCR.
    """

    _instance: VisionService | None = None

    def __init__(self) -> None:
        self._yolo_model: Any | None = None
        self._ocr_model: Any | None = None
        self._plate_detector: Any | None = None
        self._settings = get_settings()

    @classmethod
    def get_instance(cls) -> VisionService:
        """Return singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Lazy model loading
    # ------------------------------------------------------------------

    def _load_yolo(self) -> Any:
        """Load YOLOv8-nano model on first use."""
        if self._yolo_model is not None:
            return self._yolo_model

        try:
            from ultralytics import YOLO
        except ImportError:
            raise ImportError(
                "ultralytics is required for vision features. "
                "Install with: pip install -e '.[vision]'"
            )

        model_name = self._settings.vehicle_detection_model
        logger.info("loading_yolo_model", model=model_name)
        self._yolo_model = YOLO(f"{model_name}.pt")
        return self._yolo_model

    def _load_ocr(self) -> Any:
        """Load OCR model on first use."""
        if self._ocr_model is not None:
            return self._ocr_model

        ocr_engine = self._settings.anpr_model

        if ocr_engine == "paddleocr":
            try:
                from paddleocr import PaddleOCR
            except ImportError:
                raise ImportError(
                    "paddleocr is required for ANPR. "
                    "Install with: pip install -e '.[vision]'"
                )
            logger.info("loading_paddleocr")
            self._ocr_model = PaddleOCR(
                use_angle_cls=True,
                lang="en",
                show_log=False,
            )
        elif ocr_engine == "easyocr":
            try:
                import easyocr
            except ImportError:
                raise ImportError(
                    "easyocr is required for ANPR with easyocr engine. "
                    "Install with: pip install easyocr"
                )
            logger.info("loading_easyocr")
            self._ocr_model = easyocr.Reader(["en"], gpu=False)
        else:
            raise ValueError(f"Unknown ANPR model: {ocr_engine}")

        return self._ocr_model

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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def analyze_snapshot(self, image_path: str | Path) -> VisionResult:
        """Run the combined vision pipeline on a snapshot image.

        Performs vehicle detection and/or ANPR based on configuration.
        Vehicle detection uses a dedicated YOLO model; ANPR uses a
        separate plate detector YOLO model with cropped OCR.

        Args:
            image_path: Path to the snapshot image file.

        Returns:
            VisionResult with plate_number, vehicle_type, and confidences.
        """
        image_path = Path(image_path)
        if not image_path.exists():
            logger.warning("snapshot_not_found", path=str(image_path))
            return VisionResult()

        result = VisionResult()
        anpr_enabled = self._settings.anpr_enabled
        detection_enabled = self._settings.vehicle_detection_enabled

        if not anpr_enabled and not detection_enabled:
            return result

        # Run vehicle YOLO only if vehicle detection is enabled
        yolo_detections = []
        if detection_enabled:
            yolo_detections = self._run_yolo(str(image_path))
            result.raw_detections = yolo_detections

        # Run plate detection if ANPR is enabled
        plate_detections: list[dict[str, Any]] = []
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

        # Extract vehicle type from YOLO results
        if detection_enabled:
            vtype, vconf = self._extract_vehicle_type(yolo_detections)
            if vconf >= self._settings.vehicle_detection_confidence_threshold:
                result.vehicle_type = vtype
                result.vehicle_confidence = vconf

        # Extract plate text via OCR (uses plate detections for cropping)
        if anpr_enabled:
            plate_text, plate_conf = self._extract_plate_number(
                str(image_path), plate_detections
            )
            if plate_conf >= self._settings.anpr_confidence_threshold:
                result.plate_number = plate_text
                result.plate_confidence = plate_conf

        logger.info(
            "vision_analysis_complete",
            path=str(image_path),
            plate=result.plate_number,
            vehicle_type=result.vehicle_type,
        )

        return result

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _run_yolo(self, image_path: str) -> list[dict[str, Any]]:
        """Run YOLOv8 detection on an image."""
        model = self._load_yolo()
        results = model(image_path, verbose=False)

        detections = []
        for det in results[0].boxes:
            class_id = int(det.cls)
            class_name = model.names[class_id]
            confidence = float(det.conf)
            bbox = det.xyxy[0].tolist()

            detections.append({
                "class_name": class_name,
                "class_id": class_id,
                "confidence": confidence,
                "bbox": bbox,
            })

        return detections

    def _extract_vehicle_type(
        self, detections: list[dict[str, Any]]
    ) -> tuple[str | None, float]:
        """Extract best vehicle type classification from YOLO detections."""
        best_type: str | None = None
        best_conf = 0.0

        for det in detections:
            class_name = det["class_name"]
            if class_name in COCO_TO_VEHICLE_TYPE and det["confidence"] > best_conf:
                best_type = COCO_TO_VEHICLE_TYPE[class_name]
                best_conf = det["confidence"]

        return best_type, best_conf

    def _run_ocr(self, image_path: str) -> tuple[str | None, float]:
        """Run OCR on an image and return concatenated text with average confidence."""
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

    def _extract_plate_number(
        self, image_path: str, plate_detections: list[dict[str, Any]]
    ) -> tuple[str | None, float]:
        """Extract plate number by cropping detected plate region, then OCR.

        If a plate detection with sufficient confidence is available, crops
        to that bounding box before OCR.  Falls back to full-frame OCR if
        no plate is detected.
        """
        # Try to crop to detected plate region
        crop_bbox: list[float] | None = None
        for det in plate_detections:
            if det["confidence"] >= self._settings.anpr_confidence_threshold:
                crop_bbox = det["bbox"]
                break

        # Run OCR on cropped region or full image
        ocr_image_path = image_path
        tmp_path: str | None = None
        if crop_bbox is not None:
            try:
                from PIL import Image

                img = Image.open(image_path)
                cropped = img.crop(tuple(crop_bbox))
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
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        if not result:
            return None, 0.0

        raw_text, avg_conf = result
        plate = self._parse_indonesian_plate(raw_text)

        return plate, avg_conf

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

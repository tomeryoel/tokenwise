"""Focused unit tests for image-analyser-service (Day 8)."""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from analyser import (
    MAX_IMAGE_BYTES,
    ImageValidationError,
    classify_image,
    decode_base64_image,
)


def _png_b64(color: tuple[int, int, int], size: tuple[int, int] = (640, 480)) -> str:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_decode_base64_image_accepts_data_url():
    raw = _png_b64((10, 20, 30))
    data_url = f"data:image/png;base64,{raw}"
    img = decode_base64_image(data_url)
    assert img.size == (640, 480)
    assert img.mode == "RGB"


def test_decode_rejects_empty_payload():
    with pytest.raises(ImageValidationError):
        decode_base64_image("")
    with pytest.raises(ImageValidationError):
        decode_base64_image("   ")


def test_decode_rejects_corrupt_payload():
    with pytest.raises(ImageValidationError):
        decode_base64_image(base64.b64encode(b"not-an-image").decode("ascii"))


def test_decode_rejects_oversized_payload():
    huge = base64.b64encode(b"x" * (MAX_IMAGE_BYTES + 1)).decode("ascii")
    with pytest.raises(ImageValidationError, match="maximum size"):
        decode_base64_image(huge)


def test_classify_image_returns_contract_fields():
    img = decode_base64_image(_png_b64((120, 80, 200), (800, 600)))
    result = classify_image(img)
    assert result.class_name in {
        "screenshot", "diagram", "chart", "document_photo"
    }
    assert 0.0 <= result.confidence <= 1.0
    assert 0.0 <= result.visual_complexity <= 1.0
    assert isinstance(result.needs_vision_model, bool)
    assert result.model == "resnet18"
    assert result.inference_ms >= 0.0


def test_visual_complexity_is_bounded_and_consistent_with_threshold():
    img = Image.effect_noise((640, 480), 80.0).convert("RGB")
    result = classify_image(img)
    assert 0.0 <= result.visual_complexity <= 1.0
    assert result.needs_vision_model is (result.visual_complexity >= 0.5)
    # High-entropy noisy images should score non-trivially (routing signal).
    assert result.visual_complexity >= 0.3



def test_analyse_endpoint_without_bytes():
    from fastapi.testclient import TestClient
    from main import app

    tc = TestClient(app)
    res = tc.post("/analyse", json={"filename": "empty.png"})
    assert res.status_code == 200
    body = res.json()
    assert body["class"] == "unknown"
    assert body["visual_complexity"] == 0.0
    assert body["model"] == "resnet18"


def test_analyse_endpoint_with_image_bytes():
    from fastapi.testclient import TestClient
    from main import app

    tc = TestClient(app)
    res = tc.post(
        "/analyse",
        json={"filename": "sample.png", "image_base64": _png_b64((40, 90, 160))},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["class"] != "unknown"
    assert body["confidence"] > 0.0
    assert body["visual_complexity"] > 0.0
    assert body["model"] == "resnet18"
    assert "weights" in body


def test_analyse_endpoint_rejects_corrupt_image():
    from fastapi.testclient import TestClient
    from main import app

    tc = TestClient(app)
    res = tc.post(
        "/analyse",
        json={
            "filename": "bad.png",
            "image_base64": base64.b64encode(b"not-an-image").decode("ascii"),
        },
    )
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail["code"] == "INVALID_IMAGE"


def test_health_endpoint():
    from fastapi.testclient import TestClient
    from main import app

    tc = TestClient(app)
    res = tc.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == "image-analyser-service"
    assert body["model"] == "resnet18"

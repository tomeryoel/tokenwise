"""image-analyser-service — PyTorch ResNet18 classification (Day 8)."""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from analyser import (
    MODEL_NAME,
    WEIGHTS_ID,
    AnalysisResult,
    ImageValidationError,
    classify_image,
    decode_base64_image,
)

SERVICE_NAME = "image-analyser-service"

app = FastAPI(title=SERVICE_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyseRequest(BaseModel):
    filename: str | None = None
    image_base64: str | None = Field(
        default=None,
        description="Base64-encoded image bytes (optionally data-URL prefixed).",
    )


def _to_response(result: AnalysisResult) -> dict:
    return {
        "class": result.class_name,
        "confidence": result.confidence,
        "visual_complexity": result.visual_complexity,
        "needs_vision_model": result.needs_vision_model,
        "model": result.model,
        "weights": WEIGHTS_ID,
        "inference_ms": result.inference_ms,
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "model": MODEL_NAME,
        "weights": WEIGHTS_ID,
    }


@app.post("/analyse")
def analyse(req: AnalyseRequest):
    if not req.image_base64:
        # Backward-compatible stub when no bytes are supplied.
        return {
            "class": "unknown",
            "confidence": 0.0,
            "visual_complexity": 0.0,
            "needs_vision_model": False,
            "model": MODEL_NAME,
            "weights": WEIGHTS_ID,
            "inference_ms": 0.0,
        }

    try:
        img = decode_base64_image(req.image_base64)
        result = classify_image(img)
    except ImageValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_IMAGE", "message": str(exc)},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_IMAGE", "message": "failed to analyse image"},
        ) from exc

    return _to_response(result)

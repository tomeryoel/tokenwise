"""PyTorch ResNet18 image classification + visual complexity scoring (Day 8)."""

from __future__ import annotations

import base64
import io
import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import torch
import torch.nn.functional as F
from PIL import Image, ImageFile, UnidentifiedImageError
from torchvision.models import ResNet18_Weights, resnet18

if TYPE_CHECKING:
    from PIL.Image import Image as PilImage

# Cap decompression / decode cost for the academic MVP.
Image.MAX_IMAGE_PIXELS = 25_000_000
ImageFile.LOAD_TRUNCATED_IMAGES = False

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MiB decoded payload
MODEL_NAME = "resnet18"
WEIGHTS_ID = "IMAGENET1K_V1"

CLASSES = ("screenshot", "diagram", "chart", "document_photo")

# ImageNet label keywords mapped to MomiHelm coarse classes.
_CLASS_KEYWORDS: dict[str, tuple[str, ...]] = {
    "screenshot": (
        "monitor", "screen", "laptop", "desktop computer", "notebook",
        "hand-held computer", "cellular telephone", "television", "web site",
        "crt", "computer keyboard", "mouse",
    ),
    "chart": (
        "bar chart", "abacus", "scale", "analog clock", "digital clock",
        "odometer", "slide rule", "graph", "histogram",
    ),
    "diagram": (
        "jigsaw", "maze", "crossword", "puzzle", "map", "blueprint",
        "technical", "schematic", "traffic light", "street sign",
    ),
    "document_photo": (
        "envelope", "menu", "book jacket", "comic book", "newspaper",
        "binder", "library", "bookshop", "letter", "cardigan",
        "file", "paper", "document", "notebook", "writing",
    ),
}

_model = None
_preprocess = None
_categories: list[str] | None = None


@dataclass(frozen=True)
class AnalysisResult:
    class_name: str
    confidence: float
    visual_complexity: float
    needs_vision_model: bool
    model: str = MODEL_NAME
    inference_ms: float = 0.0


class ImageValidationError(ValueError):
    """Raised for empty, oversized, or corrupt image payloads."""


def _load_model() -> None:
    global _model, _preprocess, _categories
    if _model is not None:
        return
    weights = ResNet18_Weights.IMAGENET1K_V1
    _model = resnet18(weights=weights)
    _model.eval()
    _preprocess = weights.transforms()
    _categories = list(weights.meta["categories"])


def decode_base64_image(image_base64: str) -> PilImage:
    if not image_base64 or not str(image_base64).strip():
        raise ImageValidationError("empty image payload")
    raw = image_base64.strip()
    if "," in raw and raw.lower().startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise ImageValidationError("invalid base64 image payload") from exc
    if not data:
        raise ImageValidationError("empty image payload")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageValidationError(
            f"image exceeds maximum size of {MAX_IMAGE_BYTES} bytes"
        )
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except UnidentifiedImageError as exc:
        raise ImageValidationError("unrecognized or corrupt image data") from exc
    except Image.DecompressionBombError as exc:
        raise ImageValidationError("image dimensions exceed safe limits") from exc
    except OSError as exc:
        raise ImageValidationError(f"failed to decode image: {exc}") from exc
    return img.convert("RGB")


def _bucket_scores(label: str, score: float, buckets: dict[str, float]) -> None:
    lower = label.lower()
    for class_name, keywords in _CLASS_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            buckets[class_name] = max(buckets.get(class_name, 0.0), score)


def _geometry_hint(img: PilImage) -> dict[str, float]:
    w, h = img.size
    if w <= 0 or h <= 0:
        return {}
    aspect = w / h
    hints: dict[str, float] = {}
    if aspect >= 1.25:
        hints["screenshot"] = 0.35
    if 0.75 <= aspect <= 1.35:
        hints["document_photo"] = 0.2
        hints["diagram"] = 0.15
    if w * h >= 500_000:
        hints["screenshot"] = hints.get("screenshot", 0.0) + 0.1
    return hints


def _visual_complexity(img: PilImage, probs: torch.Tensor) -> float:
    top5 = probs[:5].tolist()
    entropy = -sum(p * math.log(p + 1e-12) for p in top5 if p > 0)
    entropy_norm = min(1.0, entropy / math.log(5))

    # Full-pixel variance for modest images; sample for large ones.
    sample = img if (img.size[0] * img.size[1]) <= 300_000 else img.resize((128, 128))
    pixels = list(sample.getdata())
    if not pixels:
        color_var = 0.0
    else:
        rs = [p[0] for p in pixels]
        gs = [p[1] for p in pixels]
        bs = [p[2] for p in pixels]
        mean_r = sum(rs) / len(rs)
        mean_g = sum(gs) / len(gs)
        mean_b = sum(bs) / len(bs)
        var = (
            sum((r - mean_r) ** 2 for r in rs)
            + sum((g - mean_g) ** 2 for g in gs)
            + sum((b - mean_b) ** 2 for b in bs)
        ) / (3 * len(pixels))
        color_var = min(1.0, math.sqrt(var) / 70.0)

    w, h = img.size
    res_factor = min(1.0, math.log10(max(w * h, 1)) / 6.5)

    score = 0.35 * entropy_norm + 0.35 * color_var + 0.30 * res_factor
    return round(min(1.0, max(0.0, score)), 3)


def classify_image(img: PilImage) -> AnalysisResult:
    """Run ResNet18 inference and map to MomiHelm coarse classes."""
    _load_model()
    assert _model is not None and _preprocess is not None and _categories is not None

    started = time.perf_counter()
    tensor = _preprocess(img).unsqueeze(0)
    with torch.inference_mode():
        logits = _model(tensor)
        probs = F.softmax(logits, dim=1)[0]

    topk = torch.topk(probs, k=5)
    buckets: dict[str, float] = {}
    for idx, score in zip(topk.indices.tolist(), topk.values.tolist()):
        _bucket_scores(_categories[idx], float(score), buckets)

    for class_name, boost in _geometry_hint(img).items():
        buckets[class_name] = buckets.get(class_name, 0.0) + boost

    if not buckets:
        buckets["document_photo"] = 0.4

    best_class = max(buckets, key=buckets.get)
    raw_conf = buckets[best_class]
    confidence = round(min(0.99, max(0.35, raw_conf)), 3)

    complexity = _visual_complexity(img, topk.values)
    needs_vision = complexity >= 0.5
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)

    return AnalysisResult(
        class_name=best_class,
        confidence=confidence,
        visual_complexity=complexity,
        needs_vision_model=needs_vision,
        model=MODEL_NAME,
        inference_ms=elapsed_ms,
    )

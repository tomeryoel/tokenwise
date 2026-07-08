"""image-analyser-service (walking skeleton).

Day 1-2: mock responses only. Real PyTorch (ResNet18 transfer learning) image
classification + visual complexity scoring comes later. Not called by the
skeleton n8n flow unless a file is attached.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/analyse")
def analyse(req: AnalyseRequest):
    # MOCK: static classification. Real PyTorch inference comes later.
    return {
        "class": "unknown",
        "confidence": 0.0,
        "visual_complexity": 0.0,
        "needs_vision_model": False,
    }

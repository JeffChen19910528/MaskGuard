from .base import IOcrEngine
from .paddle_engine import PaddleOcrEngine
from .tesseract_engine import LocalOcrEngine

__all__ = ["IOcrEngine", "LocalOcrEngine", "PaddleOcrEngine"]

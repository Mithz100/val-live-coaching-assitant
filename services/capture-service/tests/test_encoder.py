"""Unit tests for encoder.py — no hardware required."""

import numpy as np
import pytest

# Patch settings before import
import sys
from unittest.mock import MagicMock, patch

# Provide a minimal settings stub
mock_settings = MagicMock()
mock_settings.jpeg_quality = 75
sys.modules.setdefault("config", MagicMock(settings=mock_settings))

from encoder import encode_jpeg  # noqa: E402


class TestEncodeJpeg:
    def test_returns_bytes(self) -> None:
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        result = encode_jpeg(img)
        assert isinstance(result, bytes)

    def test_jpeg_magic_bytes(self) -> None:
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        result = encode_jpeg(img)
        # JPEG starts with FF D8
        assert result[:2] == b"\xff\xd8"

    def test_nonzero_image(self) -> None:
        img = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        result = encode_jpeg(img)
        assert len(result) > 0

"""Centralized configuration for the vision service."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class VisionConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VISION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Upstream capture service ──────────────────────────────────────────────
    capture_ws_url: str = Field(default="ws://localhost:8000/stream")

    # ── Output websocket server ───────────────────────────────────────────────
    ws_host: str = Field(default="0.0.0.0")
    ws_port: int = Field(default=8100, ge=1024, le=65535)

    # ── Capture / resolution ──────────────────────────────────────────────────
    capture_width: int = Field(default=1920)
    capture_height: int = Field(default=1080)

    # ── Analysis rate ─────────────────────────────────────────────────────────
    # Process at most this many frames per second (drop the rest)
    analysis_fps: float = Field(default=5.0, ge=0.5, le=30.0)
    max_queue_size: int = Field(default=4, ge=1)

    # ── OCR ───────────────────────────────────────────────────────────────────
    ocr_gpu: bool = Field(default=False)          # set True if CUDA available
    ocr_languages: list[str] = Field(default=["en"])
    ocr_confidence_min: float = Field(default=0.3, ge=0.0, le=1.0)
    ocr_batch_size: int = Field(default=1)

    # ── Template matching ─────────────────────────────────────────────────────
    template_confidence_min: float = Field(default=0.75, ge=0.0, le=1.0)
    template_multi_scale: bool = Field(default=True)
    template_scale_steps: int = Field(default=5, ge=1)
    template_scale_min: float = Field(default=0.8, ge=0.1)
    template_scale_max: float = Field(default=1.2, le=3.0)

    # ── Event engine ─────────────────────────────────────────────────────────
    event_dedup_window_s: float = Field(default=2.0, ge=0.1)
    low_economy_threshold: int = Field(default=2000, ge=0)
    force_buy_threshold: int = Field(default=3000, ge=0)

    # ── ROI config file ───────────────────────────────────────────────────────
    roi_config_path: str = Field(default="rois.yaml")

    # ── Debug / benchmark ─────────────────────────────────────────────────────
    debug_mode: bool = Field(default=False)
    debug_show_window: bool = Field(default=False)
    debug_save_frames: bool = Field(default=False)
    debug_frame_dir: str = Field(default="debug_vision_frames")
    benchmark_mode: bool = Field(default=False)
    benchmark_log_interval: float = Field(default=5.0, ge=1.0)

    # ── Frame skipping ────────────────────────────────────────────────────────
    skip_ocr_on_template_miss: bool = Field(default=False)


settings = VisionConfig()

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class CaptureConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAPTURE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Capture
    target_fps: int = Field(default=10, ge=1, le=60)
    capture_width: int = Field(default=1920, ge=640)
    capture_height: int = Field(default=1080, ge=360)
    game_window_title: str = Field(default="VALORANT")

    # JPEG streaming
    jpeg_quality: int = Field(default=75, ge=10, le=100)

    # WebSocket
    ws_host: str = Field(default="0.0.0.0")
    ws_port: int = Field(default=8000, ge=1024, le=65535)

    # Frame queue
    max_queue_size: int = Field(default=5, ge=1, le=30)

    # Debug / benchmark
    debug_mode: bool = Field(default=False)
    frame_save_interval: float = Field(default=5.0, ge=0.5)
    frame_save_dir: str = Field(default="debug_frames")
    benchmark_mode: bool = Field(default=False)
    benchmark_log_interval: float = Field(default=5.0, ge=1.0)


# Singleton — import this everywhere
settings = CaptureConfig()

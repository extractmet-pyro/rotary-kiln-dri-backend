"""Runtime settings from environment variables (no secrets in code)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _b(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    app_env: str = os.environ.get("APP_ENV", "demo")
    database_url: str = os.environ.get("DATABASE_URL", f"sqlite:///{ROOT / 'data' / 'twin.db'}")
    allowed_origins: list = field(default_factory=lambda: [o.strip() for o in os.environ.get(
        "ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173").split(",") if o.strip()])
    secret_key: str = os.environ.get("SECRET_KEY", "")
    demo_public: bool = _b("DEMO_PUBLIC", True)
    demo_password: str = os.environ.get("DEMO_USER_PASSWORD", "")
    max_job_workers: int = int(os.environ.get("MAX_JOB_WORKERS", "1"))
    job_wall_cap_s: float = float(os.environ.get("JOB_WALL_CAP_S", "900"))
    rate_limit_per_min: int = int(os.environ.get("RATE_LIMIT_PER_MIN", "240"))
    max_request_bytes: int = int(os.environ.get("MAX_REQUEST_BYTES", str(3 * 1024 * 1024)))
    result_retention: int = int(os.environ.get("RESULT_RETENTION_RUNS", "300"))
    default_mode: str = os.environ.get("DEFAULT_MODE", "DEMO_SYNTHETIC")
    log_level: str = os.environ.get("LOG_LEVEL", "INFO")
    fixtures_dir: Path = ROOT / "fixtures"
    docs_dir: Path = ROOT / "docs"

    def __post_init__(self):
        if not self.secret_key:
            if self.app_env == "production":
                raise RuntimeError("SECRET_KEY must be set in production")
            self.secret_key = "dev-only-insecure-key-change-me"
        if self.database_url.startswith("postgres://"):
            self.database_url = self.database_url.replace("postgres://", "postgresql+psycopg://", 1)
        if self.database_url.startswith("sqlite:///"):
            Path(self.database_url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)

    def secrets_status(self) -> dict:
        """Presence only - never values."""
        return {"SECRET_KEY": bool(os.environ.get("SECRET_KEY")), "DATABASE_URL": bool(os.environ.get("DATABASE_URL")),
                "DEMO_USER_PASSWORD": bool(os.environ.get("DEMO_USER_PASSWORD"))}


settings = Settings()

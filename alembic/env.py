"""Alembic environment: uses DATABASE_URL from app settings."""
import sys
from pathlib import Path

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.settings import settings  # noqa: E402
from app.data import models  # noqa: E402,F401
from app.data.database import Base, make_engine  # noqa: E402

target_metadata = Base.metadata


def run():
    eng = make_engine(settings.database_url)
    with eng.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run()

"""
Database connection and session management using SQLAlchemy.

This module defines a SQLAlchemy Engine and SessionLocal for database
connections. By default it uses SQLite for ease of development, but the
connection URL can be overridden via the `DATABASE_URL` environment
variable. When deploying with Docker Compose the environment can be
configured to point at a Postgres instance instead.

The Base class defined here should be used by all ORM models in
``models.py`` to ensure they share the same metadata.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker


# Read database URL from environment or fallback to SQLite file in the
# project directory. When using Docker Compose this should be set to
# something like `postgresql+psycopg2://user:password@postgres/dbname`.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", f"sqlite:///./suno.db"
)

# ``connect_args`` only apply to SQLite. They ensure that the
# ``check_same_thread`` flag is disabled so the same connection can
# be shared across threads within a single process.
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(DATABASE_URL)

# Create a sessionmaker bound to the engine. Sessions should be
# instantiated per-request in FastAPI and closed afterwards.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for ORM models.
Base = declarative_base()


def init_db() -> None:
    """Create database tables.

    This function should be invoked on application startup to ensure
    that all ORM models are created in the database. It is safe to call
    this repeatedly as SQLAlchemy only issues CREATE TABLE statements
    when a table does not already exist.
    """
    import logging

    from . import models  # noqa: F401  Ensure models are registered

    logging.info("Creating database tables if they do not exist…")
    Base.metadata.create_all(bind=engine)
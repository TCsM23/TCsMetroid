"""Metroidvania Route Planner & Randomizer (Flask application factory)."""
from __future__ import annotations

import os

import click
import sqlalchemy as sa
from flask import Flask

from .extensions import db


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL", "sqlite:///" + os.path.join(app.instance_path, "planner.db")),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        LOAD_DEMO_MAP=True,
    )
    if test_config:
        app.config.update(test_config)
    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    from . import models  # noqa: F401  (register tables)
    from .api import api
    from .routes import bp
    app.register_blueprint(bp)
    app.register_blueprint(api)

    with app.app_context():
        db.create_all()
        _upgrade_schema()
        if app.config["LOAD_DEMO_MAP"] and models.Map.query.first() is None:
            _load_demo()

    @app.cli.command("reset-db")
    def reset_db():
        """Drop every table and reload the demo map."""
        db.drop_all()
        db.create_all()
        _load_demo()
        click.echo("Database reset with the demo map.")

    return app


# Columns added after the first version: (table, column, SQL type and default).
NEW_COLUMNS = [
    ("maps", "is_template", "BOOLEAN NOT NULL DEFAULT 0"),           # step 12
    ("maps", "powerups_json", "TEXT NOT NULL DEFAULT ''"),           # step 15
]


def _upgrade_schema() -> None:
    """Add columns that newer steps expect to a database made by an older step.

    db.create_all() only creates missing *tables*; it never adds a column to a
    table that already exists. So a planner.db made before a step that added a
    column crashes on the first query. This is a tiny, hand-written migration:
    look at the real columns, add whatever is missing.
    """
    inspector = sa.inspect(db.engine)
    for table, column, ddl in NEW_COLUMNS:
        existing = {c["name"] for c in inspector.get_columns(table)}
        if column not in existing:
            with db.engine.begin() as conn:
                conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def _load_demo() -> None:
    from .demo_map import DEMO_MAP
    from .models import Map
    Map.from_dict(DEMO_MAP)
    db.session.commit()

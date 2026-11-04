"""initial schema v1: runs, recommendations, decisions, audit, plant_configs, materials, alerts

Revision ID: 0001_initial
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None


def upgrade():
    ts = lambda n: sa.Column(n, sa.DateTime(timezone=True))  # noqa: E731
    op.create_table("runs", sa.Column("id", sa.String(40), primary_key=True), sa.Column("kind", sa.String(40), index=True),
                    sa.Column("status", sa.String(20), index=True), sa.Column("progress", sa.Float), sa.Column("message", sa.Text),
                    ts("created_utc"), ts("started_utc"), ts("finished_utc"), sa.Column("scenario_name", sa.String(120)),
                    sa.Column("mode", sa.String(30)), sa.Column("plant_config_version", sa.String(60)), sa.Column("model_version", sa.String(60)),
                    sa.Column("input_hash", sa.String(64), index=True), sa.Column("campaign_id", sa.String(60)),
                    sa.Column("feed_batch_id", sa.String(60)), sa.Column("operator", sa.String(60)), sa.Column("request", sa.JSON),
                    sa.Column("summary", sa.JSON), sa.Column("result_gz", sa.LargeBinary))
    op.create_table("recommendations", sa.Column("id", sa.String(40), primary_key=True), ts("created_utc"),
                    sa.Column("scenario", sa.String(60)), sa.Column("status", sa.String(40)), sa.Column("mode", sa.String(30)),
                    sa.Column("requested_by", sa.String(60)), sa.Column("payload", sa.JSON), sa.Column("gates", sa.JSON),
                    sa.Column("verification_run_id", sa.String(40)), sa.Column("decision", sa.String(20)))
    op.create_table("decisions", sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
                    sa.Column("recommendation_id", sa.String(40), index=True), ts("created_utc"), sa.Column("user", sa.String(60)),
                    sa.Column("role", sa.String(30)), sa.Column("decision", sa.String(20)), sa.Column("note", sa.Text),
                    sa.Column("override_minutes", sa.Float))
    op.create_table("audit", sa.Column("id", sa.Integer, primary_key=True, autoincrement=True), ts("ts_utc"),
                    sa.Column("user", sa.String(60)), sa.Column("role", sa.String(30)), sa.Column("action", sa.String(80)),
                    sa.Column("detail", sa.JSON))
    op.create_table("plant_configs", sa.Column("version", sa.String(60), primary_key=True), ts("created_utc"),
                    sa.Column("author", sa.String(60)), sa.Column("active", sa.Boolean), sa.Column("config", sa.JSON), sa.Column("note", sa.Text))
    op.create_table("materials", sa.Column("id", sa.Integer, primary_key=True, autoincrement=True), sa.Column("kind", sa.String(20)),
                    sa.Column("lot_id", sa.String(60)), ts("created_utc"), sa.Column("assay", sa.JSON), sa.Column("basis", sa.String(40)),
                    sa.Column("provenance", sa.String(40)))
    op.create_table("alerts", sa.Column("id", sa.Integer, primary_key=True, autoincrement=True), ts("ts_utc"),
                    sa.Column("category", sa.String(40)), sa.Column("severity", sa.String(20)), sa.Column("message", sa.Text),
                    sa.Column("source", sa.String(60)), sa.Column("acknowledged_by", sa.String(60)))


def downgrade():
    for t in ("alerts", "materials", "plant_configs", "audit", "decisions", "recommendations", "runs"):
        op.drop_table(t)

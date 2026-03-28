"""Initial v7 schema (database-spec). Single migration for fresh DB.

Creates: set_updated_at trigger, all tables per database-spec (PK DEFAULT gen_random_uuid()),
partial unique indexes, CHECK constraints, GIN indexes, partitioned crawl_runs/crawl_logs,
crawl_run_tasks lookup, materialized view, pg_trgm and title trigram index.

Revision ID: v7_001
Revises:
Create Date: 2026-02-23

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v7_001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_set_updated_at_trigger(conn):
    conn.execute(sa.text("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """))


def _attach_updated_at_trigger(conn, table: str):
    conn.execute(sa.text(f"""
        CREATE TRIGGER set_updated_at
        BEFORE UPDATE ON {table}
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """))


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Extensions (gen_random_uuid is built-in; pg_trgm for trigram search)
    op.execute(sa.text('CREATE EXTENSION IF NOT EXISTS "pg_trgm";'))

    # 2. Trigger function for updated_at
    _create_set_updated_at_trigger(conn)

    # 3. colleges
    op.create_table(
        "colleges",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("is_crawl_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_colleges_external_id", "colleges", ["external_id"], unique=True, postgresql_where=sa.text("deleted_at IS NULL"))
    _attach_updated_at_trigger(conn, "colleges")

    # 4. notices
    op.create_table(
        "notices",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("college_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(512), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("url", sa.String(2048), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("sub_category", sa.String(64), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("eligibility", postgresql.JSONB(), nullable=True),
        sa.Column("hashtags", postgresql.JSONB(), nullable=True),
        sa.Column("ai_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("ai_extracted_json", postgresql.JSONB(), nullable=True),
        sa.Column("is_manual_edited", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["college_id"], ["colleges.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("ai_status IN ('pending', 'processing', 'done')", name="notices_ai_status_check"),
        sa.CheckConstraint("eligibility IS NULL OR (jsonb_typeof(eligibility) = 'array' AND jsonb_array_length(eligibility) <= 50)", name="chk_eligibility_array"),
        sa.CheckConstraint("ai_extracted_json IS NULL OR jsonb_typeof(ai_extracted_json) = 'object'", name="chk_ai_extracted_object"),
    )
    op.create_index("ix_notices_college_id", "notices", ["college_id"], unique=False)
    op.create_index("ix_notices_published_at", "notices", ["published_at"], unique=False)
    op.create_index("ix_notices_ai_status", "notices", ["ai_status"], unique=False)
    op.create_index("ix_notices_content_hash", "notices", ["content_hash"], unique=False)
    op.create_index("ix_notices_category", "notices", ["category"], unique=False)
    op.create_index("uq_notices_college_external", "notices", ["college_id", "external_id"], unique=True, postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index(
        "ix_notices_eligibility_gin",
        "notices",
        ["eligibility"],
        unique=False,
        postgresql_using="gin",
        postgresql_with={"fastupdate": "on", "gin_pending_list_limit": 4194304},
    )
    op.create_index(
        "ix_notices_hashtags_gin",
        "notices",
        ["hashtags"],
        unique=False,
        postgresql_using="gin",
        postgresql_with={"fastupdate": "on", "gin_pending_list_limit": 4194304},
    )
    _attach_updated_at_trigger(conn, "notices")

    # 5. notice_contents
    op.create_table(
        "notice_contents",
        sa.Column("notice_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_url", sa.String(2048), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["notice_id"], ["notices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("notice_id"),
    )
    _attach_updated_at_trigger(conn, "notice_contents")

    # 6. notice_schedules
    op.create_table(
        "notice_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("notice_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schedule_type", sa.String(32), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_all_day", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_tbd", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_always_open", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("schedule_text_fallback", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["notice_id"], ["notices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("(is_tbd = true OR is_always_open = true) OR start_at IS NOT NULL", name="chk_schedule_time"),
        sa.CheckConstraint("NOT (is_tbd = true AND is_always_open = true)", name="chk_schedule_exclusive"),
        sa.CheckConstraint("is_tbd = false OR (start_at IS NULL AND end_at IS NULL)", name="chk_tbd_null"),
    )
    op.create_index("ix_notice_schedules_notice_id", "notice_schedules", ["notice_id"], unique=False)
    _attach_updated_at_trigger(conn, "notice_schedules")

    # 7. users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_user_id", sa.String(256), nullable=False),
        sa.Column("email", sa.String(256), nullable=True),
        sa.Column("name", sa.String(256), nullable=True),
        sa.Column("refresh_token_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_provider", "users", ["provider"], unique=False)
    op.create_index("ix_users_provider_user_id", "users", ["provider_user_id"], unique=False)
    op.create_index("uq_users_provider_uid", "users", ["provider", "provider_user_id"], unique=True, postgresql_where=sa.text("deleted_at IS NULL"))
    _attach_updated_at_trigger(conn, "users")

    # 8. user_profiles
    op.create_table(
        "user_profiles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("encrypted_data", postgresql.BYTEA(), nullable=False),
        sa.Column("matching_profile", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("kms_key_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.CheckConstraint("jsonb_typeof(matching_profile) = 'object' AND NOT (matching_profile ? 'phone' OR matching_profile ? 'ssn')", name="chk_matching_profile_schema"),
    )
    op.create_index("idx_user_profiles_matching", "user_profiles", ["matching_profile"], unique=False, postgresql_using="gin")
    _attach_updated_at_trigger(conn, "user_profiles")

    # 9. user_calendar_events
    op.create_table(
        "user_calendar_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notice_schedule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("custom_title", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["notice_schedule_id"], ["notice_schedules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_calendar_events_user_id", "user_calendar_events", ["user_id"], unique=False)
    op.create_index("ix_user_calendar_events_notice_schedule_id", "user_calendar_events", ["notice_schedule_id"], unique=False)
    op.create_index("uq_user_calendar_user_schedule", "user_calendar_events", ["user_id", "notice_schedule_id"], unique=True)

    # 10. keyword_subscriptions
    op.create_table(
        "keyword_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("keyword_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_keyword_subscriptions_user_id", "keyword_subscriptions", ["user_id"], unique=False)
    op.create_index("ix_keyword_subscriptions_keyword_hash", "keyword_subscriptions", ["keyword_hash"], unique=False)
    op.create_index("uq_keyword_subscriptions_user_hash", "keyword_subscriptions", ["user_id", "keyword_hash"], unique=True)

    # 11. crawl_run_tasks (global unique lookup)
    op.create_table(
        "crawl_run_tasks",
        sa.Column("celery_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("celery_task_id"),
    )
    op.create_index("ix_crawl_run_tasks_run_id", "crawl_run_tasks", ["run_id"], unique=False)

    # 12. crawl_runs (partitioned) - parent table
    op.create_table(
        "crawl_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("college_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fail_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["college_id"], ["colleges.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", "started_at"),
        sa.CheckConstraint("status IN ('running', 'success', 'failed')", name="crawl_runs_status_check"),
        postgresql_partition_by="RANGE (started_at)",
    )
    op.create_index("ix_crawl_runs_college_id", "crawl_runs", ["college_id"], unique=False)
    op.execute(sa.text("""
        CREATE TABLE crawl_runs_default PARTITION OF crawl_runs
        DEFAULT
    """))

    # 13. crawl_logs (partitioned)
    op.create_table(
        "crawl_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("message", sa.String(2000), nullable=True),
        sa.Column("stack_trace", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", "created_at"),
        sa.CheckConstraint("severity IN ('INFO', 'WARN', 'ERROR')", name="crawl_logs_severity_check"),
        postgresql_partition_by="RANGE (created_at)",
    )
    op.create_index("ix_crawl_logs_run_id", "crawl_logs", ["run_id"], unique=False)
    op.execute(sa.text("""
        CREATE TABLE crawl_logs_default PARTITION OF crawl_logs
        DEFAULT
    """))

    # 14. Materialized view
    op.execute(sa.text("""
        CREATE MATERIALIZED VIEW active_notice_schedules_mv AS
        SELECT
            ns.id AS schedule_id,
            ns.notice_id,
            n.college_id,
            ns.start_at,
            ns.end_at,
            ns.is_all_day,
            ns.is_tbd,
            ns.is_always_open,
            ns.schedule_text_fallback,
            n.title
        FROM notice_schedules ns
        INNER JOIN notices n ON ns.notice_id = n.id AND n.deleted_at IS NULL
        INNER JOIN colleges c ON n.college_id = c.id AND c.deleted_at IS NULL
    """))
    op.create_index("uq_active_schedules_mv_id", "active_notice_schedules_mv", ["schedule_id"], unique=True)
    op.create_index("ix_active_schedules_mv_start_at", "active_notice_schedules_mv", ["start_at"], unique=False)

    # 15. pg_trgm title index (search fallback)
    op.create_index("idx_notices_title_trgm", "notices", ["title"], unique=False, postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"})


def downgrade() -> None:
    conn = op.get_bind()

    op.drop_index("idx_notices_title_trgm", table_name="notices", postgresql_using="gin")
    op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS active_notice_schedules_mv"))
    op.execute(sa.text("DROP TABLE IF EXISTS crawl_logs_default"))
    op.drop_table("crawl_logs")
    op.execute(sa.text("DROP TABLE IF EXISTS crawl_runs_default"))
    op.drop_table("crawl_runs")
    op.drop_table("crawl_run_tasks")
    op.drop_table("keyword_subscriptions")
    op.drop_table("user_calendar_events")
    op.drop_table("user_profiles")
    op.drop_table("users")
    op.drop_table("notice_schedules")
    op.drop_table("notice_contents")
    op.drop_table("notices")
    op.drop_table("colleges")

    conn.execute(sa.text("DROP FUNCTION IF EXISTS set_updated_at() CASCADE"))
    op.execute(sa.text('DROP EXTENSION IF EXISTS "pg_trgm"'))

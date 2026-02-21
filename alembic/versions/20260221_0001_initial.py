"""Initial schema

Revision ID: 20260221_0001
Revises:
Create Date: 2026-02-21 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260221_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


bot_status_enum = sa.Enum("RUNNING", "STOPPED", name="bot_status_enum")
plan_type_enum = sa.Enum("FREE", "MONTHLY", "SEMIANNUAL", "YEARLY", name="plan_type_enum")
user_role_enum = sa.Enum("OWNER", "ADMIN", "MOD", "USER", name="user_role_enum")
subscription_plan_type_enum = sa.Enum(
    "FREE",
    "MONTHLY",
    "SEMIANNUAL",
    "YEARLY",
    name="subscription_plan_type_enum",
)
subscription_status_enum = sa.Enum(
    "ACTIVE",
    "EXPIRED",
    "PENDING",
    "CANCELED",
    name="subscription_status_enum",
)
payment_status_enum = sa.Enum("PENDING", "APPROVED", "REJECTED", name="payment_status_enum")
broadcast_segment_enum = sa.Enum(
    "ALL",
    "ACTIVE_24H",
    "ACTIVE_7D",
    "VIP_ONLY",
    name="broadcast_segment_enum",
)
broadcast_status_enum = sa.Enum(
    "PENDING",
    "SCHEDULED",
    "PROCESSING",
    "DONE",
    "FAILED",
    name="broadcast_status_enum",
)


def upgrade() -> None:
    op.create_table(
        "client_bots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("owner_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=True),
        sa.Column("token_encrypted", sa.Text(), nullable=False),
        sa.Column("webhook_secret", sa.String(length=128), nullable=False),
        sa.Column("status", bot_status_enum, nullable=False, server_default="STOPPED"),
        sa.Column("plan_type", plan_type_enum, nullable=False, server_default="FREE"),
        sa.Column("branding_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("subscription_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_banned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ad_frequency", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("settings", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("template_name", sa.String(length=64), nullable=True),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("webhook_secret", name="uq_client_bots_webhook_secret"),
    )
    op.create_index("ix_client_bots_owner_telegram_id", "client_bots", ["owner_telegram_id"])
    op.create_index("ix_client_bots_webhook_secret", "client_bots", ["webhook_secret"])

    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "bot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("client_bots.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("plan_type", subscription_plan_type_enum, nullable=False, server_default="FREE"),
        sa.Column("status", subscription_status_enum, nullable=False, server_default="ACTIVE"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "client_bot_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("bot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("client_bots.id"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", user_role_enum, nullable=False, server_default="USER"),
        sa.Column("is_vip", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_banned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("has_started", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("warnings_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("interactions_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("bot_id", "telegram_user_id", name="uq_client_bot_members_bot_id"),
    )
    op.create_index("ix_client_bot_members_telegram_user_id", "client_bot_members", ["telegram_user_id"])

    op.create_table(
        "forced_channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("bot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("client_bots.id"), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_username", sa.String(length=128), nullable=True),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("bot_id", "channel_id", name="uq_forced_channels_bot_id"),
    )

    op.create_table(
        "payment_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("bot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("client_bots.id"), nullable=False),
        sa.Column("submitted_by", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("receipt_url", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", payment_status_enum, nullable=False, server_default="PENDING"),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "coupons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("discount_percent", sa.Integer(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code", name="uq_coupons_code"),
    )
    op.create_index("ix_coupons_code", "coupons", ["code"])

    op.create_table(
        "broadcast_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("bot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("client_bots.id"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("segment", broadcast_segment_enum, nullable=False, server_default="ALL"),
        sa.Column("status", broadcast_status_enum, nullable=False, server_default="PENDING"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_target", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "broadcast_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("broadcast_jobs.id"), nullable=False),
        sa.Column("bot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("client_bots.id"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("job_id", "telegram_user_id", name="uq_broadcast_deliveries_job_id"),
    )
    op.create_index("ix_broadcast_deliveries_telegram_user_id", "broadcast_deliveries", ["telegram_user_id"])

    op.create_table(
        "bot_ads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("bot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("client_bots.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("every_n_interactions", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "platform_bans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("bot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("client_bots.id"), nullable=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_platform_bans_telegram_user_id", "platform_bans", ["telegram_user_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("actor_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "subscription_reminder_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id"),
            nullable=False,
        ),
        sa.Column("reminder_key", sa.String(length=16), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("subscription_id", "reminder_key", name="uq_subscription_reminder_logs_subscription_id"),
    )


def downgrade() -> None:
    op.drop_table("subscription_reminder_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_platform_bans_telegram_user_id", table_name="platform_bans")
    op.drop_table("platform_bans")
    op.drop_table("bot_ads")
    op.drop_index("ix_broadcast_deliveries_telegram_user_id", table_name="broadcast_deliveries")
    op.drop_table("broadcast_deliveries")
    op.drop_table("broadcast_jobs")
    op.drop_index("ix_coupons_code", table_name="coupons")
    op.drop_table("coupons")
    op.drop_table("payment_requests")
    op.drop_table("forced_channels")
    op.drop_index("ix_client_bot_members_telegram_user_id", table_name="client_bot_members")
    op.drop_table("client_bot_members")
    op.drop_table("subscriptions")
    op.drop_index("ix_client_bots_webhook_secret", table_name="client_bots")
    op.drop_index("ix_client_bots_owner_telegram_id", table_name="client_bots")
    op.drop_table("client_bots")

    broadcast_status_enum.drop(op.get_bind(), checkfirst=True)
    broadcast_segment_enum.drop(op.get_bind(), checkfirst=True)
    payment_status_enum.drop(op.get_bind(), checkfirst=True)
    subscription_status_enum.drop(op.get_bind(), checkfirst=True)
    subscription_plan_type_enum.drop(op.get_bind(), checkfirst=True)
    user_role_enum.drop(op.get_bind(), checkfirst=True)
    plan_type_enum.drop(op.get_bind(), checkfirst=True)
    bot_status_enum.drop(op.get_bind(), checkfirst=True)

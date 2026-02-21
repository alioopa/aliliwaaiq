from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    BotStatus,
    BroadcastSegment,
    BroadcastStatus,
    PaymentStatus,
    PlanType,
    SubscriptionStatus,
    UserRole,
)
from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ClientBot(Base, TimestampMixin):
    __tablename__ = "client_bots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    webhook_secret: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)

    status: Mapped[BotStatus] = mapped_column(
        Enum(BotStatus, name="bot_status_enum"), default=BotStatus.STOPPED, nullable=False
    )
    plan_type: Mapped[PlanType] = mapped_column(
        Enum(PlanType, name="plan_type_enum"), default=PlanType.FREE, nullable=False
    )
    branding_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    subscription_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ad_frequency: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    settings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    template_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    members: Mapped[list["ClientBotMember"]] = relationship(
        "ClientBotMember", back_populates="bot", cascade="all, delete-orphan"
    )
    forced_channels: Mapped[list["ForcedChannel"]] = relationship(
        "ForcedChannel", back_populates="bot", cascade="all, delete-orphan"
    )
    broadcasts: Mapped[list["BroadcastJob"]] = relationship(
        "BroadcastJob", back_populates="bot", cascade="all, delete-orphan"
    )
    ads: Mapped[list["BotAd"]] = relationship(
        "BotAd", back_populates="bot", cascade="all, delete-orphan"
    )
    subscription: Mapped["Subscription | None"] = relationship(
        "Subscription", back_populates="bot", uselist=False, cascade="all, delete-orphan"
    )


class ClientBotMember(Base, TimestampMixin):
    __tablename__ = "client_bot_members"
    __table_args__ = (UniqueConstraint("bot_id", "telegram_user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("client_bots.id"), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role_enum"), default=UserRole.USER, nullable=False
    )
    is_vip: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_started: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    warnings_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    interactions_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    bot: Mapped[ClientBot] = relationship("ClientBot", back_populates="members")


class ForcedChannel(Base, TimestampMixin):
    __tablename__ = "forced_channels"
    __table_args__ = (UniqueConstraint("bot_id", "channel_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("client_bots.id"), nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    bot: Mapped[ClientBot] = relationship("ClientBot", back_populates="forced_channels")


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_bots.id"), nullable=False, unique=True
    )
    plan_type: Mapped[PlanType] = mapped_column(
        Enum(PlanType, name="subscription_plan_type_enum"), default=PlanType.FREE, nullable=False
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status_enum"),
        default=SubscriptionStatus.ACTIVE,
        nullable=False,
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    bot: Mapped[ClientBot] = relationship("ClientBot", back_populates="subscription")
    reminder_logs: Mapped[list["SubscriptionReminderLog"]] = relationship(
        "SubscriptionReminderLog", back_populates="subscription", cascade="all, delete-orphan"
    )


class SubscriptionReminderLog(Base):
    __tablename__ = "subscription_reminder_logs"
    __table_args__ = (UniqueConstraint("subscription_id", "reminder_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=False
    )
    reminder_key: Mapped[str] = mapped_column(String(16), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    subscription: Mapped[Subscription] = relationship("Subscription", back_populates="reminder_logs")


class PaymentRequest(Base, TimestampMixin):
    __tablename__ = "payment_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("client_bots.id"), nullable=False)
    submitted_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    receipt_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status_enum"), default=PaymentStatus.PENDING, nullable=False
    )
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Coupon(Base, TimestampMixin):
    __tablename__ = "coupons"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    discount_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)


class BroadcastJob(Base, TimestampMixin):
    __tablename__ = "broadcast_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("client_bots.id"), nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    segment: Mapped[BroadcastSegment] = mapped_column(
        Enum(BroadcastSegment, name="broadcast_segment_enum"), default=BroadcastSegment.ALL, nullable=False
    )
    status: Mapped[BroadcastStatus] = mapped_column(
        Enum(BroadcastStatus, name="broadcast_status_enum"), default=BroadcastStatus.PENDING, nullable=False
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_target: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    bot: Mapped[ClientBot] = relationship("ClientBot", back_populates="broadcasts")
    deliveries: Mapped[list["BroadcastDelivery"]] = relationship(
        "BroadcastDelivery", back_populates="job", cascade="all, delete-orphan"
    )


class BroadcastDelivery(Base, TimestampMixin):
    __tablename__ = "broadcast_deliveries"
    __table_args__ = (UniqueConstraint("job_id", "telegram_user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("broadcast_jobs.id"), nullable=False)
    bot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("client_bots.id"), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped[BroadcastJob] = relationship("BroadcastJob", back_populates="deliveries")


class BotAd(Base, TimestampMixin):
    __tablename__ = "bot_ads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("client_bots.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    every_n_interactions: Mapped[int] = mapped_column(Integer, default=5, nullable=False)

    bot: Mapped[ClientBot] = relationship("ClientBot", back_populates="ads")


class PlatformBan(Base, TimestampMixin):
    __tablename__ = "platform_bans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_bots.id"), nullable=True
    )
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

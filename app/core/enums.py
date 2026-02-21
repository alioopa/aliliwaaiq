from __future__ import annotations

from enum import Enum


class PlanType(str, Enum):
    FREE = "FREE"
    MONTHLY = "MONTHLY"
    SEMIANNUAL = "SEMIANNUAL"
    YEARLY = "YEARLY"


class BotStatus(str, Enum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"


class UserRole(str, Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MOD = "MOD"
    USER = "USER"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    PENDING = "PENDING"
    CANCELED = "CANCELED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class BroadcastStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"


class BroadcastSegment(str, Enum):
    ALL = "ALL"
    ACTIVE_24H = "ACTIVE_24H"
    ACTIVE_7D = "ACTIVE_7D"
    VIP_ONLY = "VIP_ONLY"


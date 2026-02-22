from __future__ import annotations

import argparse
import secrets
from cryptography.fernet import Fernet


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate Railway-ready env blocks for web/worker/beat services."
    )
    parser.add_argument("--domain", required=True, help="Railway public domain, e.g. web-xxxx.up.railway.app")
    parser.add_argument("--master-token", default="REPLACE_WITH_NEW_BOTFATHER_TOKEN")
    parser.add_argument("--admin-ids", default="123456789", help="Comma-separated numeric Telegram admin IDs")
    parser.add_argument("--platform-handle", default="@PlatformBot")
    parser.add_argument("--postgres-ref", default="PostgreSQL.DATABASE_URL")
    parser.add_argument("--redis-ref", default="Redis.REDIS_URL")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    domain = args.domain.replace("https://", "").strip().rstrip("/")

    fernet_key = Fernet.generate_key().decode("utf-8")
    webhook_secret = secrets.token_urlsafe(32)
    ops_key = secrets.token_urlsafe(32)

    web_env = f"""# web service
APP_NAME=Telegram Bot Maker
ENVIRONMENT=production
LOG_LEVEL=INFO
DEFAULT_TIMEZONE=UTC

DATABASE_URL=${{{{{args.postgres_ref}}}}}
REDIS_URL=${{{{{args.redis_ref}}}}}
CELERY_BROKER_URL=${{{{{args.redis_ref}}}}}
CELERY_RESULT_BACKEND=${{{{{args.redis_ref}}}}}

MASTER_BOT_TOKEN={args.master_token}
MASTER_ADMIN_IDS={args.admin_ids}
BOT_TOKEN_ENCRYPTION_KEY={fernet_key}
MASTER_BOT_WEBHOOK_SECRET={webhook_secret}
OPS_API_KEY={ops_key}
PLATFORM_BRAND_HANDLE={args.platform_handle}
WEBHOOK_BASE_URL=https://{domain}

BROADCAST_FLOOD_SLEEP=0.06
BROADCAST_MAX_RETRIES=5
BROADCAST_BATCH_SIZE=500
"""

    worker_env = """# worker and beat service
DATABASE_URL=${{web.DATABASE_URL}}
REDIS_URL=${{web.REDIS_URL}}
CELERY_BROKER_URL=${{web.CELERY_BROKER_URL}}
CELERY_RESULT_BACKEND=${{web.CELERY_RESULT_BACKEND}}
WEBHOOK_BASE_URL=${{web.WEBHOOK_BASE_URL}}

MASTER_BOT_TOKEN=${{web.MASTER_BOT_TOKEN}}
MASTER_ADMIN_IDS=${{web.MASTER_ADMIN_IDS}}
BOT_TOKEN_ENCRYPTION_KEY=${{web.BOT_TOKEN_ENCRYPTION_KEY}}
MASTER_BOT_WEBHOOK_SECRET=${{web.MASTER_BOT_WEBHOOK_SECRET}}
OPS_API_KEY=${{web.OPS_API_KEY}}
PLATFORM_BRAND_HANDLE=${{web.PLATFORM_BRAND_HANDLE}}

APP_NAME=${{web.APP_NAME}}
ENVIRONMENT=${{web.ENVIRONMENT}}
LOG_LEVEL=${{web.LOG_LEVEL}}
DEFAULT_TIMEZONE=${{web.DEFAULT_TIMEZONE}}

BROADCAST_FLOOD_SLEEP=${{web.BROADCAST_FLOOD_SLEEP}}
BROADCAST_MAX_RETRIES=${{web.BROADCAST_MAX_RETRIES}}
BROADCAST_BATCH_SIZE=${{web.BROADCAST_BATCH_SIZE}}
"""

    print("=== COPY TO web (RAW Variables) ===")
    print(web_env)
    print("=== COPY TO worker AND beat (RAW Variables) ===")
    print(worker_env)


if __name__ == "__main__":
    main()


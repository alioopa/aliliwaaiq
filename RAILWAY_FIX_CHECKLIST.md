# Railway Fix Checklist (Web 502 / Bot Not Replying)

Use this checklist exactly in order.

## 1) Generate Valid Secrets + Env Blocks

Run:

```bash
python scripts/railway_bootstrap.py --domain web-production-7468f.up.railway.app --master-token "REPLACE_WITH_NEW_TOKEN" --admin-ids "123456789"
```

Copy output:
- first block -> `web` service RAW variables
- second block -> both `worker` and `beat` RAW variables

## 2) Service Start Commands

- `web`: `python -m app.run`
- `worker`: `celery -A app.tasks.celery_app.celery_app worker -l info --concurrency=2`
- `beat`: `celery -A app.tasks.celery_app.celery_app beat -l info`

## 3) Phased Rollout

1. Stop/scale down `worker` and `beat`.
2. Redeploy `web` only.
3. Run migration once:

```bash
alembic upgrade head
```

4. Check:
- `GET /health` should return `{"status":"ok"}`
- `GET /ops/preflight` with `x-ops-key`
- `GET /ops/status` with `x-ops-key`

## 4) Sync Webhooks

```bash
curl -X POST "https://web-production-7468f.up.railway.app/ops/sync-master-webhook" -H "x-ops-key: YOUR_OPS_KEY"
curl -X POST "https://web-production-7468f.up.railway.app/ops/sync-client-webhooks" -H "x-ops-key: YOUR_OPS_KEY"
```

## 5) Verify Telegram

```bash
https://api.telegram.org/bot<MASTER_BOT_TOKEN>/getMe
https://api.telegram.org/bot<MASTER_BOT_TOKEN>/getWebhookInfo
```

Expected:
- `getMe.ok == true`
- `getWebhookInfo.result.url` is not empty
- `last_error_message` is empty

## 6) Bring Back Worker + Beat

After web + webhook are healthy, redeploy/scale `worker` then `beat`.

## Optional: Automated Preflight

```bash
python scripts/railway_preflight.py \
  --domain web-production-7468f.up.railway.app \
  --ops-key YOUR_OPS_KEY \
  --master-token YOUR_MASTER_TOKEN \
  --sync-webhooks
```

Exit code `0` means all checks passed.


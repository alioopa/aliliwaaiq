from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run end-to-end Railway + Telegram preflight checks.")
    parser.add_argument("--domain", required=True, help="Railway web domain, e.g. web-xxxx.up.railway.app")
    parser.add_argument("--ops-key", help="OPS_API_KEY for /ops endpoints")
    parser.add_argument("--master-token", help="Telegram master bot token")
    parser.add_argument("--sync-webhooks", action="store_true", help="Call sync webhook endpoints")
    parser.add_argument("--timeout", type=int, default=25)
    return parser.parse_args()


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    timeout: int = 25,
) -> tuple[bool, int | None, dict | str]:
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as response:
            payload = response.read().decode("utf-8", "ignore")
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                parsed = payload
            return True, response.status, parsed
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "ignore")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = body
        return False, exc.code, parsed
    except Exception as exc:
        return False, None, str(exc)


def print_check(name: str, ok: bool, details: str) -> None:
    marker = "PASS" if ok else "FAIL"
    print(f"[{marker}] {name}: {details}")


def main() -> int:
    args = parse_args()
    base = args.domain.strip()
    if not base.startswith("http://") and not base.startswith("https://"):
        base = "https://" + base
    base = base.rstrip("/")

    overall_ok = True

    # 1) Health
    ok, status, payload = request_json(f"{base}/health", timeout=args.timeout)
    health_ok = ok and status == 200 and isinstance(payload, dict) and payload.get("status") == "ok"
    print_check("web_health", health_ok, f"status={status}, payload={payload}")
    overall_ok = overall_ok and health_ok

    # 2) OPS endpoints
    if args.ops_key:
        headers = {"x-ops-key": args.ops_key}
        ok, status, payload = request_json(f"{base}/ops/preflight", headers=headers, timeout=args.timeout)
        preflight_ok = ok and status == 200 and isinstance(payload, dict) and payload.get("ok") is True
        print_check("ops_preflight", preflight_ok, f"status={status}, payload={payload}")
        overall_ok = overall_ok and preflight_ok

        ok, status, payload = request_json(f"{base}/ops/status", headers=headers, timeout=args.timeout)
        ops_status_ok = ok and status == 200 and isinstance(payload, dict)
        print_check("ops_status", ops_status_ok, f"status={status}, payload={payload}")
        overall_ok = overall_ok and ops_status_ok

        if args.sync_webhooks:
            ok, status, payload = request_json(
                f"{base}/ops/sync-master-webhook",
                method="POST",
                headers=headers,
                timeout=args.timeout,
            )
            sync_master_ok = ok and status == 200 and isinstance(payload, dict) and payload.get("ok") is True
            print_check("sync_master_webhook", sync_master_ok, f"status={status}, payload={payload}")
            overall_ok = overall_ok and sync_master_ok

            ok, status, payload = request_json(
                f"{base}/ops/sync-client-webhooks",
                method="POST",
                headers=headers,
                timeout=args.timeout,
            )
            sync_clients_ok = ok and status == 200 and isinstance(payload, dict) and payload.get("ok") is True
            print_check("sync_client_webhooks", sync_clients_ok, f"status={status}, payload={payload}")
            overall_ok = overall_ok and sync_clients_ok
    else:
        print("[SKIP] /ops checks skipped because --ops-key was not provided")

    # 3) Telegram checks
    if args.master_token:
        encoded = urllib.parse.quote(args.master_token, safe="")
        ok, status, payload = request_json(
            f"https://api.telegram.org/bot{encoded}/getMe",
            timeout=args.timeout,
        )
        tg_me_ok = ok and isinstance(payload, dict) and payload.get("ok") is True
        print_check("telegram_getMe", tg_me_ok, f"status={status}, payload={payload}")
        overall_ok = overall_ok and tg_me_ok

        ok, status, payload = request_json(
            f"https://api.telegram.org/bot{encoded}/getWebhookInfo",
            timeout=args.timeout,
        )
        tg_hook_ok = ok and isinstance(payload, dict) and payload.get("ok") is True
        print_check("telegram_getWebhookInfo", tg_hook_ok, f"status={status}, payload={payload}")
        overall_ok = overall_ok and tg_hook_ok
    else:
        print("[SKIP] Telegram checks skipped because --master-token was not provided")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())


from __future__ import annotations


BOT_TEMPLATES: dict[str, dict] = {
    "BASIC": {
        "anti_link": True,
        "anti_spam": True,
        "forbidden_words": [],
        "max_warns": 3,
        "captcha_enabled": False,
    },
    "COMMUNITY": {
        "anti_link": True,
        "anti_spam": True,
        "forbidden_words": ["spam", "scam"],
        "max_warns": 3,
        "captcha_enabled": True,
    },
    "STORE": {
        "anti_link": False,
        "anti_spam": True,
        "forbidden_words": [],
        "max_warns": 3,
        "captcha_enabled": False,
    },
}


from __future__ import annotations

import uvicorn

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.api.main:app",
        host="0.0.0.0",
        port=int(settings.port),
        reload=False,
    )


if __name__ == "__main__":
    main()


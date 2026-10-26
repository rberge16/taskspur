"""Startet Taktspur ausschließlich auf 127.0.0.1:8775 (Port 8765 gehört einer anderen App)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import uvicorn  # noqa: E402

from app import config  # noqa: E402


def main() -> int:
    port = config.PORT
    if port in config.FORBIDDEN_PORTS:
        print(f"Port {port} ist für Taktspur gesperrt.")
        return 2
    uvicorn.run("app.main:app", host=config.bind_host(), port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

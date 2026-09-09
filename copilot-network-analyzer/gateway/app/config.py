"""Runtime configuration, read from the environment.

Everything the gateway needs to reach ntopng and to authenticate its own
callers lives here so deployments differ only by .env, never by code.
"""

import os
from functools import lru_cache


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings:
    def __init__(self) -> None:
        # ntopng, e.g. http://10.9.1.241:3001 (this deployment) or
        # http://ntopng:3000 when the gateway runs on the compose network.
        self.ntopng_url: str = os.getenv("NTOPNG_URL", "http://10.9.1.241:3001").rstrip("/")
        # Only needed when ntopng runs without --disable-login 1.
        self.ntopng_user: str = os.getenv("NTOPNG_USER", "")
        self.ntopng_password: str = os.getenv("NTOPNG_PASSWORD", "")
        # ntopng interface id. 0 is the first (and, in this stack, only) one.
        self.ntopng_ifid: int = int(os.getenv("NTOPNG_IFID", "0"))
        self.ntopng_timeout: float = float(os.getenv("NTOPNG_TIMEOUT_SECONDS", "10"))

        # Keys accepted in the X-API-Key header. Empty disables auth, which is
        # only ever appropriate for a local smoke test.
        self.api_keys: list[str] = _split_csv(os.getenv("GATEWAY_API_KEYS", ""))

        # Caps that keep responses small enough for an agent to reason over.
        self.max_page_size: int = int(os.getenv("MAX_PAGE_SIZE", "500"))
        self.default_limit: int = int(os.getenv("DEFAULT_LIMIT", "10"))

    @property
    def ntopng_auth(self) -> tuple[str, str] | None:
        if self.ntopng_user:
            return (self.ntopng_user, self.ntopng_password)
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()

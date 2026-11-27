"""Settings: every api/ env var from docs/04-technical-design.md §13.

Secrets are `SecretStr | None` so the app imports and serves `/health` with no environment at all
(CI, tests). Non-secret keys carry local-dev defaults (api/.env.example).
"""

from functools import lru_cache

from fastapi import Request
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: SecretStr | None = None
    web_url: str = "http://localhost:3000"
    # Shared with the web's /api/revalidate route; unset = menu changes wait out the page cache.
    revalidate_secret: SecretStr | None = None

    # Shared with the web tier, which forwards the visitor's address with it (limits.client_ip).
    proxy_secret: SecretStr | None = None

    # Razorpay (test mode). Unset key = online payment is switched off; COD still works.
    razorpay_key_id: str | None = None
    razorpay_key_secret: SecretStr | None = None
    razorpay_webhook_secret: SecretStr | None = None

    # Open services with no account. "off" = never call out (tests, CI): straight-line legs, and
    # address search answers "drop the pin instead".
    osrm_url: str = "https://router.project-osrm.org"
    photon_url: str = "https://photon.komoot.io"
    user_agent: str = "platter.virajdomadia.com (portfolio demo)"

    # Seconds a stream stays open before `event: reconnect` (Vercel's function limit is 300).
    stream_lifetime_s: int = 280

    # The ambient world (services/demo.py): sim customers keep a couple of orders moving while
    # someone watches the board or the admin map. Off in tests.
    ambient_orders: bool = True

    @property
    def secure_cookies(self) -> bool:
        return self.web_url.startswith("https://")

    @property
    def razorpay_enabled(self) -> bool:
        return bool(self.razorpay_key_id and self.razorpay_key_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def current_settings(request: Request) -> Settings:
    """The app's own settings (tests build apps with their own)."""
    return request.app.state.settings

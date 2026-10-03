from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    discord_token: str
    battlemetrics_token: str | None
    state_path: str
    poll_interval: int
    log_level: str
    data_path: str
    steam_api_key: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.environ.get("DISCORD_TOKEN", "")
        if not token:
            raise RuntimeError("DISCORD_TOKEN is required")
        interval = max(10, int(os.environ.get("RUST_POLL_INTERVAL_SECONDS", "10")))
        return cls(token, os.environ.get("BATTLEMETRICS_TOKEN"), os.environ.get("RUST_TRACKER_STATE_PATH", "/data/rustbot.sqlite3"), interval, os.environ.get("RUST_LOG_LEVEL", "INFO"), os.environ.get("RUST_DATA_PATH", "data/rust_catalog.yml"), os.environ.get("STEAM_API_KEY") or None)

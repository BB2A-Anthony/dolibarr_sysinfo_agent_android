"""Shared helpers for the Kivy UI and the background service."""
import os


def app_data_dir():
    """Private app storage dir (same from UI and service process)."""
    candidates = [
        os.environ.get("ANDROID_PRIVATE_DATA"),
        os.path.expanduser("~"),
        ".",
    ]
    for path in candidates:
        if path and os.path.isdir(path):
            return path
    return "."


def config_path():
    return os.path.join(app_data_dir(), "config.json")


def ensure_config():
    """Create a default config.json on first launch."""
    import json

    path = config_path()
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "api_url": "",
                    "initial_delay_seconds": 15,
                    "poll_interval_seconds": 14400,
                    "timeout_seconds": 30,
                    "verify_ssl": True,
                },
                f,
                indent=4,
            )
    return path

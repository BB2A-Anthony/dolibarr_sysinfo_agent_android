"""Background service for the Android APK (run by buildozer/p4a).

Started on boot (via p4a service autostart) and kept alive by the app.
Loops: collect + send report every poll_interval_seconds.
"""
import logging
import time

from agent.sender import load_config, send_report
from mobile_common import ensure_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sysinfo.service")


def main():
    path = ensure_config()
    config = load_config(path)
    delay = config.get("initial_delay_seconds", 15)
    logger.info("Service demarre, premier envoi dans %ss", delay)
    time.sleep(delay)
    while True:
        interval = config.get("poll_interval_seconds", 14400)
        try:
            config = load_config(path)
            send_report(config)
            logger.info("Rapport envoye, prochain dans %ss", interval)
        except Exception as exc:
            logger.error("Envoi echoue: %s", exc)
        try:
            from agent.updater import apply_update, check_for_update

            info = check_for_update(config)
            if info:
                apply_update(config, info)
        except Exception as exc:
            logger.error("Auto-update echoue: %s", exc)
        time.sleep(interval)


if __name__ == "__main__":
    main()

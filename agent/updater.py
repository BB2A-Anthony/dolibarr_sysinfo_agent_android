"""Auto-update for the Android agent.

Queries the Dolibarr module 'sysinfo' config endpoint
(GET /api/index.php/sysinfo/config), which exposes the latest agent
version and its GitHub release update folder. If the remote version is
newer, downloads the APK package into the app data dir; the UI (main.py)
then prompts the user to install it (an APK cannot replace itself
silently without system privileges).
"""

import logging
import os

import requests

from agent import sender

logger = logging.getLogger("agent.updater")

AGENT_VERSION = "1.0.0"
OS_KEY = "android"
PACKAGE_FILENAME = "dolibarr_sysinfo_agent.apk"
CONFIG_ENDPOINT = "/sysinfo/config"


def _version_tuple(version):
    parts = []
    for chunk in str(version).split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def downloaded_package_path(config):
    """Return the path of the downloaded update APK, if any."""
    from mobile_common import app_data_dir

    return os.path.join(app_data_dir(), PACKAGE_FILENAME)


def check_for_update(config):
    """Return the remote update info if a newer version is available."""
    if not config.get("auto_update", True):
        return None
    try:
        resp = requests.get(
            sender.dolibarr_url(config, CONFIG_ENDPOINT),
            headers=sender.auth_headers(config),
            timeout=config.get("timeout_seconds", 30),
            verify=config.get("verify_ssl", True),
        )
        resp.raise_for_status()
        info = (resp.json() or {}).get(OS_KEY) or {}
    except Exception as exc:
        logger.warning("Verification de mise a jour echouee : %s", exc)
        return None
    remote_version = info.get("version")
    update_url = info.get("update_url")
    if not remote_version or not update_url:
        return None
    if _version_tuple(remote_version) <= _version_tuple(AGENT_VERSION):
        return None
    logger.info("Nouvelle version disponible : %s (actuelle %s)", remote_version, AGENT_VERSION)
    return info


def apply_update(config, info):
    """Download the new APK into the app data dir and return its path.

    The caller (UI) must ask the user to install it via the standard
    package installer (ACTION_VIEW intent with the APK content URI).
    """
    from mobile_common import app_data_dir

    package_url = info["update_url"].rstrip("/") + "/" + PACKAGE_FILENAME
    apk_path = os.path.join(app_data_dir(), PACKAGE_FILENAME)
    logger.info("Telechargement de %s", package_url)
    resp = requests.get(
        package_url,
        timeout=config.get("timeout_seconds", 30),
        verify=config.get("verify_ssl", True),
    )
    resp.raise_for_status()
    with open(apk_path, "wb") as f:
        f.write(resp.content)
    logger.info("APK %s telecharge, installation a confirmer par l'utilisateur", info.get("version"))
    return apk_path

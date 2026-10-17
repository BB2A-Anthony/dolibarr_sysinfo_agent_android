"""HTTP layer: config loading, auth headers, enrollment, reporting.

Kept protocol-compatible with the Windows agent so the same Dolibarr
module (sysinfo) accepts both agents.
"""

import json
import logging
import os
import subprocess
import uuid

import requests

from agent.collector import collect_system_info
from agent.crypto import decrypt, encrypt, migrate_config

logger = logging.getLogger("agent.sender")

DOLIBARR_STATUS_PATH = "/status"
DOLIBARR_API_ROOT = "/api/index.php"
ENDPOINT_PATH = "/sysinfo/machine"


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)
    if not config.get("guid"):
        config["guid"] = _machine_id()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)
        except OSError:
            pass
    migrate_config(config, path)
    return config


def get_api_key(config):
    """Return the plaintext API key (decrypted from AES storage)."""
    encrypted = config.get("api_key_encrypted")
    if encrypted:
        key = decrypt(encrypted)
        if key:
            return key
        logger.warning("Impossible de decrypter la cle API stockee")
    return config.get("api_key") or ""


def set_api_key(config, path, api_key):
    """Store the API key encrypted and remove any plaintext from config."""
    encrypted = encrypt(api_key)
    if encrypted:
        config["api_key_encrypted"] = encrypted
        config.pop("api_key", None)
    else:
        config["api_key"] = api_key
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)


def auth_headers(config):
    """Return Dolibarr-style auth headers (DOLIBARR_API_KEY)."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    api_key = get_api_key(config)
    if api_key:
        headers["DOLIBARR_API_KEY"] = api_key
    return headers


def dolibarr_url(config, path):
    """Build a full Dolibarr API URL from base URL and endpoint path."""
    api_url = config["api_url"].rstrip("/")
    if DOLIBARR_API_ROOT in api_url:
        return api_url + path
    return api_url + DOLIBARR_API_ROOT + path


def enroll_soc(config, code, config_path, confirm_reassign=False):
    """Enroll this device with a one-time code (5 min valid) generated on
    the thirdparty card. The server links the device to the thirdparty
    AND delivers the technical user's API key (stored encrypted).
    Returns (ok, message, need_confirm).
    """
    base = config["api_url"].rstrip("/")
    if "/api/index.php" in base:
        base = base.split("/api/index.php")[0]
    url = base + "/custom/sysinfo/enroll_soc.php"
    try:
        resp = requests.post(
            url,
            json={
                "code": code.strip(),
                "guid": config.get("guid"),
                "confirm_reassign": bool(confirm_reassign),
            },
            timeout=config.get("timeout_seconds", 30),
            verify=config.get("verify_ssl", True),
        )
        if resp.status_code == 409:
            try:
                data = resp.json()
            except ValueError:
                data = {}
            if data.get("confirm_reassign") and not confirm_reassign:
                return False, data.get("error", "Reaffectation requise."), True
            return False, data.get("error", resp.reason), False
        if resp.status_code != 200:
            try:
                message = resp.json().get("error", resp.reason)
            except ValueError:
                message = resp.reason
            return False, "Enrolement echoue : {}".format(message), False
        data = resp.json()
        fk_soc = data.get("thirdparty_id")
        api_key = data.get("api_key")
        if not fk_soc or not api_key:
            return False, "Reponse invalide du serveur.", False
        set_api_key(config, config_path, api_key)
        return True, (
            "Machine rattachee a : {}. Cle API recuperee et stockee chiffree."
            .format(_thirdparty_label(data))
        ), False
    except requests.exceptions.SSLError:
        return False, "Erreur de certificat SSL.", False
    except requests.exceptions.ConnectionError:
        return False, "Impossible de joindre le serveur (URL incorrecte ?).", False
    except requests.exceptions.Timeout:
        return False, "Delai d'attente depasse.", False


def _thirdparty_label(data):
    """Build a readable label: name (alias) zip town."""
    name = data.get("thirdparty_name") or "Tiers #{}".format(data.get("thirdparty_id", "?"))
    alias = data.get("thirdparty_alias")
    parts = [name + (" ({})".format(alias) if alias else "")]
    zip_code = data.get("thirdparty_zip")
    town = data.get("thirdparty_town")
    location = " ".join(p for p in (zip_code, town) if p)
    if location:
        parts.append(location)
    return " ".join(parts)


def test_connection(config):
    """Ping the Dolibarr status endpoint. Returns (ok, message)."""
    try:
        resp = requests.get(
            dolibarr_url(config, DOLIBARR_STATUS_PATH),
            headers=auth_headers(config),
            timeout=config.get("timeout_seconds", 30),
            verify=config.get("verify_ssl", True),
        )
        if resp.status_code == 200:
            return True, "Connexion reussie : API Dolibarr accessible."
        if resp.status_code in (401, 403):
            return False, "Authentification refusee : verifiez la cle API."
        return False, "HTTP {}: {}".format(resp.status_code, resp.reason)
    except requests.exceptions.SSLError:
        return False, "Erreur de certificat SSL."
    except requests.exceptions.ConnectionError:
        return False, "Impossible de joindre le serveur (URL incorrecte ?)."
    except requests.exceptions.Timeout:
        return False, "Delai d'attente depasse."


def send_report(config):
    """Collect system info and POST it to the Dolibarr API."""
    payload = collect_system_info(config)
    url = dolibarr_url(config, ENDPOINT_PATH)
    resp = requests.post(
        url,
        json=payload,
        headers=auth_headers(config),
        timeout=config.get("timeout_seconds", 30),
        verify=config.get("verify_ssl", True),
    )
    if resp.status_code == 404:
        logger.warning(
            "Endpoint %s introuvable : le module Dolibarr 'sysinfo' "
            "doit etre installe cote serveur.", url
        )
    resp.raise_for_status()
    logger.info("Report sent successfully (status %s)", resp.status_code)
    return payload


def _machine_id():
    """Stable device GUID: Android ro.serialno/boot IDs, else random UUID."""
    for prop in ("ro.serialno", "ro.boot.serialno"):
        try:
            result = subprocess.run(
                ["getprop", prop],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            value = result.stdout.decode("utf-8", errors="ignore").strip()
        except (OSError, subprocess.SubprocessError):
            value = ""
        if value:
            return "android-" + value
    for path in ("/proc/sys/kernel/random/boot_id",):
        try:
            with open(path, "r", encoding="utf-8") as f:
                value = f.read().strip()
            if value:
                return "android-" + value
        except OSError:
            continue
    return str(uuid.uuid4())


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    config = load_config(sys.argv[1] if len(sys.argv) > 1 else "config.json")
    print(json.dumps(send_report(config), indent=2, default=str))

"""Collect Android system information to report to the Dolibarr API.

Runs under Termux (Python on Android). Data sources:
- platform / socket / os for host identity
- psutil for CPU, memory, disks, network interfaces, boot time
- `getprop` for device model, Android version, build details
- Termux:API commands (termux-battery-status) when available
- /sys/class/power_supply for battery info without Termux:API
"""

import os
import platform
import re
import socket
import subprocess
import time

import psutil
import requests

PUBLIC_IP_SERVICES = (
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
)

ISP_INFO_SERVICE = "https://ipinfo.io/json"


def collect_system_info(config):
    """Collect Android system information to report to the API."""
    info = {
        "guid": config["guid"],
        "hostname": socket.gethostname(),
        "fqdn": socket.getfqdn(),
        "platform": platform.system(),
        "platform_release": platform.release(),
        "platform_version": platform.version(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
    }

    props = _getprop()
    if props:
        info["os_details"] = {
            "device": props.get("ro.product.device"),
            "model": props.get("ro.product.model"),
            "brand": props.get("ro.product.brand"),
            "manufacturer": props.get("ro.product.manufacturer"),
            "board": props.get("ro.product.board"),
            "android_version": props.get("ro.build.version.release"),
            "sdk_int": props.get("ro.build.version.sdk"),
            "security_patch": props.get("ro.build.version.security_patch"),
            "build_id": props.get("ro.build.display.id"),
            "build_type": props.get("ro.build.type"),
            "is_emulator": _is_emulator(props),
        }
        info["android_edition"] = " ".join(
            p
            for p in (props.get("ro.product.brand"), props.get("ro.product.model"))
            if p
        )

    mem = psutil.virtual_memory()
    info["memory"] = {
        "total_bytes": mem.total,
        "available_bytes": mem.available,
        "used_bytes": mem.used,
        "percent_used": mem.percent,
    }

    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        disks.append(
            {
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "percent_used": usage.percent,
            }
        )
    info["disks"] = disks

    nics = []
    for name, addrs in psutil.net_if_addrs().items():
        addresses = [
            {"family": str(a.family), "address": a.address, "netmask": a.netmask}
            for a in addrs
            if a.family in (socket.AF_INET, socket.AF_INET6)
        ]
        if addresses:
            nics.append({"name": name, "addresses": addresses})
    info["network_interfaces"] = nics

    boot_time = psutil.boot_time()
    info["boot_time"] = boot_time
    info["uptime_seconds"] = time.time() - boot_time

    info["cpu"] = {
        "count_logical": psutil.cpu_count(logical=True),
        "count_physical": psutil.cpu_count(logical=False),
        "percent_used": psutil.cpu_percent(interval=1),
    }

    info["mac_addresses"] = _mac_addresses()
    info["public_ip"] = _public_ip()
    info["isp"] = _isp()
    info["battery"] = _battery_status()
    return info


def _run_command(command, timeout=5):
    """Run a subprocess and return its stripped stdout, or None on failure."""
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        return result.stdout.decode("utf-8", errors="ignore").strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _getprop():
    """Read all Android system properties via getprop (best effort)."""
    output = _run_command(["getprop"])
    if not output:
        return {}
    props = {}
    for line in output.splitlines():
        match = re.match(r"^\[(.+)\]:\s*\[(.*)\]$", line.strip())
        if match:
            props[match.group(1)] = match.group(2)
    return props


def _is_emulator(props):
    hints = (
        props.get("ro.kernel.qemu"),
        props.get("ro.boot.qemu"),
        props.get("ro.hardware"),
    )
    return any(h and h in ("1", "goldfish", "ranchu") for h in hints)


def _battery_status():
    """Battery info via Termux:API, falling back to /sys/class/power_supply."""
    status = _termux_battery_status()
    if status is None:
        status = _sysfs_battery_status()
    if status is None:
        return {"available": False}
    status["available"] = True
    return status


def _termux_battery_status():
    output = _run_command(["termux-battery-status"], timeout=10)
    if not output:
        return None
    try:
        import json

        data = json.loads(output)
    except ValueError:
        return None
    result = {}
    if "percentage" in data:
        result["percent"] = data["percentage"]
    if "status" in data:
        result["charging"] = data["status"] in (
            "CHARGING",
            "FULL",
            "NOT_CHARGING",
        )
    if "temperature" in data:
        result["temperature_celsius"] = round(data["temperature"], 1)
    if "health" in data:
        result["health"] = data["health"]
    if "current" in data:
        result["current_microamps"] = data["current"]
    return result or None


def _sysfs_battery_status():
    base = "/sys/class/power_supply"
    if not os.path.isdir(base):
        return None
    for name in sorted(os.listdir(base)):
        path = os.path.join(base, name)
        if "battery" not in name.lower():
            continue
        result = {}
        capacity = _read_int(os.path.join(path, "capacity"))
        if capacity is not None:
            result["percent"] = capacity
        status = _read_str(os.path.join(path, "status"))
        if status:
            result["status"] = status
            result["charging"] = status in ("Charging", "Full", "Not charging")
        temp = _read_int(os.path.join(path, "temp"))
        if temp is not None:
            result["temperature_celsius"] = round(temp / 10.0, 1)
        health = _read_str(os.path.join(path, "health"))
        if health:
            result["health"] = health
        if result:
            return result
    return None


def _read_int(path):
    value = _read_str(path)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _read_str(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _public_ip():
    """Fetch the public IP from an external service (best effort)."""
    for service in PUBLIC_IP_SERVICES:
        try:
            resp = requests.get(service, timeout=5)
            if resp.status_code == 200:
                ip = resp.text.strip()
                if ip:
                    return ip
        except requests.RequestException:
            continue
    return None


def _isp():
    """Fetch the ISP name from ipinfo.io (best effort)."""
    try:
        resp = requests.get(ISP_INFO_SERVICE, timeout=5)
        if resp.status_code == 200:
            return resp.json().get("org") or None
    except (requests.RequestException, ValueError):
        pass
    return None


def _mac_addresses():
    macs = []
    for name, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family == getattr(psutil, "AF_LINK", None):
                if addr.address and addr.address not in macs:
                    macs.append(addr.address)
    return macs

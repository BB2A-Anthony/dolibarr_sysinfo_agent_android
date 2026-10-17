"""Android-native system info collection (used inside the APK).

Fallback used by agent.collector when psutil is unavailable (native app
build, where psutil cannot be compiled). Uses Android Java APIs via
pyjnius, shipped with the Kivy/p4a SDL2 bootstrap. Same payload keys
as the Termux collector so the Dolibarr server needs no change.
"""
import logging
import platform
import socket
import time

import requests

logger = logging.getLogger("agent.mobile_collect")

PUBLIC_IP_SERVICES = (
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
)
ISP_INFO_SERVICE = "https://ipinfo.io/json"


def _autoclass(name):
    from jnius import autoclass
    return autoclass(name)


def _context():
    """Return the current Android Context (service or activity)."""
    try:
        svc = _autoclass("org.kivy.android.PythonService")
        if getattr(svc, "mService", None):
            return svc.mService
    except Exception:
        pass
    try:
        act = _autoclass("org.kivy.android.PythonActivity")
        return act.mActivity
    except Exception:
        return None


def collect_system_info(config):
    """Build the same payload dict as agent.collector, Android-native."""
    info = {
        "guid": config["guid"],
        "hostname": _hostname(),
        "fqdn": socket.getfqdn(),
        "platform": "Android",
        "platform_release": "",
        "platform_version": _android_version(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
    }
    ctx = _context()
    details = _os_details()
    if details:
        info["os_details"] = details
        info["android_edition"] = " ".join(
            p for p in (details.get("brand"), details.get("model")) if p
        )
    info["memory"] = _memory(ctx)
    info["disks"] = _disks(ctx)
    info["network_interfaces"] = _networks()
    info["boot_time"] = _boot_time()
    info["uptime_seconds"] = _uptime()
    info["cpu"] = _cpu()
    info["mac_addresses"] = _mac_addresses()
    info["public_ip"] = _public_ip()
    info["isp"] = _isp()
    info["battery"] = _battery(ctx)
    return info


def _hostname():
    try:
        Build = _autoclass("android.os.Build")
        return Build.MODEL or socket.gethostname()
    except Exception:
        return socket.gethostname()


def _android_version():
    try:
        VERSION = _autoclass("android.os.Build$VERSION")
        return VERSION.RELEASE or ""
    except Exception:
        return ""


def _os_details():
    try:
        Build = _autoclass("android.os.Build")
        VERSION = _autoclass("android.os.Build$VERSION")

        def g(v):
            return v or None

        return {
            "device": g(Build.DEVICE),
            "model": g(Build.MODEL),
            "brand": g(Build.BRAND),
            "manufacturer": g(Build.MANUFACTURER),
            "board": g(Build.BOARD),
            "android_version": g(VERSION.RELEASE),
            "sdk_int": str(VERSION.SDK_INT) if VERSION.SDK_INT else None,
            "security_patch": g(getattr(VERSION, "SECURITY_PATCH", None)),
            "build_id": g(Build.ID),
            "build_type": g(Build.TYPE),
            "is_emulator": _is_emulator(Build),
        }
    except Exception as exc:
        logger.warning("os_details indisponibles: %s", exc)
        return None


def _is_emulator(Build):
    fingerprint = (Build.FINGERPRINT or "").lower()
    hints = (
        "generic" in fingerprint,
        "test-keys" in fingerprint,
        getattr(Build, "HARDWARE", "") in ("goldfish", "ranchu"),
        "sdk" in (getattr(Build, "PRODUCT", "") or ""),
        "emulator" in (getattr(Build, "MODEL", "") or "").lower(),
    )
    return any(hints)


def _memory(ctx):
    if not ctx:
        return {"total_bytes": None, "available_bytes": None,
                "used_bytes": None, "percent_used": None}
    try:
        ActivityManager = _autoclass("android.app.ActivityManager")
        am = ctx.getSystemService(ctx.ACTIVITY_SERVICE)
        mi = ActivityManager.MemoryInfo()
        am.getMemoryInfo(mi)
        total = int(mi.totalMem)
        avail = int(mi.availMem)
        used = total - avail
        return {
            "total_bytes": total,
            "available_bytes": avail,
            "used_bytes": used,
            "percent_used": round(used * 100.0 / total, 1) if total else None,
        }
    except Exception as exc:
        logger.warning("memoire indisponible: %s", exc)
        return {"total_bytes": None, "available_bytes": None,
                "used_bytes": None, "percent_used": None}


def _disks(ctx):
    out = []

    def add(path, device, mountpoint, fstype):
        try:
            StatFs = _autoclass("android.os.StatFs")
            st = StatFs(path)
            total = st.getBlockCountLong() * st.getBlockSizeLong()
            free = st.getAvailableBlocksLong() * st.getBlockSizeLong()
            used = total - free
            out.append({
                "device": device,
                "mountpoint": mountpoint,
                "fstype": fstype,
                "total_bytes": total,
                "used_bytes": used,
                "free_bytes": free,
                "percent_used": round(used * 100.0 / total, 1) if total else None,
            })
        except Exception as exc:
            logger.warning("disk %s indisponible: %s", path, exc)

    add("/data", "/data", "/data", "ext4")
    if ctx:
        try:
            ext = ctx.getExternalFilesDir(None)
            if ext:
                add(ext.getAbsolutePath(), "sdcard", ext.getAbsolutePath(), "ext4")
        except Exception:
            pass
    return out


def _networks():
    nics = []
    try:
        NetworkInterface = _autoclass("java.net.NetworkInterface")
        enums = NetworkInterface.getNetworkInterfaces()
        while enums.hasMoreElements():
            ni = enums.nextElement()
            addresses = []
            ia = ni.getInetAddresses()
            while ia.hasMoreElements():
                addr = ia.nextElement()
                host = addr.getHostAddress()
                family = "2" if ":" not in host else "10"
                addresses.append({"family": family, "address": host, "netmask": None})
            if addresses:
                nics.append({"name": ni.getName(), "addresses": addresses})
    except Exception as exc:
        logger.warning("reseaux indisponibles: %s", exc)
    return nics


def _mac_addresses():
    macs = []
    try:
        NetworkInterface = _autoclass("java.net.NetworkInterface")
        enums = NetworkInterface.getNetworkInterfaces()
        while enums.hasMoreElements():
            ni = enums.nextElement()
            raw = ni.getHardwareAddress()
            if raw:
                mac = ":".join("%02x" % b for b in raw)
                if mac not in macs:
                    macs.append(mac)
    except Exception:
        pass
    return macs


def _boot_time():
    try:
        SystemClock = _autoclass("android.os.SystemClock")
        System = _autoclass("java.lang.System")
        return (System.currentTimeMillis() - SystemClock.elapsedRealtime()) / 1000.0
    except Exception:
        return None


def _uptime():
    try:
        SystemClock = _autoclass("android.os.SystemClock")
        return SystemClock.elapsedRealtime() / 1000.0
    except Exception:
        return None


def _cpu():
    logical = None
    try:
        Runtime_ = _autoclass("java.lang.Runtime")
        logical = Runtime_.getRuntime().availableProcessors()
    except Exception:
        pass
    return {
        "count_logical": logical,
        "count_physical": None,
        "percent_used": _cpu_percent(),
    }


def _cpu_percent(interval=1.0):
    def totals():
        try:
            with open("/proc/stat", "r") as f:
                parts = f.readline().split()[1:]
            values = [int(p) for p in parts]
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            return sum(values), idle
        except Exception:
            return None, None

    total1, idle1 = totals()
    if total1 is None:
        return None
    time.sleep(interval)
    total2, idle2 = totals()
    if not total2 or total2 == total1:
        return None
    total_delta = total2 - total1
    idle_delta = idle2 - idle1
    if total_delta <= 0:
        return None
    return round(100.0 * (total_delta - idle_delta) / total_delta, 1)


def _battery(ctx):
    if not ctx:
        return {"available": False}
    try:
        Intent = _autoclass("android.content.Intent")
        IntentFilter = _autoclass("android.content.IntentFilter")
        BatteryManager = _autoclass("android.os.BatteryManager")
        intent = ctx.registerReceiver(None, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        if intent is None:
            return {"available": False}
        level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        status = intent.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
        plugged = intent.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1)
        temp = intent.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1)
        health = intent.getIntExtra(BatteryManager.EXTRA_HEALTH, -1)
        result = {}
        if level >= 0 and scale > 0:
            result["percent"] = level * 100 // scale
        result["status"] = str(status)
        result["charging"] = (
            status == BatteryManager.BATTERY_STATUS_CHARGING
            or status == BatteryManager.BATTERY_STATUS_FULL
            or plugged > 0
        )
        if temp >= 0:
            result["temperature_celsius"] = round(temp / 10.0, 1)
        if health > 0:
            result["health"] = str(health)
        result["available"] = True
        return result
    except Exception as exc:
        logger.warning("batterie indisponible: %s", exc)
        return {"available": False}


def _public_ip():
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
    try:
        resp = requests.get(ISP_INFO_SERVICE, timeout=5)
        if resp.status_code == 200:
            return resp.json().get("org") or None
    except (requests.RequestException, ValueError):
        pass
    return None

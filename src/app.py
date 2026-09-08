import os
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any

import paramiko
from flask import Flask, jsonify


app = Flask(__name__)

NAS_HOST = os.getenv("NAS_HOST", "").strip()
NAS_PORT = int(os.getenv("NAS_PORT", "22"))
NAS_USER = os.getenv("NAS_USER", "sshd")
SSH_KEY = os.getenv("SSH_KEY", "/run/secrets/nas_ssh_key")
NAS_MOUNT = os.getenv("NAS_MOUNT", "").strip()
CACHE_SECONDS = int(os.getenv("CACHE_SECONDS", "15"))

XMLDB_SOCKET = "/var/run/xmldb_sock_sysinfo"

cache_lock = threading.Lock()
cached_data: dict[str, Any] | None = None
cached_at = 0.0


def xml_text(
    element: ET.Element,
    path: str,
    default: str = "",
) -> str:
    """Return stripped XML text or a default value."""
    found = element.find(path)

    if found is None or found.text is None:
        return default

    return found.text.strip()


def safe_int(value: str, default: int = 0) -> int:
    """Convert a string to int without raising an exception."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def create_ssh_client() -> paramiko.SSHClient:
    """Connect to the WD NAS over SSH."""
    if not NAS_HOST:
        raise RuntimeError("NAS_HOST is not configured")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    client.connect(
        hostname=NAS_HOST,
        port=NAS_PORT,
        username=NAS_USER,
        key_filename=SSH_KEY,
        timeout=10,
        banner_timeout=10,
        auth_timeout=10,
    )

    return client


def run_ssh_command(
    client: paramiko.SSHClient,
    command: str,
    timeout: int = 20,
) -> str:
    """Run a command over SSH and return stdout."""
    _, stdout, stderr = client.exec_command(
        command,
        timeout=timeout,
    )

    output = stdout.read().decode(
        "utf-8",
        errors="replace",
    ).strip()

    error = stderr.read().decode(
        "utf-8",
        errors="replace",
    ).strip()

    exit_status = stdout.channel.recv_exit_status()

    if exit_status != 0:
        raise RuntimeError(
            f"Remote command failed with exit status "
            f"{exit_status}: {error or command}"
        )

    return output


def query_xmldb(
    client: paramiko.SSHClient,
    node: str,
    filename: str,
) -> ET.Element:
    """Query WD's internal xmldb socket and parse the result."""
    command = (
        f"xmldbc -p {node} {filename} "
        f"-S {XMLDB_SOCKET} && "
        f"cat {filename} && "
        f"rm -f {filename}"
    )

    xml_data = run_ssh_command(client, command)

    if not xml_data:
        raise RuntimeError(
            f"WD xmldb returned no data for {node}"
        )

    try:
        return ET.fromstring(xml_data)
    except ET.ParseError as exc:
        raise RuntimeError(
            f"Invalid XML returned for {node}: {exc}"
        ) from exc


def read_cpu_percent(
    client: paramiko.SSHClient,
) -> int:
    """Calculate CPU usage from two /proc/stat samples."""
    output = run_ssh_command(
        client,
        "head -n 1 /proc/stat; "
        "sleep 1; "
        "head -n 1 /proc/stat",
    )

    lines = output.splitlines()

    if len(lines) != 2:
        raise RuntimeError(
            "Could not read two CPU samples"
        )

    def parse_cpu_line(line: str) -> tuple[int, int]:
        values = [
            int(value)
            for value in line.split()[1:]
        ]

        idle = values[3]

        if len(values) > 4:
            idle += values[4]

        return sum(values), idle

    total_1, idle_1 = parse_cpu_line(lines[0])
    total_2, idle_2 = parse_cpu_line(lines[1])

    total_delta = total_2 - total_1
    idle_delta = idle_2 - idle_1

    if total_delta <= 0:
        return 0

    usage = (
        100
        * (total_delta - idle_delta)
        / total_delta
    )

    return max(
        0,
        min(100, round(usage)),
    )


def read_memory_percent(
    client: paramiko.SSHClient,
) -> int:
    """Calculate memory usage from /proc/meminfo."""
    output = run_ssh_command(
        client,
        "cat /proc/meminfo",
    )

    values: dict[str, int] = {}

    for line in output.splitlines():
        if ":" not in line:
            continue

        key, raw_value = line.split(":", 1)
        parts = raw_value.strip().split()

        if parts and parts[0].isdigit():
            values[key] = int(parts[0])

    total = values.get("MemTotal", 0)

    if total <= 0:
        return 0

    available = values.get("MemAvailable")

    if available is None:
        available = (
            values.get("MemFree", 0)
            + values.get("Buffers", 0)
            + values.get("Cached", 0)
        )

    used = max(0, total - available)
    percentage = used * 100 / total

    return max(
        0,
        min(100, round(percentage)),
    )


def parse_disks(
    disks_xml: ET.Element,
) -> list[dict[str, Any]]:
    """Parse disk health, temperature and SMART data."""
    disks: list[dict[str, Any]] = []

    for disk in disks_xml.findall("disk"):
        smart_result = xml_text(
            disk,
            "smart/result",
            "Unknown",
        )

        disks.append(
            {
                "id": disk.attrib.get("id", ""),
                "name": xml_text(disk, "name"),
                "device": xml_text(disk, "dev"),
                "model": xml_text(disk, "model"),
                "serial": xml_text(disk, "sn"),
                "size": safe_int(
                    xml_text(disk, "size", "0")
                ),
                "temperature": safe_int(
                    xml_text(disk, "temp", "0")
                ),
                "healthy": (
                    xml_text(
                        disk,
                        "healthy",
                        "0",
                    )
                    == "1"
                ),
                "failed": (
                    xml_text(
                        disk,
                        "failed",
                        "0",
                    )
                    == "1"
                ),
                "over_temperature": (
                    xml_text(
                        disk,
                        "over_temp",
                        "0",
                    )
                    == "1"
                ),
                "sleeping": (
                    xml_text(
                        disk,
                        "sleep",
                        "0",
                    )
                    == "1"
                ),
                "smart": smart_result,
                "smart_passed": (
                    smart_result
                    .lower()
                    .startswith("pass")
                ),
            }
        )

    return disks


def parse_raids(
    raids_xml: ET.Element,
) -> list[dict[str, Any]]:
    """Parse WD RAID information."""
    raids: list[dict[str, Any]] = []

    for raid in raids_xml.findall("raid"):
        raids.append(
            {
                "id": xml_text(raid, "id"),
                "device": xml_text(raid, "dev"),
                "level": xml_text(raid, "level"),
                "state": xml_text(
                    raid,
                    "state",
                    "unknown",
                ),
                "state_detail": xml_text(
                    raid,
                    "state_detail",
                ),
                "size": safe_int(
                    xml_text(
                        raid,
                        "size",
                        "0",
                    )
                ),
                "total_disks": safe_int(
                    xml_text(
                        raid,
                        "num_of_total_disks",
                        "0",
                    )
                ),
                "working_disks": safe_int(
                    xml_text(
                        raid,
                        "num_of_working_disks",
                        "0",
                    )
                ),
                "failed_disks": safe_int(
                    xml_text(
                        raid,
                        "num_of_failed_disks",
                        "0",
                    )
                ),
                "rebuilding_disks": xml_text(
                    raid,
                    "rebuilding_disks",
                ),
                "dirty": (
                    xml_text(
                        raid,
                        "dirty",
                        "0",
                    )
                    == "1"
                ),
            }
        )

    return raids


def parse_volumes(
    volumes_xml: ET.Element,
) -> dict[str, Any]:
    """Parse capacity and mounted-volume data."""
    volume = volumes_xml.find("vol")

    total_bytes = safe_int(
        xml_text(
            volumes_xml,
            "total_size",
            "0",
        )
    )

    used_bytes = safe_int(
        xml_text(
            volumes_xml,
            "total_used_size",
            "0",
        )
    )

    free_bytes = safe_int(
        xml_text(
            volumes_xml,
            "total_unused_size",
            "0",
        )
    )

    storage_percent = (
        round(used_bytes * 100 / total_bytes)
        if total_bytes > 0
        else 0
    )

    return {
        "name": (
            xml_text(volume, "name")
            if volume is not None
            else ""
        ),
        "mountpoint": (
            xml_text(volume, "mnt")
            if volume is not None
            else ""
        ),
        "mounted": (
            volume is not None
            and xml_text(
                volume,
                "mounted",
                "0",
            )
            == "1"
        ),
        "raid_level": (
            xml_text(
                volume,
                "raid_level",
            )
            if volume is not None
            else ""
        ),
        "raid_state": (
            xml_text(
                volume,
                "raid_state",
            )
            if volume is not None
            else ""
        ),
        "total_bytes": total_bytes,
        "used_bytes": used_bytes,
        "free_bytes": free_bytes,
        "percent": storage_percent,
        "total_human": xml_text(
            volumes_xml,
            "total_size_h",
        ),
        "used_human": xml_text(
            volumes_xml,
            "total_used_size_h",
        ),
        "free_human": xml_text(
            volumes_xml,
            "total_unused_size_h",
        ),
    }


def get_mount_status() -> dict[str, Any]:
    """Check an optional NAS filesystem mount."""
    if not NAS_MOUNT:
        return {
            "enabled": False,
            "online": None,
            "total_bytes": 0,
            "used_bytes": 0,
            "free_bytes": 0,
            "percent": 0,
        }

    try:
        stats = os.statvfs(NAS_MOUNT)

        total = stats.f_blocks * stats.f_frsize
        available = stats.f_bavail * stats.f_frsize
        used = total - available

        return {
            "enabled": True,
            "online": os.path.isdir(NAS_MOUNT),
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": available,
            "percent": (
                round(used * 100 / total)
                if total > 0
                else 0
            ),
        }

    except OSError:
        return {
            "enabled": True,
            "online": False,
            "total_bytes": 0,
            "used_bytes": 0,
            "free_bytes": 0,
            "percent": 0,
        }


def determine_health(
    disks: list[dict[str, Any]],
    raids: list[dict[str, Any]],
    volume: dict[str, Any],
) -> str:
    """Create a simple overall health state."""
    disks_ok = bool(disks) and all(
        disk["healthy"]
        and not disk["failed"]
        and not disk["over_temperature"]
        and disk["smart_passed"]
        for disk in disks
    )

    raids_ok = bool(raids) and all(
        raid["state"] == "clean"
        and raid["failed_disks"] == 0
        and not raid["dirty"]
        for raid in raids
    )

    volume_ok = (
        volume["mounted"]
        and volume["raid_state"] == "clean"
    )

    if disks_ok and raids_ok and volume_ok:
        return "Healthy"

    if any(
        raid["failed_disks"] > 0
        or raid["state"] == "degraded"
        for raid in raids
    ):
        return "Degraded"

    if any(
        raid["rebuilding_disks"]
        for raid in raids
    ):
        return "Rebuilding"

    return "Attention"


def health_metadata(health: str) -> tuple[str, str]:
    """Return machine-readable severity and a display icon."""
    states = {
        "Healthy": ("ok", "🟢"),
        "Rebuilding": ("warning", "🟡"),
        "Attention": ("warning", "🟠"),
        "Degraded": ("critical", "🔴"),
        "Offline": ("unavailable", "⚫"),
    }

    return states.get(health, ("unknown", "⚪"))


def build_status(
    cpu_percent: int,
    memory_percent: int,
    disks: list[dict[str, Any]],
    raids: list[dict[str, Any]],
    volume: dict[str, Any],
) -> dict[str, Any]:
    """Build both raw and Homepage-friendly output."""
    data_raid = max(
        raids,
        key=lambda raid: raid["size"],
        default={},
    )

    raid_level = (
        data_raid.get(
            "level",
            volume.get("raid_level", "unknown"),
        )
        or "unknown"
    ).upper()

    raid_state = (
        data_raid.get(
            "state",
            volume.get("raid_state", "unknown"),
        )
        or "unknown"
    )

    health = determine_health(
        disks,
        raids,
        volume,
    )

    health_severity, health_icon = health_metadata(
        health
    )

    disk_1_temp = (
        disks[0]["temperature"]
        if len(disks) >= 1
        else 0
    )

    disk_2_temp = (
        disks[1]["temperature"]
        if len(disks) >= 2
        else 0
    )

    smart_ok = bool(disks) and all(
        disk["smart_passed"]
        for disk in disks
    )

    return {
        # Raw Homepage fields
        "cpu": cpu_percent,
        "ram": memory_percent,
        "storage": volume["percent"],
        "raid": f"{raid_level} {raid_state}",
        "health": health,
        "health_severity": health_severity,
        "health_icon": health_icon,
        "disk1_temp": disk_1_temp,
        "disk2_temp": disk_2_temp,

        # Formatted Homepage fields
        "cpu_display": f"{cpu_percent}%",
        "ram_display": f"{memory_percent}%",
        "storage_display": (
            f"{volume['used_human']} / "
            f"{volume['total_human']}"
        ),
        "storage_percent_display": (
            f"{volume['percent']}%"
        ),
        "free_display": volume["free_human"],
        "health_display": (
            f"{raid_level} • {health}"
        ),
        "raid_display": (
            f"{raid_level} • "
            f"{raid_state.title()}"
        ),
        "disk1_display": (
            f"{disk_1_temp}°C"
            if len(disks) >= 1
            else "N/A"
        ),
        "disk2_display": (
            f"{disk_2_temp}°C"
            if len(disks) >= 2
            else "N/A"
        ),
        "temperature_display": (
            f"{disk_1_temp}° / "
            f"{disk_2_temp}°"
            if len(disks) >= 2
            else (
                f"{disk_1_temp}°C"
                if len(disks) == 1
                else "N/A"
            )
        ),
        "smart_display": (
            "Pass"
            if smart_ok
            else "Check"
        ),

        # Capacity details
        "storage_used": volume["used_human"],
        "storage_total": volume["total_human"],
        "storage_free": volume["free_human"],
        "storage_used_bytes": volume["used_bytes"],
        "storage_total_bytes": volume["total_bytes"],
        "storage_free_bytes": volume["free_bytes"],

        # Detailed data
        "volume": volume,
        "disks": disks,
        "raids": raids,
        "mount": get_mount_status(),
        "updated": int(time.time()),
    }


def collect_status() -> dict[str, Any]:
    """Collect all NAS metrics in one SSH session."""
    client = create_ssh_client()

    try:
        cpu_percent = read_cpu_percent(client)
        memory_percent = read_memory_percent(client)

        disks_xml = query_xmldb(
            client,
            "/disks",
            "/tmp/homepage-disks.xml",
        )

        raids_xml = query_xmldb(
            client,
            "/raids",
            "/tmp/homepage-raids.xml",
        )

        volumes_xml = query_xmldb(
            client,
            "/vols",
            "/tmp/homepage-volumes.xml",
        )

    finally:
        client.close()

    disks = parse_disks(disks_xml)
    raids = parse_raids(raids_xml)
    volume = parse_volumes(volumes_xml)

    return build_status(
        cpu_percent,
        memory_percent,
        disks,
        raids,
        volume,
    )


def get_cached_status() -> dict[str, Any]:
    """Return cached metrics to avoid excessive SSH polling."""
    global cached_data
    global cached_at

    now = time.time()

    with cache_lock:
        cache_is_valid = (
            cached_data is not None
            and now - cached_at < CACHE_SECONDS
        )

        if cache_is_valid:
            return cached_data

        cached_data = collect_status()
        cached_at = now

        return cached_data


@app.get("/status")
def status():
    try:
        return jsonify(get_cached_status())

    except Exception as exc:
        return jsonify(
            {
                "health": "Offline",
                "health_severity": "unavailable",
                "health_icon": "⚫",
                "health_display": "NAS • Offline",
                "error": str(exc),
                "updated": int(time.time()),
            }
        ), 503


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "wd-os5-exporter",
        }
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8085,
    )

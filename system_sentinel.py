"""JARVIS System Sentinel & Hardware Telemetry Suite for DarkShadow.

Provides real-time system monitoring, CPU/RAM telemetry, battery diagnostics,
top resource-consuming process inspection, and safe task termination for Windows 11.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import socket
import sys
from dataclasses import dataclass, field
from typing import Any

LOGGER = logging.getLogger(__name__)

# Critical OS processes protected from termination
PROTECTED_PROCESS_NAMES = {
    "system",
    "registry",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "services.exe",
    "lsass.exe",
    "svchost.exe",
    "dwm.exe",
    "winlogon.exe",
    "explorer.exe",
    "spoolsv.exe",
    "fontdrvhost.exe",
}


@dataclass
class HardwareTelemetry:
    """Snapshot of system hardware utilization."""

    cpu_percent: float
    cpu_freq_ghz: float
    cpu_cores_logical: int
    ram_total_gb: float
    ram_used_gb: float
    ram_free_gb: float
    ram_percent: float
    disk_total_gb: float
    disk_used_gb: float
    disk_free_gb: float
    disk_percent: float
    battery_percent: int | None
    is_charging: bool | None
    hostname: str
    os_name: str
    uptime_hours: float
    network_status: str


class SystemSentinel:
    """Hardware telemetry monitor and safe process inspector."""

    _instance: SystemSentinel | None = None

    @classmethod
    def get_instance(cls) -> SystemSentinel:
        """Singleton accessor."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_telemetry(self) -> HardwareTelemetry:
        """Collect live hardware telemetry from Windows."""
        import psutil

        # CPU
        cpu_pct = psutil.cpu_percent(interval=None)
        cpu_freq_obj = psutil.cpu_freq()
        cpu_freq_ghz = round(cpu_freq_obj.current / 1000.0, 2) if cpu_freq_obj else 0.0
        cpu_cores = psutil.cpu_count(logical=True) or 1

        # Memory (RAM)
        vmem = psutil.virtual_memory()
        ram_tot = round(vmem.total / (1024**3), 2)
        ram_used = round(vmem.used / (1024**3), 2)
        ram_free = round(vmem.available / (1024**3), 2)
        ram_pct = vmem.percent

        # Disk
        root_path = Path_root = "C:\\" if os.name == "nt" else "/"
        disk = shutil.disk_usage(root_path)
        disk_tot = round(disk.total / (1024**3), 1)
        disk_used = round((disk.total - disk.free) / (1024**3), 1)
        disk_free = round(disk.free / (1024**3), 1)
        disk_pct = round((disk_used / disk_tot) * 100, 1) if disk_tot > 0 else 0.0

        # Battery
        battery = psutil.sensors_battery()
        bat_pct = int(battery.percent) if battery else None
        charging = battery.power_plugged if battery else None

        # Uptime
        import time
        boot_time = psutil.boot_time()
        uptime_h = round((time.time() - boot_time) / 3600.0, 1)

        # Basic Network check
        net_status = "Connected"
        try:
            net_io = psutil.net_io_counters()
            if net_io.bytes_recv == 0 and net_io.bytes_sent == 0:
                net_status = "Disconnected"
        except Exception:
            net_status = "Online"

        return HardwareTelemetry(
            cpu_percent=cpu_pct,
            cpu_freq_ghz=cpu_freq_ghz,
            cpu_cores_logical=cpu_cores,
            ram_total_gb=ram_tot,
            ram_used_gb=ram_used,
            ram_free_gb=ram_free,
            ram_percent=ram_pct,
            disk_total_gb=disk_tot,
            disk_used_gb=disk_used,
            disk_free_gb=disk_free,
            disk_percent=disk_pct,
            battery_percent=bat_pct,
            is_charging=charging,
            hostname=socket.gethostname(),
            os_name=f"{platform.system()} {platform.release()}",
            uptime_hours=uptime_h,
            network_status=net_status,
        )

    def get_top_processes(self, limit: int = 5, sort_by: str = "memory") -> list[dict[str, Any]]:
        """List the top resource-consuming applications currently running."""
        import psutil

        procs: list[dict[str, Any]] = []
        for p in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent"]):
            try:
                info = p.info
                mem_bytes = info.get("memory_info").rss if info.get("memory_info") else 0
                mem_mb = round(mem_bytes / (1024 * 1024), 1)
                procs.append({
                    "pid": info.get("pid"),
                    "name": info.get("name") or "unknown",
                    "memory_mb": mem_mb,
                    "cpu_percent": info.get("cpu_percent") or 0.0,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        if sort_by == "cpu":
            procs.sort(key=lambda x: x["cpu_percent"], reverse=True)
        else:
            procs.sort(key=lambda x: x["memory_mb"], reverse=True)

        return procs[:max(1, min(limit, 20))]

    def safe_terminate_process(self, pid_or_name: int | str) -> dict[str, Any]:
        """Safely terminate a hung or runaway process while protecting system critical apps."""
        import psutil

        my_pid = os.getpid()

        # By PID
        if isinstance(pid_or_name, int) or str(pid_or_name).isdigit():
            target_pid = int(pid_or_name)
            if target_pid == my_pid:
                return {"success": False, "message": "Captain, main DarkShadow ke apne hi process ko terminate nahi kar sakta!"}
            try:
                proc = psutil.Process(target_pid)
                pname = proc.name().lower()
                if pname in PROTECTED_PROCESS_NAMES:
                    return {"success": False, "message": f"Captain, '{pname}' ek critical Windows system process hai, ise terminate karna safe nahi hai."}
                proc.terminate()
                return {"success": True, "message": f"Process '{pname}' (PID {target_pid}) ko successfully close kar diya gaya."}
            except psutil.NoSuchProcess:
                return {"success": False, "message": f"PID {target_pid} active nahi mila."}
            except psutil.AccessDenied:
                return {"success": False, "message": f"PID {target_pid} close karne ke liye administrator privileges chahiye."}

        # By Name
        clean_name = str(pid_or_name).strip().lower()
        if clean_name in PROTECTED_PROCESS_NAMES:
            return {"success": False, "message": f"Captain, '{clean_name}' system critical process hai, ise kill nahi kiya ja sakta."}

        matched = []
        for p in psutil.process_iter(["pid", "name"]):
            try:
                if p.info["name"] and clean_name in p.info["name"].lower():
                    if p.info["pid"] != my_pid:
                        matched.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not matched:
            return {"success": False, "message": f"'{pid_or_name}' naam se koi active process nahi mila."}

        closed_count = 0
        for p in matched:
            try:
                p.terminate()
                closed_count += 1
            except Exception:
                pass

        return {
            "success": closed_count > 0,
            "message": f"Captain, '{pid_or_name}' ke {closed_count} process(es) terminate kar diye gaye.",
            "closed_count": closed_count,
        }

    def format_telemetry_report(self, include_top_procs: bool = True) -> str:
        """Format an executive hardware health briefing for Captain."""
        t = self.get_telemetry()

        battery_str = "Desktop (AC Powered)"
        if t.battery_percent is not None:
            charging_state = "Charging ⚡" if t.is_charging else "Discharging"
            battery_str = f"{t.battery_percent}% ({charging_state})"

        lines = [
            f"Captain, **Live System Diagnostics ({t.hostname})**:",
            f"• **CPU:** {t.cpu_percent}% @ {t.cpu_freq_ghz} GHz ({t.cpu_cores_logical} cores)",
            f"• **RAM:** {t.ram_used_gb} GB used / {t.ram_total_gb} GB total ({t.ram_percent}%)",
            f"• **Storage (C:):** {t.disk_free_gb} GB free of {t.disk_total_gb} GB ({t.disk_percent}% used)",
            f"• **Battery / Power:** {battery_str}",
            f"• **Uptime:** {t.uptime_hours} ghante | **Network:** {t.network_status}",
        ]

        if include_top_procs:
            top = self.get_top_processes(limit=4)
            if top:
                lines.append("\n**Top Resource-Consuming Apps:**")
                for p in top:
                    lines.append(f"  - `{p['name']}`: {p['memory_mb']} MB RAM | {p['cpu_percent']}% CPU")

        return "\n".join(lines)


__all__ = [
    "HardwareTelemetry",
    "SystemSentinel",
    "PROTECTED_PROCESS_NAMES",
]

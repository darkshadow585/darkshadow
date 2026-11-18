"""Dynamic Self-Improvement Backlog for DarkShadow.

When Captain requests a command or workflow step for which code has not yet been written,
DarkShadow records the missing capability into `.darkshadow/improvements.jsonl` and
generates a structured markdown roadmap in `.darkshadow/improvements.md`.

This ensures DarkShadow never fails silently, never crashes on unimplemented features,
and systematically catalogs future upgrades requested by Captain.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent
_DARKSHADOW_DIR = _PROJECT_ROOT / ".darkshadow"
IMPROVEMENTS_JSONL_PATH = _DARKSHADOW_DIR / "improvements.jsonl"
IMPROVEMENTS_MD_PATH = _DARKSHADOW_DIR / "improvements.md"


@dataclass
class ImprovementEntry:
    """Represents one missing or requested capability."""

    id: str
    capability_name: str
    requested_command: str
    reason: str
    suggested_implementation: str
    timestamp: str
    status: str = "PENDING"  # PENDING | IN_PROGRESS | IMPLEMENTED
    priority: str = "MEDIUM"  # LOW | MEDIUM | HIGH


class ImprovementBacklog:
    """Manages recording, reading, and rendering missing capability improvements."""

    _instance: ImprovementBacklog | None = None

    def __init__(
        self,
        jsonl_path: Path | str = IMPROVEMENTS_JSONL_PATH,
        md_path: Path | str = IMPROVEMENTS_MD_PATH,
    ) -> None:
        self.jsonl_path = Path(jsonl_path)
        self.md_path = Path(md_path)
        self._ensure_storage()

    @classmethod
    def get_instance(cls) -> ImprovementBacklog:
        """Singleton accessor."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _ensure_storage(self) -> None:
        """Ensure destination directories exist."""
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self.md_path.parent.mkdir(parents=True, exist_ok=True)

    def load_entries(self) -> list[ImprovementEntry]:
        """Load all entries from the JSONL file."""
        if not self.jsonl_path.exists():
            return []
        entries: list[ImprovementEntry] = []
        try:
            with open(self.jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        entries.append(ImprovementEntry(**data))
                    except (json.JSONDecodeError, TypeError) as parse_err:
                        LOGGER.debug("Skipping malformed improvement line: %s", parse_err)
        except Exception as exc:
            LOGGER.warning("Failed to load improvements from %s: %s", self.jsonl_path, exc)
        return entries

    def record_missing_capability(
        self,
        capability_name: str,
        requested_command: str,
        reason: str = "Code not written yet",
        suggested_implementation: str = "",
        priority: str = "MEDIUM",
    ) -> ImprovementEntry:
        """Record a missing capability into JSONL and refresh the markdown roadmap."""
        self._ensure_storage()
        now = datetime.datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
        date_prefix = now.strftime("%Y%m%d")
        entry_id = f"IMP-{date_prefix}-{uuid.uuid4().hex[:4].upper()}"

        clean_cap = str(capability_name).strip() or "unspecified_capability"
        clean_cmd = str(requested_command).strip()

        # Check deduplication: if exact capability is already pending, return existing
        existing_entries = self.load_entries()
        for e in existing_entries:
            if (
                e.status == "PENDING"
                and e.capability_name.casefold() == clean_cap.casefold()
            ):
                LOGGER.info("Capability '%s' already logged in backlog (%s)", clean_cap, e.id)
                return e

        entry = ImprovementEntry(
            id=entry_id,
            capability_name=clean_cap,
            requested_command=clean_cmd,
            reason=str(reason).strip() or "Capability not yet implemented in DarkShadow",
            suggested_implementation=(
                str(suggested_implementation).strip()
                or f"Implement `{clean_cap}` handler in skill.py or automation.py"
            ),
            timestamp=timestamp_str,
            status="PENDING",
            priority=priority.upper(),
        )

        # 1. Append to JSONL atomically
        try:
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            LOGGER.info("Recorded missing capability to %s (ID: %s)", self.jsonl_path.name, entry.id)
        except Exception as exc:
            LOGGER.warning("Failed to append to %s: %s", self.jsonl_path, exc)

        # 2. Update markdown report
        self.update_markdown_roadmap()

        return entry

    def update_markdown_roadmap(self) -> None:
        """Regenerate the human-readable improvements.md roadmap file."""
        entries = self.load_entries()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            "# 🚀 DarkShadow Autonomous Improvements Backlog",
            "",
            "> **Generated autonomously by DarkShadow RealWork Orchestrator**  ",
            f"> *Last Updated: {now_str}*  ",
            "",
            "Jab bhi Captain koi aisi command ya mission dete hain jiska code abhi DarkShadow me nahi likha gaya hai, "
            "DarkShadow use is backlog me record kar leta hai taaki aage aane wale upgrades me ise implement kiya ja sake.",
            "",
            "## 📋 Pending Capabilities (Future Roadmap)",
            "",
            "| ID | Capability / Feature | Triggered Command | Suggested Implementation | Priority | Date Logged |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]

        pending = [e for e in entries if e.status == "PENDING"]
        if not pending:
            lines.append("| - | *Koi pending capability nahi hai* | *Sabhi requested features implemented hain!* | - | - | - |")
        else:
            for e in pending:
                cmd_escaped = e.requested_command.replace("|", "\\|").replace("\n", " ")[:60]
                sug_escaped = e.suggested_implementation.replace("|", "\\|").replace("\n", " ")[:70]
                lines.append(
                    f"| `{e.id}` | **{e.capability_name}** | {cmd_escaped} | {sug_escaped} | `{e.priority}` | {e.timestamp} |"
                )

        # Show completed if any
        completed = [e for e in entries if e.status == "IMPLEMENTED"]
        if completed:
            lines.extend([
                "",
                "## ✅ Recently Implemented",
                "",
                "| ID | Capability | Implemented Date |",
                "| :--- | :--- | :--- |",
            ])
            for e in completed:
                lines.append(f"| `{e.id}` | {e.capability_name} | {e.timestamp} |")

        lines.extend([
            "",
            "---",
            "*To view this inside DarkShadow, type `/improvements` or ask: 'kya kya improvements baki hai'.*",
        ])

        try:
            self.md_path.write_text("\n".join(lines), encoding="utf-8")
        except Exception as exc:
            LOGGER.warning("Failed to write %s: %s", self.md_path, exc)

    def format_summary_for_captain(self) -> str:
        """Return friendly Hinglish readout of pending improvements for Captain."""
        entries = self.load_entries()
        pending = [e for e in entries if e.status == "PENDING"]
        if not pending:
            return (
                "Captain, hamare improvements backlog me abhi koi pending feature nahi hai! "
                "Aap jo bhi naya kaam kahenge jiska code nahi hoga, main turant yaha note kar lunga."
            )

        count = len(pending)
        sample_names = ", ".join(f"'{e.capability_name}'" for e in pending[:4])
        more_text = f" aur {count - 4} aur" if count > 4 else ""

        report_lines = [
            f"Captain, improvements backlog (`.darkshadow/improvements.md`) me kul **{count} feature(s)** pending hain:",
            f"- Features: {sample_names}{more_text}",
            "\nIn sabhi ke liye main roadmap bana chuka hoon taaki aage ke updates me hum inhe direct code kar sakein!",
        ]
        return "\n".join(report_lines)


__all__ = [
    "ImprovementEntry",
    "ImprovementBacklog",
    "IMPROVEMENTS_JSONL_PATH",
    "IMPROVEMENTS_MD_PATH",
]

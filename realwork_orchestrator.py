"""RealWork Autonomous Orchestrator for DarkShadow.

Decomposes complex real-world commands into multi-step executable plans,
runs each step with live feedback, and gracefully records any missing/unwritten
tools into the dynamic self-improvement backlog (.darkshadow/improvements.md).
"""

from __future__ import annotations

import datetime
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from improvement_backlog import ImprovementBacklog
from safety import CAMERA_BLOCKED_MESSAGE, ensure_captain_address

LOGGER = logging.getLogger(__name__)


@dataclass
class RealWorkStep:
    """Represents a single step in a multi-step real-work mission."""

    step_idx: int
    title: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    status: str = "PENDING"  # PENDING | RUNNING | COMPLETED | FAILED | BACKLOGGED
    result_message: str = ""


@dataclass
class RealWorkPlan:
    """Complete decomposed plan for a mission."""

    mission_goal: str
    steps: list[RealWorkStep] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )


class RealWorkOrchestrator:
    """Orchestrates mission planning, live step execution, and backlog capture."""

    _instance: RealWorkOrchestrator | None = None

    def __init__(self, backlog: ImprovementBacklog | None = None) -> None:
        self.backlog = backlog or ImprovementBacklog.get_instance()

    @classmethod
    def get_instance(cls) -> RealWorkOrchestrator:
        """Singleton accessor."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def decompose_mission(
        self,
        goal_text: str,
        client: Any = None,
        settings: Any = None,
    ) -> RealWorkPlan:
        """Break down Captain's goal into an ordered sequence of actionable steps."""
        cleaned_goal = str(goal_text).strip()
        if not cleaned_goal:
            return RealWorkPlan(mission_goal="", steps=[])

        # 1. Try Gemini model decomposition if client is available
        if client is not None and hasattr(client, "models"):
            plan = self._decompose_with_gemini(cleaned_goal, client, settings)
            if plan and plan.steps:
                return plan

        # 2. Fallback to intelligent heuristic rule-based decomposition
        return self._decompose_heuristic(cleaned_goal)

    def _decompose_with_gemini(
        self,
        goal_text: str,
        client: Any,
        settings: Any,
    ) -> RealWorkPlan | None:
        """Decompose mission using Gemini structured generation."""
        try:
            model_name = getattr(settings, "model", "gemini-3.8-flash")
            prompt = (
                "You are the Mission Decomposition Planner for DarkShadow, an intelligent desktop assistant for Windows 11.\n"
                "Captain (the user) has given a mission. Break it down into sequential, atomic sub-steps.\n\n"
                f"Mission Goal: {goal_text}\n\n"
                "Available tools in DarkShadow include:\n"
                "- search_google(query)\n"
                "- search_youtube(query)\n"
                "- play_youtube(query)\n"
                "- send_whatsapp_message(recipient, message)\n"
                "- prepare_whatsapp_message(recipient, message)\n"
                "- search_whatsapp_contact(contact_name)\n"
                "- open_application(app_name)\n"
                "- open_website(url_or_name)\n"
                "- set_volume(level)\n"
                "- change_volume(direction, amount)\n"
                "- set_brightness(level)\n"
                "- get_system_status()\n"
                "- get_system_telemetry()\n"
                "- get_current_time()\n"
                "- get_current_date()\n"
                "- inspect_clipboard()\n"
                "- copy_to_clipboard(text)\n"
                "- save_note(text)\n"
                "- recall_memory(query)\n"
                "- deep_research(topic)\n"
                "- execute_terminal_command(command)\n\n"
                "CRITICAL RULES:\n"
                "1. Never fabricate fake or dummy phone numbers (e.g. '9876543210'). For WhatsApp or messaging actions, pass the recipient's exact name (e.g. 'Kuldeep', 'Rahul', 'Mummy').\n"
                "2. If a step requires the output or summary of an earlier step (e.g. sending a search result or note via WhatsApp), set that argument to '$PREV' so the pipeline dynamically pipes the data.\n"
                "3. If a sub-step requires an action for which NO tool currently exists in DarkShadow "
                "(e.g. photoshop_filter, convert_pdf_to_audio, book_flight, train_model, export_to_notion), "
                "YOU MUST STILL INCLUDE IT with a descriptive tool_name (e.g. 'photoshop_filter') and appropriate arguments. "
                "DarkShadow's improvement logger will automatically log it into the development backlog!\n\n"
                "Return a valid JSON array of step objects with this schema:\n"
                '[\n  {\n    "step_idx": 1,\n    "title": "Short title",\n    "tool_name": "tool_name",\n    "arguments": {},\n    "description": "What this step accomplishes"\n  }\n]'
            )

            call_kwargs: dict[str, Any] = {
                "model": model_name,
                "contents": prompt,
            }
            try:
                from google.genai import types
                tb = getattr(settings, "thinking_budget_automation", 1024) if settings else 1024
                if hasattr(types, "ThinkingConfig") and tb > 0:
                    call_kwargs["config"] = types.GenerateContentConfig(
                        thinking_config=types.ThinkingConfig(
                            thinking_budget=tb,
                            include_thoughts=False,
                        ),
                        temperature=0.1,
                    )
            except Exception:
                pass

            response = client.models.generate_content(**call_kwargs)
            raw_text = getattr(response, "text", "") or ""
            # Extract JSON block
            match = re.search(r"\[\s*\{.*\}\s*\]", raw_text, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                steps = []
                for idx, item in enumerate(data, 1):
                    steps.append(
                        RealWorkStep(
                            step_idx=idx,
                            title=item.get("title", f"Step {idx}"),
                            tool_name=item.get("tool_name", "custom_action"),
                            arguments=item.get("arguments", {}),
                            description=item.get("description", ""),
                        )
                    )
                if steps:
                    return RealWorkPlan(mission_goal=goal_text, steps=steps)
        except Exception as exc:
            LOGGER.warning("Gemini decomposition notice: %s", exc)
        return None

    def _decompose_heuristic(self, goal_text: str) -> RealWorkPlan:
        """Heuristic rule-based multi-step decomposer when offline or fast parsing."""
        # Split on natural conjunctive boundaries: 'aur fir', 'then', 'fir', 'uske baad', 'and', ';'
        normalized = re.sub(r"\b(?:pehle|first)\b\s*", "", goal_text, flags=re.IGNORECASE)
        delimiter_pattern = r"\b(?:aur\s+fir|uske\s+baad|then|fir|aur|and)\b|[;\n]"
        raw_parts = [p.strip() for p in re.split(delimiter_pattern, normalized, flags=re.IGNORECASE) if p.strip()]

        if not raw_parts:
            raw_parts = [goal_text.strip()]

        steps: list[RealWorkStep] = []
        for idx, part in enumerate(raw_parts, 1):
            lower_part = part.lower()

            # Identify candidate tool from text keywords
            tool_name = "custom_action"
            arguments: dict[str, Any] = {}
            title = part[:40]

            if any(k in lower_part for k in ("system status", "pc status", "system health", "hardware")):
                tool_name = "get_system_status"
                title = "Check System Status"
            elif any(k in lower_part for k in ("ram", "memory", "cpu usage")):
                tool_name = "get_system_telemetry"
                title = "Check Hardware Telemetry"
            elif any(k in lower_part for k in ("whatsapp", "wa")):
                if "draft" in lower_part:
                    tool_name = "prepare_whatsapp_message"
                    title = "Prepare WhatsApp Draft"
                    arguments = {"recipient": "contact", "message": part}
                else:
                    tool_name = "send_whatsapp_message"
                    title = "Send WhatsApp Message"
                    arguments = {"recipient": "contact", "message": part}
            elif any(k in lower_part for k in ("youtube", "video", "gaana", "song", "play")):
                tool_name = "play_youtube"
                title = "Play Media on YouTube"
                arguments = {"query": part}
            elif any(k in lower_part for k in ("google search", "search google", "khojo", "dhoondo", "search")):
                tool_name = "search_google"
                title = "Search Google"
                arguments = {"query": part}
            elif any(k in lower_part for k in ("deep research", "research")):
                tool_name = "deep_research"
                title = "Run Deep Research"
                arguments = {"topic": part}
            elif any(k in lower_part for k in ("note", "likh lo", "save note")):
                tool_name = "save_note"
                title = "Save Note"
                arguments = {"text": part}
            elif any(k in lower_part for k in ("clipboard", "copy")):
                tool_name = "inspect_clipboard"
                title = "Inspect Clipboard"
            elif any(k in lower_part for k in ("open", "kholo", "chalao")):
                tool_name = "open_application"
                title = f"Open {part[:20]}"
                arguments = {"app_name": part}
            else:
                # Missing or specialized tool request
                # e.g. "photoshop me image filter lagao", "excel sheet banaye"
                clean_name = re.sub(r"[^a-zA-Z0-9_]+", "_", part.strip().lower())[:25].strip("_")
                tool_name = clean_name or f"unwritten_tool_{idx}"
                title = part[:40]
                arguments = {"instruction": part}

            steps.append(
                RealWorkStep(
                    step_idx=idx,
                    title=title,
                    tool_name=tool_name,
                    arguments=arguments,
                    description=part,
                )
            )

        return RealWorkPlan(mission_goal=goal_text, steps=steps)

    def is_tool_implemented(self, tool_name: str, skill_registry: Any = None) -> bool:
        """Check if DarkShadow has executable code/handler for the requested tool."""
        # 1. Check SkillRegistry
        if skill_registry is not None:
            if hasattr(skill_registry, "get") and skill_registry.get(tool_name) is not None:
                return True

        # 2. Check ToolRegistry / Automation
        try:
            from tool_registry import dispatch_tool
            # Known established tools
            known_tools = {
                "get_system_status",
                "get_system_telemetry",
                "get_current_time",
                "get_current_date",
                "search_google",
                "search_youtube",
                "play_youtube",
                "send_whatsapp_message",
                "prepare_whatsapp_message",
                "search_whatsapp_contact",
                "make_phone_call",
                "open_application",
                "open_website",
                "set_volume",
                "change_volume",
                "set_brightness",
                "scroll_screen",
                "click_screen_element",
                "inspect_desktop_window",
                "execute_terminal_command",
                "search_local_files",
                "deep_research",
                "inspect_clipboard",
                "copy_to_clipboard",
                "save_note",
                "recall_memory",
            }
            if tool_name in known_tools:
                return True
        except Exception:
            pass

        return False

    def execute_mission(
        self,
        plan: RealWorkPlan,
        progress_callback: Callable[[str], None] | None = None,
        skill_registry: Any = None,
        memory_store: Any = None,
    ) -> dict[str, Any]:
        """Execute all steps of the mission sequentially with live updates and backlog logging."""
        total_steps = len(plan.steps)
        if total_steps == 0:
            msg = "Captain, mission me koi steps identify nahi hue."
            if progress_callback:
                progress_callback(msg)
            return {"success": False, "message": msg, "plan": plan}

        # Announcement of the plan
        announcement_lines = [
            f"Captain, mission receive hua: '{plan.mission_goal}'",
            f"Maine ise **{total_steps} sequential steps** me plan kiya hai:",
        ]
        for s in plan.steps:
            announcement_lines.append(f"  {s.step_idx}. {s.title} ({s.description})")
        announcement_lines.append("\nAb execution shuru kar raha hoon...")

        if progress_callback:
            progress_callback("\n".join(announcement_lines))

        completed_steps = 0
        backlogged_steps = 0
        failed_steps = 0
        last_step_output: str = ""

        for s in plan.steps:
            # Context piping: dynamically pass previous step output if requested
            if last_step_output and isinstance(s.arguments, dict):
                for k, v in list(s.arguments.items()):
                    if isinstance(v, str):
                        if "$PREV" in v or "$LAST_RESULT" in v:
                            s.arguments[k] = v.replace("$PREV", last_step_output).replace("$LAST_RESULT", last_step_output)
                        elif k in {"message", "text", "content"} and v.strip() in {"", "result", "summary", "previous_result"}:
                            s.arguments[k] = last_step_output

            s.status = "RUNNING"
            step_start_msg = f"Captain, Step {s.step_idx}/{total_steps} shuru kar raha hoon: {s.title}..."
            if progress_callback:
                progress_callback(step_start_msg)

            # Check camera privacy first
            if "camera" in s.tool_name.lower() or "webcam" in s.tool_name.lower():
                s.status = "FAILED"
                s.result_message = CAMERA_BLOCKED_MESSAGE
                failed_steps += 1
                if progress_callback:
                    progress_callback(f"Step {s.step_idx} blocked: {CAMERA_BLOCKED_MESSAGE}")
                continue

            # Check if code is written / tool is implemented
            if self.is_tool_implemented(s.tool_name, skill_registry):
                # EXECUTE IMPLEMENTED TOOL
                try:
                    res = self._execute_step_tool(s, skill_registry, memory_store)
                    if res.get("success", False):
                        s.status = "COMPLETED"
                        s.result_message = res.get("message", "Completed successfully")
                        step_data = res.get("data") or {}
                        if isinstance(step_data, dict):
                            last_step_output = str(step_data.get("result") or step_data.get("summary") or s.result_message)
                        else:
                            last_step_output = str(s.result_message)
                        completed_steps += 1
                        success_msg = f"Step {s.step_idx} complete! {s.result_message}. Ab agle step par chalte hain..."
                        if progress_callback:
                            progress_callback(success_msg)
                    else:
                        s.status = "FAILED"
                        s.result_message = res.get("message", "Execution failed")
                        failed_steps += 1
                        if progress_callback:
                            progress_callback(f"Step {s.step_idx} warning: {s.result_message}. Continuing mission...")
                except Exception as exc:
                    s.status = "FAILED"
                    s.result_message = f"Error: {exc}"
                    failed_steps += 1
                    if progress_callback:
                        progress_callback(f"Step {s.step_idx} error: {exc}. Continuing mission...")
            else:
                # MISSING CAPABILITY - LOG TO IMPROVEMENT BACKLOG!
                s.status = "BACKLOGGED"
                suggested_code = f"Add `{s.tool_name}` handler in skill.py or automation.py"
                entry = self.backlog.record_missing_capability(
                    capability_name=s.tool_name,
                    requested_command=s.description or s.title,
                    reason="Code not written yet in DarkShadow codebase",
                    suggested_implementation=suggested_code,
                    priority="HIGH" if total_steps <= 3 else "MEDIUM",
                )
                s.result_message = f"Logged to improvements backlog ({entry.id})"
                backlogged_steps += 1

                backlog_msg = (
                    f"Captain, Step {s.step_idx} ('{s.title}') ke liye abhi code nahi likha gaya hai. "
                    f"Maine ise improvement file (.darkshadow/improvements.md) me note kar liya hai taaki "
                    f"hum ise aage jod sakein. Ab main bache huye steps execute kar raha hoon..."
                )
                if progress_callback:
                    progress_callback(backlog_msg)

        # FINAL MISSION REPORT
        report_lines = [
            f"\n🎯 **Mission Concluded:** '{plan.mission_goal}'",
            f"- Total Steps: {total_steps}",
            f"- ✅ Completed: {completed_steps}",
            f"- 📋 Backlogged for Future: {backlogged_steps}",
        ]
        if failed_steps > 0:
            report_lines.append(f"- ⚠️ Warnings/Failed: {failed_steps}")

        if backlogged_steps > 0:
            report_lines.append(
                "\n*Note: Jo capabilities abhi implemented nahi thi, unhe `.darkshadow/improvements.md` "
                "me log kar diya gaya hai. Aap `/improvements` se unki list dekh sakte hain.*"
            )

        final_summary = ensure_captain_address("\n".join(report_lines))
        if progress_callback:
            progress_callback(final_summary)

        return {
            "success": completed_steps > 0 or backlogged_steps > 0,
            "message": final_summary,
            "plan": plan,
            "completed_steps": completed_steps,
            "backlogged_steps": backlogged_steps,
            "failed_steps": failed_steps,
        }

    def _execute_step_tool(
        self,
        step: RealWorkStep,
        skill_registry: Any,
        memory_store: Any,
    ) -> dict[str, Any]:
        """Dispatch step to appropriate skill or tool implementation."""
        # 1. SkillRegistry execution
        if skill_registry is not None and hasattr(skill_registry, "execute"):
            if skill_registry.get(step.tool_name) is not None:
                skill_res = skill_registry.execute(step.tool_name, **step.arguments)
                return {
                    "success": skill_res.success,
                    "message": skill_res.message,
                    "data": skill_res.data,
                }

        # 2. ToolRegistry dispatch
        from tool_registry import dispatch_tool
        raw_res = dispatch_tool(step.tool_name, step.arguments)
        status = raw_res.get("status", "error")
        return {
            "success": status in {"ok", "success"},
            "message": raw_res.get("message", "Tool executed"),
            "data": raw_res.get("data", {}),
        }


__all__ = [
    "RealWorkStep",
    "RealWorkPlan",
    "RealWorkOrchestrator",
]

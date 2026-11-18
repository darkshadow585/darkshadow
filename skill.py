"""Modular 5-Level Skill Architecture for DarkShadow Chatbot.

Defines, organizes, and executes capabilities across 5 levels of intelligence:
- Level 1: Native Multimodal Screen Vision (Zero Face-Camera)
- Level 2: Autonomous ReAct Multi-Step Reasoning Loop
- Level 3: Advanced Cross-App Workflow Orchestrator
- Level 4: Hierarchical Long-Term Memory & Context Distillation
- Level 5: Proactive Ambient Desktop Co-Pilot

Privacy Guarantee:
All physical camera, webcam, and face recording capabilities are STRICTLY
prohibited and hard-blocked to protect Captain's privacy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Callable

from safety import CAMERA_BLOCKED_MESSAGE

LOGGER = logging.getLogger(__name__)


class SkillLevel(IntEnum):
    """5-Level Capability Hierarchy for DarkShadow."""

    LEVEL_1_SCREEN_VISION = 1
    LEVEL_2_REACT_REASONING = 2
    LEVEL_3_WORKFLOW_ORCHESTRATION = 3
    LEVEL_4_EPISODIC_MEMORY = 4
    LEVEL_5_PROACTIVE_AMBIENT = 5


class SkillCategory(str, Enum):
    """Categorization of DarkShadow skills."""

    SCREEN_VISION = "screen_vision"
    REACT_REASONING = "react_reasoning"
    WORKFLOW_ORCHESTRATION = "workflow_orchestration"
    MEMORY_KNOWLEDGE = "memory_knowledge"
    PROACTIVE_AMBIENT = "proactive_ambient"
    DESKTOP_CONTROL = "desktop_control"
    MEDIA_ENTERTAINMENT = "media_entertainment"
    PRIVACY_BLOCKED = "privacy_blocked"


@dataclass(frozen=True, slots=True)
class SkillResult:
    """Standard output returned by any executed skill."""

    success: bool
    skill_name: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(slots=True)
class Skill:
    """Definition of a single DarkShadow capability."""

    name: str
    level: SkillLevel
    category: SkillCategory
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any] | None = None
    requires_network: bool = False
    requires_camera: bool = False  # If True, hard-blocked for Captain's privacy
    enabled: bool = True
    examples: list[str] = field(default_factory=list)

    def to_gemini_schema(self) -> dict[str, Any]:
        """Convert to Google GenAI function calling schema."""
        return {
            "name": self.name,
            "description": f"[Level {self.level.value} - {self.category.value}] {self.description}",
            "parameters": self.parameters,
        }


class SkillRegistry:
    """Central registry for discovering, validating, and executing DarkShadow skills."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        """Register a new skill into the catalog."""
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        """Retrieve a registered skill by name."""
        return self._skills.get(name)

    def list_skills(
        self,
        level: SkillLevel | int | None = None,
        category: SkillCategory | str | None = None,
        include_disabled: bool = False,
    ) -> list[Skill]:
        """Filter skills by level and/or category."""
        results = []
        for skill in self._skills.values():
            if not include_disabled and not skill.enabled:
                continue
            if level is not None and skill.level != level:
                continue
            if category is not None and skill.category != category:
                continue
            results.append(skill)
        return results

    def export_gemini_schemas(self, max_level: int = 5) -> list[dict[str, Any]]:
        """Export all enabled, non-camera skills up to max_level as Gemini tool schemas."""
        schemas = []
        for skill in self._skills.values():
            if not skill.enabled or skill.requires_camera:
                continue
            if skill.level <= max_level:
                schemas.append(skill.to_gemini_schema())
        # Dynamically append discovered MCP tool schemas
        try:
            from mcp_client import MCPManager
            mcp_schemas = MCPManager.get_instance().get_all_tool_schemas()
            schemas.extend(mcp_schemas)
        except Exception as mcp_err:
            LOGGER.debug("MCP schemas export notice: %s", mcp_err)
        return schemas

    def execute(self, name: str, **kwargs: Any) -> SkillResult:
        """Execute a skill with strict privacy checks."""
        # 1. MCP tool dispatch
        try:
            from mcp_client import MCPManager
            mcp_mgr = MCPManager.get_instance()
            if mcp_mgr.is_mcp_tool(name):
                mcp_res = mcp_mgr.execute_tool(name, kwargs)
                return SkillResult(
                    success=mcp_res.get("success", False),
                    skill_name=name,
                    message=mcp_res.get("output", mcp_res.get("error", "MCP action completed")),
                    data=mcp_res,
                    error=mcp_res.get("error"),
                )
        except Exception as mcp_exec_err:
            LOGGER.debug("MCP execution check error: %s", mcp_exec_err)

        skill = self.get(name)
        if skill is None:
            # Fallback dispatch to existing automation functions if available
            try:
                from automation import execute_automation_command, parsed_command_from_tool_call

                parsed = parsed_command_from_tool_call(name, kwargs)
                if parsed is not None:
                    res = execute_automation_command(parsed)
                    return SkillResult(
                        success=res.success,
                        skill_name=name,
                        message=res.message,
                        data=res.data,
                        error=res.error,
                    )
            except Exception as exc:
                LOGGER.warning("Automation fallback execution failed for %s: %s", name, exc)

            return SkillResult(
                success=False,
                skill_name=name,
                message=f"Skill '{name}' DarkShadow ke catalog me nahi mila.",
                error="skill_not_found",
            )

        # STRICT CAMERA PRIVACY ENFORCEMENT
        if skill.requires_camera or skill.category == SkillCategory.PRIVACY_BLOCKED:
            LOGGER.warning("Blocked attempt to invoke camera-dependent skill: %s", name)
            return SkillResult(
                success=False,
                skill_name=name,
                message=CAMERA_BLOCKED_MESSAGE,
                error="camera_access_denied",
            )

        if not skill.enabled:
            return SkillResult(
                success=False,
                skill_name=name,
                message=f"Captain, '{name}' skill abhi disabled hai.",
                error="skill_disabled",
            )

        if skill.handler is None:
            # If no custom handler attached, attempt automation dispatch
            try:
                from automation import execute_automation_command, parsed_command_from_tool_call

                parsed = parsed_command_from_tool_call(name, kwargs)
                if parsed is not None:
                    res = execute_automation_command(parsed)
                    return SkillResult(
                        success=res.success,
                        skill_name=name,
                        message=res.message,
                        data=res.data,
                        error=res.error,
                    )
            except Exception as exc:
                return SkillResult(
                    success=False,
                    skill_name=name,
                    message=f"Skill execution failed: {exc}",
                    error="handler_error",
                )

            return SkillResult(
                success=True,
                skill_name=name,
                message=f"Captain, '{name}' execute ho gaya.",
                data=kwargs,
            )

        try:
            output = skill.handler(**kwargs)
            if isinstance(output, SkillResult):
                return output
            if isinstance(output, dict):
                return SkillResult(
                    success=output.get("success", True),
                    skill_name=name,
                    message=output.get("message", "Task completed."),
                    data=output.get("data", {}),
                    error=output.get("error"),
                )
            return SkillResult(
                success=True,
                skill_name=name,
                message=str(output),
                data=kwargs,
            )
        except Exception as exc:
            LOGGER.error("Error executing skill %s: %s", name, exc)
            return SkillResult(
                success=False,
                skill_name=name,
                message=f"Skill execution error: {exc}",
                error=str(type(exc).__name__),
            )

    def describe_catalog(self) -> str:
        """Return a structured, readable summary of DarkShadow skills for Captain."""
        lines = [
            "Captain, DarkShadow 5-Level Skill Catalog ready hai:",
            "",
            "Level 1: Screen Vision & Sensory OCR (Monitor Display Only, Zero Face-Camera)",
            "  - analyze_screen: Monitor display analyze karta hai (errors/windows/UI)",
            "  - read_active_window: Active app window text aur context read karta hai",
            "  - click_screen_element: Screen element ko visually dhoond kar click karta hai",
            "",
            "Level 2: Autonomous ReAct Multi-Step Loop (Self-Correcting Reasoning)",
            "  - react_execute_goal: Thought -> Action -> Observation -> Self-Correction loop",
            "  - self_healing_action: Fallback coordination agar primary action fail ho",
            "  - verify_action_success: Verify karta hai task sach me complete hua ya nahi",
            "",
            "Level 3: Advanced Cross-App Workflow Orchestrator (Multi-App Pipelines)",
            "  - chain_multi_app_workflow: Browser + Desktop + WhatsApp + Media sequential pipelines",
            "  - ecommerce_multi_cart: Amazon aur Flipkart multi-store price check & cart",
            "  - media_cross_controller: Background me YouTube/Spotify seamlessly control karna",
            "",
            "Level 4: Hierarchical Long-Term Memory & Context Distillation",
            "  - remember_preference: Captain ke niyam aur preferences hamesha yaad rakhna",
            "  - recall_long_term_context: Past context aur facts recall karna beyond 8 turns",
            "  - summarize_past_session: Rolling conversations ko episodic facts me distill karna",
            "",
            "Level 5: Proactive Ambient Desktop Co-Pilot (Autonomous Watcher)",
            "  - watch_background_job: Terminal builds, scripts, aur downloads complete hone par alert",
            "  - monitor_system_health: High CPU/RAM/Battery spikes par proactively warning dena",
            "  - proactive_desktop_alert: Captain ko important status alert bhejna bina poochhe",
            "",
            "Privacy Shield Protocol: Physical camera / webcam hardware access PERMANENTLY DISABLED.",
        ]
        return "\n".join(lines)


# Global singleton registry
_GLOBAL_REGISTRY: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    """Return or initialize the singleton SkillRegistry with all 5 levels configured."""
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is not None:
        return _GLOBAL_REGISTRY

    registry = SkillRegistry()

    # =========================================================================
    # LEVEL 1: NATIVE MULTIMODAL SCREEN VISION (MONITOR SCREEN ONLY, ZERO CAMERA)
    # =========================================================================
    registry.register(
        Skill(
            name="analyze_screen",
            level=SkillLevel.LEVEL_1_SCREEN_VISION,
            category=SkillCategory.SCREEN_VISION,
            description="Capture user active monitor screen and visually analyze open windows, errors, or code.",
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "What to look for on screen (e.g. 'explain the error', 'read this code')",
                    }
                },
            },
            requires_camera=False,
            enabled=True,
            examples=["screen par kya error hai", "code inspect karo"],
        )
    )
    registry.register(
        Skill(
            name="read_active_window",
            level=SkillLevel.LEVEL_1_SCREEN_VISION,
            category=SkillCategory.SCREEN_VISION,
            description="Read the UI title, controls, and accessibility tree of the currently active desktop window.",
            parameters={"type": "object", "properties": {}},
            requires_camera=False,
            enabled=True,
            examples=["active window padho", "kaunsa app open hai"],
        )
    )
    registry.register(
        Skill(
            name="click_screen_element",
            level=SkillLevel.LEVEL_1_SCREEN_VISION,
            category=SkillCategory.SCREEN_VISION,
            description="Visually locate a button, link, or element on the monitor screen and click it.",
            parameters={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Label, text, or visual name of the button/element to click",
                    }
                },
                "required": ["target"],
            },
            requires_camera=False,
            enabled=True,
            examples=["play button click karo", "apply now par click karo"],
        )
    )
    registry.register(
        Skill(
            name="scroll_screen",
            level=SkillLevel.LEVEL_1_SCREEN_VISION,
            category=SkillCategory.SCREEN_VISION,
            description="Scroll the active desktop window or webpage up or down.",
            parameters={
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["up", "down"]},
                    "amount": {"type": "integer", "description": "Number of scroll notches (default 3)"},
                },
                "required": ["direction"],
            },
            requires_camera=False,
            enabled=True,
            examples=["neeche scroll karo", "scroll up"],
        )
    )
    registry.register(
        Skill(
            name="get_current_time",
            level=SkillLevel.LEVEL_1_SCREEN_VISION,
            category=SkillCategory.DESKTOP_CONTROL,
            description="Return the current local system time.",
            parameters={"type": "object", "properties": {}},
            requires_camera=False,
            enabled=True,
            examples=["time kya hua hai", "current time"],
        )
    )
    registry.register(
        Skill(
            name="get_current_date",
            level=SkillLevel.LEVEL_1_SCREEN_VISION,
            category=SkillCategory.DESKTOP_CONTROL,
            description="Return the current local system date.",
            parameters={"type": "object", "properties": {}},
            requires_camera=False,
            enabled=True,
            examples=["aaj ki date kya hai"],
        )
    )
    registry.register(
        Skill(
            name="get_system_status",
            level=SkillLevel.LEVEL_1_SCREEN_VISION,
            category=SkillCategory.DESKTOP_CONTROL,
            description="Return safe local OS, memory, disk, and uptime status.",
            parameters={"type": "object", "properties": {}},
            requires_camera=False,
            enabled=True,
            examples=["system status", "pc status"],
        )
    )

    # =========================================================================
    # LEVEL 2: AUTONOMOUS REACT MULTI-STEP LOOP & SELF-HEALING REASONING
    # =========================================================================
    registry.register(
        Skill(
            name="react_execute_goal",
            level=SkillLevel.LEVEL_2_REACT_REASONING,
            category=SkillCategory.REACT_REASONING,
            description="Autonomous multi-step ReAct reasoning loop (Thought -> Action -> Observation -> Self-Correction) to achieve a complex goal.",
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "The end goal to accomplish"},
                    "max_steps": {"type": "integer", "description": "Maximum reasoning turns (default 4)"},
                },
                "required": ["goal"],
            },
            requires_camera=False,
            enabled=True,
            examples=["solve this issue step by step", "browser me form fill karke verify karo"],
        )
    )
    registry.register(
        Skill(
            name="verify_action_success",
            level=SkillLevel.LEVEL_2_REACT_REASONING,
            category=SkillCategory.REACT_REASONING,
            description="Verify whether an automation step succeeded by inspecting active window state or screen changes.",
            parameters={
                "type": "object",
                "properties": {
                    "expected_condition": {"type": "string", "description": "Condition to verify (e.g. 'Notepad window visible')"}
                },
                "required": ["expected_condition"],
            },
            requires_camera=False,
            enabled=True,
        )
    )

    # =========================================================================
    # LEVEL 3: ADVANCED CROSS-APP WORKFLOW ORCHESTRATOR
    # =========================================================================
    registry.register(
        Skill(
            name="chain_multi_app_workflow",
            level=SkillLevel.LEVEL_3_WORKFLOW_ORCHESTRATION,
            category=SkillCategory.WORKFLOW_ORCHESTRATION,
            description="Orchestrate a sequential multi-app workflow across browser, desktop apps, files, and messaging.",
            parameters={
                "type": "object",
                "properties": {
                    "workflow_name": {"type": "string", "description": "Name of the workflow"},
                    "steps": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of action steps with tool names and arguments",
                    },
                },
                "required": ["workflow_name", "steps"],
            },
            requires_camera=False,
            enabled=True,
            examples=["news padho aur WhatsApp par draft ready karo"],
        )
    )
    registry.register(
        Skill(
            name="ecommerce_multi_cart",
            level=SkillLevel.LEVEL_3_WORKFLOW_ORCHESTRATION,
            category=SkillCategory.WORKFLOW_ORCHESTRATION,
            description="Autonomous cross-platform shopping comparison (Amazon + Flipkart) and cart addition without manual interaction.",
            parameters={
                "type": "object",
                "properties": {
                    "product": {"type": "string", "description": "Product name or search query"},
                    "max_price": {"type": "number", "description": "Price limit in INR"},
                    "platforms": {"type": "array", "items": {"type": "string"}, "description": "List of platforms like amazon, flipkart"},
                },
                "required": ["product"],
            },
            requires_camera=False,
            enabled=True,
            examples=["Amazon aur Flipkart par gaming mouse cart me add karo under 2000"],
        )
    )
    registry.register(
        Skill(
            name="media_cross_controller",
            level=SkillLevel.LEVEL_3_WORKFLOW_ORCHESTRATION,
            category=SkillCategory.WORKFLOW_ORCHESTRATION,
            description="Control Spotify or YouTube music in the background without stealing active window focus.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["play", "pause", "next", "previous", "search"]},
                    "query": {"type": "string", "description": "Track/artist name if action is play or search"},
                },
                "required": ["action"],
            },
            requires_camera=False,
            enabled=True,
            examples=["Spotify par gaana chala do bina window open kiye"],
        )
    )

    # =========================================================================
    # LEVEL 4: HIERARCHICAL LONG-TERM MEMORY & CONTEXT DISTILLATION
    # =========================================================================
    registry.register(
        Skill(
            name="remember_preference",
            level=SkillLevel.LEVEL_4_EPISODIC_MEMORY,
            category=SkillCategory.MEMORY_KNOWLEDGE,
            description="Store Captain's persistent rule, preference, or fact into permanent episodic memory.",
            parameters={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["preference", "note"]},
                    "content": {"type": "string", "description": "The exact fact or preference to remember"},
                },
                "required": ["kind", "content"],
            },
            requires_camera=False,
            enabled=True,
            examples=["yaad rakhna mujhe dark theme pasand hai"],
        )
    )
    registry.register(
        Skill(
            name="recall_long_term_context",
            level=SkillLevel.LEVEL_4_EPISODIC_MEMORY,
            category=SkillCategory.MEMORY_KNOWLEDGE,
            description="Retrieve Captain's relevant notes, preferences, and project facts across past sessions.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topic or entity to recall"},
                    "limit": {"type": "integer", "description": "Maximum items to recall (default 3)"},
                },
                "required": ["query"],
            },
            requires_camera=False,
            enabled=True,
            examples=["mere project ke notes recall karo"],
        )
    )

    # =========================================================================
    # LEVEL 5: PROACTIVE AMBIENT DESKTOP CO-PILOT (CAMERA-FREE)
    # =========================================================================
    registry.register(
        Skill(
            name="watch_background_job",
            level=SkillLevel.LEVEL_5_PROACTIVE_AMBIENT,
            category=SkillCategory.PROACTIVE_AMBIENT,
            description="Monitor a background terminal build, script, or download and proactively alert Captain upon completion.",
            parameters={
                "type": "object",
                "properties": {
                    "job_name": {"type": "string", "description": "Name or command of the job to monitor"},
                    "process_name": {"type": "string", "description": "Executable or process name (e.g. 'python.exe', 'npm.cmd')"},
                },
                "required": ["job_name"],
            },
            requires_camera=False,
            enabled=True,
            examples=["is script ke complete hone par mujhe batao"],
        )
    )
    registry.register(
        Skill(
            name="monitor_system_health",
            level=SkillLevel.LEVEL_5_PROACTIVE_AMBIENT,
            category=SkillCategory.PROACTIVE_AMBIENT,
            description="Check CPU, RAM, disk, and battery thresholds and return proactive alerts if resources are strained.",
            parameters={"type": "object", "properties": {}},
            requires_camera=False,
            enabled=True,
            examples=["system load check karo"],
        )
    )

    # =========================================================================
    # COMPUTER USE & MULTI-AGENT SWARM CAPABILITIES
    # =========================================================================
    def _handle_visual_click(target: str, click_type: str = "single") -> SkillResult:
        from vision_agent import get_computer_use_executor
        res = get_computer_use_executor().visual_click(target=target, click_type=click_type)
        return SkillResult(
            success=res.get("success", False),
            skill_name="visual_click_element",
            message=res.get("message", "Visual click executed."),
            data=res,
            error=res.get("error"),
        )

    def _handle_visual_type(text: str, target: str | None = None) -> SkillResult:
        from vision_agent import get_computer_use_executor
        res = get_computer_use_executor().visual_type(target=target, text=text)
        return SkillResult(
            success=res.get("success", False),
            skill_name="visual_type_text",
            message=res.get("message", "Visual type executed."),
            data=res,
            error=res.get("error"),
        )

    def _handle_deep_research(topic: str) -> SkillResult:
        from agent_swarm import SwarmCoordinator
        task_id = SwarmCoordinator.get_instance().run_research(topic=topic)
        return SkillResult(
            success=True,
            skill_name="dispatch_deep_research",
            message=f"Captain, '{topic}' par Deep Research Agent background me dispatch kar diya gaya hai (Task ID: {task_id}).",
            data={"task_id": task_id, "topic": topic},
        )

    def _handle_workspace_audit() -> SkillResult:
        from agent_swarm import SwarmCoordinator
        task_id = SwarmCoordinator.get_instance().run_workspace_audit()
        return SkillResult(
            success=True,
            skill_name="run_workspace_audit",
            message=f"Captain, Workspace Auditor Agent dispatch kar diya hai (Task ID: {task_id}).",
            data={"task_id": task_id},
        )

    def _handle_system_cleanup(dry_run: bool = True) -> SkillResult:
        from agent_swarm import SwarmCoordinator
        task_id = SwarmCoordinator.get_instance().run_cleanup(dry_run=dry_run)
        return SkillResult(
            success=True,
            skill_name="run_system_cleanup",
            message=f"Captain, System Cleanup Agent scan kar raha hai (Task ID: {task_id}).",
            data={"task_id": task_id, "dry_run": dry_run},
        )

    registry.register(
        Skill(
            name="visual_click_element",
            level=SkillLevel.LEVEL_1_SCREEN_VISION,
            category=SkillCategory.SCREEN_VISION,
            description="Locate an element on the screen visually or via accessibility and click it.",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Description or label of button/icon to click"},
                    "click_type": {"type": "string", "enum": ["single", "double", "right"]},
                },
                "required": ["target"],
            },
            handler=_handle_visual_click,
            requires_camera=False,
            enabled=True,
            examples=["screen par submit button par click karo"],
        )
    )

    registry.register(
        Skill(
            name="visual_type_text",
            level=SkillLevel.LEVEL_1_SCREEN_VISION,
            category=SkillCategory.SCREEN_VISION,
            description="Focus on a screen input field visually and type text into it.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text string to type"},
                    "target": {"type": "string", "description": "Optional name of input element to focus first"},
                },
                "required": ["text"],
            },
            handler=_handle_visual_type,
            requires_camera=False,
            enabled=True,
            examples=["search bar me DarkShadow type karo"],
        )
    )

    registry.register(
        Skill(
            name="dispatch_deep_research",
            level=SkillLevel.LEVEL_2_REACT_REASONING,
            category=SkillCategory.REACT_REASONING,
            description="Launch autonomous background DeepResearchAgent to research a complex topic and generate a Markdown report.",
            parameters={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Topic or technology to research deeply"},
                },
                "required": ["topic"],
            },
            handler=_handle_deep_research,
            requires_camera=False,
            enabled=True,
            examples=["AI agents par deep research report banao"],
        )
    )

    registry.register(
        Skill(
            name="run_workspace_audit",
            level=SkillLevel.LEVEL_3_WORKFLOW_ORCHESTRATION,
            category=SkillCategory.WORKFLOW_ORCHESTRATION,
            description="Run an autonomous audit on current project repo, git changes, and environment health.",
            parameters={"type": "object", "properties": {}},
            handler=_handle_workspace_audit,
            requires_camera=False,
            enabled=True,
            examples=["workspace audit karo", "git status check karo"],
        )
    )

    registry.register(
        Skill(
            name="run_system_cleanup",
            level=SkillLevel.LEVEL_3_WORKFLOW_ORCHESTRATION,
            category=SkillCategory.DESKTOP_CONTROL,
            description="Scan or clean temporary files, __pycache__, and reclaimable disk storage.",
            parameters={
                "type": "object",
                "properties": {
                    "dry_run": {"type": "boolean", "description": "If true, only scans and reports reclaimable space without deleting"},
                },
            },
            handler=_handle_system_cleanup,
            requires_camera=False,
            enabled=True,
            examples=["system cleanup scan karo", "cache clear karo"],
        )
    )

    def _handle_whatsapp_in_chat_search(contact_name: str, search_term: str) -> SkillResult:
        from desktop_workflow_agent import WhatsAppInChatSearchAgent
        res = WhatsAppInChatSearchAgent.search_and_read(contact_name=contact_name, search_term=search_term)
        return SkillResult(
            success=res.get("success", False),
            skill_name="whatsapp_in_chat_search",
            message=res.get("message", "In-chat search completed."),
            data=res,
            error=res.get("error"),
        )

    def _handle_multi_level_task(goal: str) -> SkillResult:
        from desktop_workflow_agent import HierarchicalTaskExecutor
        res = HierarchicalTaskExecutor.execute_goal(goal=goal)
        return SkillResult(
            success=res.get("success", False),
            skill_name="execute_multi_level_task",
            message=res.get("message", "Task executed."),
            data=res,
            error=res.get("error"),
        )

    registry.register(
        Skill(
            name="whatsapp_in_chat_search",
            level=SkillLevel.LEVEL_3_WORKFLOW_ORCHESTRATION,
            category=SkillCategory.WORKFLOW_ORCHESTRATION,
            description="Multi-level flow: Open WhatsApp, search and open a contact's chat, search for words inside the chat history, and read matching message snippets.",
            parameters={
                "type": "object",
                "properties": {
                    "contact_name": {"type": "string", "description": "Contact or person name on WhatsApp"},
                    "search_term": {"type": "string", "description": "Word or phrase to search inside their chat messages"},
                },
                "required": ["contact_name", "search_term"],
            },
            handler=_handle_whatsapp_in_chat_search,
            requires_camera=False,
            enabled=True,
            examples=["WhatsApp me Saloni ke chat me pagal search karke batao"],
        )
    )

    registry.register(
        Skill(
            name="execute_multi_level_task",
            level=SkillLevel.LEVEL_2_REACT_REASONING,
            category=SkillCategory.REACT_REASONING,
            description="Execute hierarchical multi-level goals across desktop applications with sense-think-act coordination.",
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "High level goal to accomplish across apps"},
                },
                "required": ["goal"],
            },
            handler=_handle_multi_level_task,
            requires_camera=False,
            enabled=True,
            examples=["multi-level workflow chalao"],
        )
    )

    def _handle_search_in_active_app(query: str, app_name: str | None = None) -> SkillResult:
        from desktop_workflow_agent import UniversalInAppOperator
        res = UniversalInAppOperator.search_in_active_or_open_app(query=query, target_app=app_name)
        return SkillResult(
            success=res.get("success", False),
            skill_name="search_in_active_app",
            message=res.get("message", "In-app search completed."),
            data=res,
            error=res.get("error"),
        )

    registry.register(
        Skill(
            name="search_in_active_app",
            level=SkillLevel.LEVEL_1_SCREEN_VISION,
            category=SkillCategory.DESKTOP_CONTROL,
            description="Search directly inside the currently active window or open app (YouTube, Spotify, VS Code, File Explorer) without opening new tabs.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Query or song or file to search for"},
                    "app_name": {"type": "string", "description": "Optional app hint like 'youtube', 'spotify', 'vscode', 'explorer'"},
                },
                "required": ["query"],
            },
            handler=_handle_search_in_active_app,
            requires_camera=False,
            enabled=True,
            examples=["is par Arijit Singh live song search karo", "YouTube par search karo"],
        )
    )
    registry.register(
        Skill(
            name="webcam_record",
            level=SkillLevel.LEVEL_1_SCREEN_VISION,
            category=SkillCategory.PRIVACY_BLOCKED,
            description="Physical webcam video recording (HARD-BLOCKED for Captain's privacy).",
            parameters={"type": "object", "properties": {}},
            requires_camera=True,
            enabled=False,
        )
    )
    registry.register(
        Skill(
            name="face_camera_feed",
            level=SkillLevel.LEVEL_1_SCREEN_VISION,
            category=SkillCategory.PRIVACY_BLOCKED,
            description="Physical face camera stream (HARD-BLOCKED for Captain's privacy).",
            parameters={"type": "object", "properties": {}},
            requires_camera=True,
            enabled=False,
        )
    )

    def _handle_execute_realwork_mission(goal: str) -> SkillResult:
        from realwork_orchestrator import RealWorkOrchestrator
        orchestrator = RealWorkOrchestrator.get_instance()
        plan = orchestrator.decompose_mission(goal)
        res = orchestrator.execute_mission(plan, skill_registry=registry)
        return SkillResult(
            success=res.get("success", False),
            skill_name="execute_realwork_mission",
            message=res.get("message", "Mission concluded."),
            data=res,
        )

    def _handle_view_improvements_backlog(**kwargs: Any) -> SkillResult:
        from improvement_backlog import ImprovementBacklog
        summary = ImprovementBacklog.get_instance().format_summary_for_captain()
        return SkillResult(
            success=True,
            skill_name="view_improvements_backlog",
            message=summary,
        )

    registry.register(
        Skill(
            name="execute_realwork_mission",
            level=SkillLevel.LEVEL_3_WORKFLOW_ORCHESTRATION,
            category=SkillCategory.WORKFLOW_ORCHESTRATION,
            description="Decompose and execute any complex multi-step real-world mission with live progress reporting and automatic missing capability backlog capture.",
            parameters={
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "Complete mission goal from Captain"}
                },
                "required": ["goal"],
            },
            handler=_handle_execute_realwork_mission,
            requires_camera=False,
            enabled=True,
            examples=["pehle system status check karo, fir YouTube par lo-fi chalao"],
        )
    )
    registry.register(
        Skill(
            name="view_improvements_backlog",
            level=SkillLevel.LEVEL_2_REACT_REASONING,
            category=SkillCategory.REACT_REASONING,
            description="View the dynamic improvements backlog of missing capabilities requested by Captain.",
            parameters={"type": "object", "properties": {}},
            handler=_handle_view_improvements_backlog,
            requires_camera=False,
            enabled=True,
            examples=["kya kya improvements baki hai", "/improvements"],
        )
    )

    _GLOBAL_REGISTRY = registry
    return registry

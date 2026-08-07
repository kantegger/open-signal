"""Degraded mode manager (spec §141-143, OS-037).

Operational modes: normal / static_edition / deterministic_only /
section_restricted / archive_only. Mode is derived from feature flags and
budget state; an EditionPolicy decides what each mode allows.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from open_signal.budget import BudgetGuard

MODES = ("normal", "static_edition", "deterministic_only", "section_restricted", "archive_only")


class DegradedModeError(Exception):
    pass


class DegradedModeManager:
    def __init__(self, engine: Any) -> None:
        self.engine = engine

    # -------------------------------------------------------------- mode read
    def current_mode(self) -> str:
        """Derive mode from ops.mode.* feature flags + budget hard limit."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT flag_name, enabled FROM feature_flags "
                    "WHERE flag_name LIKE 'ops.mode.%'"
                )
            ).fetchall()
        for name, enabled in rows:
            if enabled:
                mode = name[len("ops.mode."):]
                return mode if mode in MODES else "normal"
        guard = BudgetGuard(self.engine)
        if guard.state().hard_exceeded():
            return "deterministic_only"
        return "normal"

    def set_mode(self, mode: str, reason: str = "operator action") -> None:
        if mode not in MODES:
            raise DegradedModeError(f"unknown mode {mode!r}")
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE feature_flags SET enabled = false "
                    "WHERE flag_name LIKE 'ops.mode.%'"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO feature_flags (flag_name, enabled, description, updated_at) "
                    "VALUES ('ops.mode.' || :mode, true, :reason, now()) "
                    "ON CONFLICT (flag_name) DO UPDATE SET enabled = true, "
                    "description = :reason, updated_at = now()"
                ),
                {"mode": mode, "reason": reason},
            )

    # -------------------------------------------------------------- policies
    def edition_policy(self, mode: str | None = None) -> dict[str, Any]:
        """What the current mode allows for edition generation."""
        mode = mode or self.current_mode()
        if mode == "archive_only":
            return {
                "generate_editions": False,
                "serve_cached": True,
                "serve_archive": True,
                "llm_agents": False,
                "reason": "archive-only mode",
            }
        if mode == "static_edition":
            return {
                "generate_editions": False,
                "serve_cached": True,
                "serve_archive": True,
                "llm_agents": True,
                "reason": "static edition mode (cached editions served)",
            }
        if mode == "deterministic_only":
            return {
                "generate_editions": True,
                "serve_cached": True,
                "serve_archive": True,
                "llm_agents": False,
                "reason": "deterministic-only mode (no LLM runs)",
            }
        if mode == "section_restricted":
            return {
                "generate_editions": True,
                "serve_cached": True,
                "serve_archive": True,
                "llm_agents": True,
                "restricted_sections": self._restricted_sections(),
                "reason": "section-restricted mode",
            }
        return {
            "generate_editions": True,
            "serve_cached": True,
            "serve_archive": True,
            "llm_agents": True,
            "reason": "normal",
        }

    def _restricted_sections(self) -> list[str]:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT description FROM feature_flags "
                    "WHERE flag_name LIKE 'ops.mode.%' AND enabled = true"
                )
            ).fetchone()
        if row and row[0] and "sections:" in row[0]:
            return [s.strip() for s in row[0].split("sections:")[1].split(",") if s.strip()]
        return []

    # ---------------------------------------------------------------- checks
    def check_edition_generation(self) -> tuple[bool, str]:
        policy = self.edition_policy()
        if not policy["generate_editions"]:
            return False, policy["reason"]
        return True, policy["reason"]

    def check_llm_agent(self, desk_id: str | None = None) -> tuple[bool, str]:
        policy = self.edition_policy()
        if not policy["llm_agents"]:
            return False, policy["reason"]
        guard = BudgetGuard(self.engine)
        allowed, reason, _ = guard.allow_llm_run(desk_id or "any")
        return allowed, reason

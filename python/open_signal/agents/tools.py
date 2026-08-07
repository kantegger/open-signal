"""Agent tool registry (spec §127-130, OS-015).

Tools are the only way agents touch the system. Every tool has a JSON
Schema for arguments, a permission scope, a cost class, and a result-size
limit; every call is logged to ``agent_tool_calls``.

Constraints (spec OS-015): no arbitrary SQL, no arbitrary URL fetch —
tools are pre-registered read-only operations with parameterised queries.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from jsonschema import Draft7Validator, ValidationError
from sqlalchemy import text

# per-call cost estimates by class (USD)
COST_CLASS_USD = {"low": 0.0002, "medium": 0.001, "high": 0.005}

DEFAULT_MAX_RESULT_BYTES = 16_384  # 16 KiB
TOOL_LOG_TRUNCATE = 4_096


class ToolPermissionError(Exception):
    pass


class ToolArgumentError(Exception):
    pass


class ToolResultTooLarge(Exception):
    pass


@dataclass
class ToolSpec:
    id: str
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema (draft-07)
    permission: str  # e.g. "desk:expectations-desk", "readonly"
    cost_class: str = "low"
    max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES
    handler: Callable[[dict[str, Any]], Any] | None = None


@dataclass
class ToolCallResult:
    tool_id: str
    ok: bool = False
    result: Any = None
    error: str | None = None
    result_size_bytes: int = 0
    cost_usd: float = 0.0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    def truncated(self) -> dict[str, Any]:
        """Result bounded to the tool-call log size."""
        return {
            "tool_id": self.tool_id,
            "ok": self.ok,
            "result": self.result,
            "error": self.error,
            "result_size_bytes": self.result_size_bytes,
            "cost_usd": self.cost_usd,
        }


class ToolRegistry:
    """Registers tools, validates calls, enforces permissions and size."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine
        self._tools: dict[str, ToolSpec] = {}
        self._validators: dict[str, Draft7Validator] = {}

    # ---------------------------------------------------------------- registry
    def register(self, spec: ToolSpec) -> None:
        if spec.id in self._tools:
            raise ValueError(f"tool {spec.id} already registered")
        self._tools[spec.id] = spec
        self._validators[spec.id] = Draft7Validator(spec.parameters)

    def get(self, tool_id: str) -> ToolSpec:
        try:
            return self._tools[tool_id]
        except KeyError:
            raise ToolArgumentError(f"unknown tool {tool_id!r}") from None

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
                "permission": t.permission,
                "cost_class": t.cost_class,
            }
            for t in self._tools.values()
        ]

    # ------------------------------------------------------------------ checks
    def validate_arguments(self, tool_id: str, arguments: dict[str, Any]) -> None:
        validator = self._validators.get(tool_id)
        if validator is None:
            raise ToolArgumentError(f"tool {tool_id!r} not registered")
        errors = list(validator.iter_errors(arguments))
        if errors:
            raise ToolArgumentError(f"invalid arguments for {tool_id}: {errors[0].message}")

    def check_permission(self, tool_id: str, permission_scope: str) -> None:
        spec = self.get(tool_id)
        if spec.permission == "readonly":
            return
        if permission_scope != spec.permission:
            raise ToolPermissionError(
                f"tool {tool_id} requires permission {spec.permission!r}, "
                f"caller has {permission_scope!r}"
            )

    # ------------------------------------------------------------------ calls
    def call(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        run_id: str,
        agent_lineage_id: str | None = None,
        permission_scope: str = "readonly",
    ) -> ToolCallResult:
        """Validate, execute and log one tool call."""
        spec = self.get(tool_id)
        self.validate_arguments(tool_id, arguments)
        self.check_permission(tool_id, permission_scope)

        started = datetime.now(timezone.utc)
        result = ToolCallResult(tool_id=tool_id, started_at=started, cost_usd=COST_CLASS_USD[spec.cost_class])
        try:
            if spec.handler is None:
                raise ToolArgumentError(f"tool {tool_id} has no handler")
            output = spec.handler(arguments)
            encoded = json.dumps(output, ensure_ascii=False, default=str)
            result.result_size_bytes = len(encoded.encode())
            if result.result_size_bytes > spec.max_result_bytes:
                raise ToolResultTooLarge(
                    f"result {result.result_size_bytes} bytes exceeds limit {spec.max_result_bytes}"
                )
            result.result = output
            result.ok = True
        except ToolResultTooLarge:
            raise
        except Exception as exc:  # noqa: BLE001
            result.ok = False
            result.error = f"{type(exc).__name__}: {exc}"
        finally:
            result.completed_at = datetime.now(timezone.utc)
            self._log_call(run_id, agent_lineage_id, tool_id, arguments, result)
        return result

    # -------------------------------------------------------------------- log
    def _log_call(
        self,
        run_id: str,
        lineage_id: str | None,
        tool_id: str,
        arguments: dict[str, Any],
        result: ToolCallResult,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO agent_tool_calls
                      (run_id, agent_lineage_id, tool_id, arguments,
                       result_size_bytes, cost_usd, status, error,
                       started_at, completed_at)
                    VALUES
                      (:run, :lineage, :tool, CAST(:args AS jsonb),
                       :size, :cost, :status, :error, :started, :completed)
                    """
                ),
                {
                    "run": run_id,
                    "lineage": lineage_id,
                    "tool": tool_id,
                    "args": json.dumps(arguments),
                    "size": result.result_size_bytes,
                    "cost": result.cost_usd,
                    "status": "ok" if result.ok else "error",
                    "error": result.error,
                    "started": result.started_at,
                    "completed": result.completed_at,
                },
            )

    def recent_calls(self, run_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            if run_id:
                rows = conn.execute(
                    text(
                        "SELECT tool_id, status, cost_usd, started_at, error "
                        "FROM agent_tool_calls WHERE run_id = :run "
                        "ORDER BY started_at DESC LIMIT :limit"
                    ),
                    {"run": run_id, "limit": limit},
                ).fetchall()
            else:
                rows = conn.execute(
                    text(
                        "SELECT tool_id, status, cost_usd, started_at, error "
                        "FROM agent_tool_calls ORDER BY started_at DESC LIMIT :limit"
                    ),
                    {"limit": limit},
                ).fetchall()
        return [
            {"tool_id": r[0], "status": r[1], "cost_usd": float(r[2] or 0), "started_at": r[3].isoformat(), "error": r[4]}
            for r in rows
        ]


# ------------------------------------------------------------- built-in tools


def register_readonly_tools(registry: ToolRegistry) -> None:
    """Pre-registered read-only tools (no arbitrary SQL/URL per OS-015)."""

    def get_market_price(args: dict[str, Any]) -> Any:
        with registry.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT observed_at, probability, best_bid, best_ask, midpoint, "
                    "data_quality_flags FROM market_observations "
                    "WHERE source_market_id = :m ORDER BY observed_at DESC LIMIT :limit"
                ),
                {"m": args["market_id"], "limit": args.get("limit", 5)},
            ).fetchall()
        return [
            {
                "observed_at": r[0].isoformat(),
                "probability": float(r[1]) if r[1] is not None else None,
                "best_bid": float(r[2]) if r[2] is not None else None,
                "best_ask": float(r[3]) if r[3] is not None else None,
                "midpoint": float(r[4]) if r[4] is not None else None,
                "flags": list(r[5] or []),
            }
            for r in rows
        ]

    def get_calculation(args: dict[str, Any]) -> Any:
        with registry.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT calculation_type, output, calculation_version, calculated_at "
                    "FROM calculation_records WHERE id = :id"
                ),
                {"id": args["calculation_id"]},
            ).fetchone()
        if row is None:
            return {"found": False}
        return {
            "found": True,
            "calculation_type": row[0],
            "output": row[1],
            "version": row[2],
            "calculated_at": row[3].isoformat(),
        }

    def search_raw_records(args: dict[str, Any]) -> Any:
        with registry.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT external_id, record_type, source_created_at "
                    "FROM raw_source_records "
                    "WHERE source_id = :sid AND payload::text ILIKE :term "
                    "ORDER BY source_created_at DESC NULLS LAST LIMIT :limit"
                ),
                {"sid": args["source_id"], "term": f"%{args['term']}%", "limit": args.get("limit", 10)},
            ).fetchall()
        return [
            {"external_id": r[0], "record_type": r[1], "source_created_at": r[2].isoformat() if r[2] else None}
            for r in rows
        ]

    def get_rule_changes(args: dict[str, Any]) -> Any:
        # Deterministic change candidates for a rule (computed on demand).
        from open_signal.derived.rule_changes import align_paragraphs

        with registry.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT payload FROM raw_source_records "
                    "WHERE source_id = :sid AND external_id = :ext"
                ),
                {"sid": args["source_id"], "ext": args["document_number"]},
            ).fetchone()
        if row is None or not isinstance(row[0], dict):
            return {"found": False}
        doc = row[0]
        new_text = doc.get("abstract") or doc.get("title") or ""
        d = align_paragraphs("", new_text)
        return {"found": True, "change_candidates": [c.as_dict() for c in d.substantive()]}

    registry.register(
        ToolSpec(
            id="get_market_price",
            name="Get Market Price",
            description="Read recent price observations for a source market.",
            permission="readonly",
            cost_class="low",
            parameters={
                "type": "object",
                "properties": {
                    "market_id": {"type": "string", "format": "uuid"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 5},
                },
                "required": ["market_id"],
                "additionalProperties": False,
            },
            handler=get_market_price,
        )
    )
    registry.register(
        ToolSpec(
            id="get_calculation",
            name="Get Calculation Record",
            description="Fetch a candidate-detection calculation record.",
            permission="readonly",
            cost_class="low",
            parameters={
                "type": "object",
                "properties": {"calculation_id": {"type": "string", "format": "uuid"}},
                "required": ["calculation_id"],
                "additionalProperties": False,
            },
            handler=get_calculation,
        )
    )
    registry.register(
        ToolSpec(
            id="search_raw_records",
            name="Search Raw Records",
            description="Search stored raw records of a source by term.",
            permission="readonly",
            cost_class="medium",
            parameters={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "format": "uuid"},
                    "term": {"type": "string", "minLength": 2, "maxLength": 200},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                },
                "required": ["source_id", "term"],
                "additionalProperties": False,
            },
            handler=search_raw_records,
        )
    )
    registry.register(
        ToolSpec(
            id="get_rule_changes",
            name="Get Rule Changes",
            description="Deterministic rule change candidates for a document.",
            permission="readonly",
            cost_class="medium",
            parameters={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "format": "uuid"},
                    "document_number": {"type": "string", "minLength": 1},
                },
                "required": ["source_id", "document_number"],
                "additionalProperties": False,
            },
            handler=get_rule_changes,
        )
    )

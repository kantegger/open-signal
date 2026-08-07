"""DeepSeek agent runtime (spec §151-155, OS-017).

- Charter loader: reads desk charters from infra/charters/*.md
- Agent Lineage: registers/uses agent_lineages
- structured output: forces + validates JSON output
- abstention: model may abstain instead of forcing a conclusion
- token/cost records: writes usage to investigation_runs
- retry policy: exponential backoff on 429/5xx
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from jsonschema import Draft7Validator, ValidationError

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
REASONER_MODEL = "deepseek-reasoner"

REPO_ROOT = Path(__file__).resolve().parents[3]
CHARTER_DIR = REPO_ROOT / "infra" / "charters"

# per-1K-token pricing (USD), approximate for DeepSeek
PRICING = {
    "deepseek-chat": {"input": 0.00027, "output": 0.00110},
    "deepseek-reasoner": {"input": 0.00055, "output": 0.00219},
}


class LlmError(Exception):
    pass


class StructuredOutputError(Exception):
    pass


class Abstention(Exception):
    """Raised when the agent explicitly abstains (spec §154.2)."""

    def __init__(self, reason: str, raw_output: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.raw_output = raw_output


@dataclass
class LlmUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def cost_usd(self, model: str) -> float:
        p = PRICING.get(model, PRICING[DEFAULT_MODEL])
        return round(self.prompt_tokens / 1000 * p["input"] + self.completion_tokens / 1000 * p["output"], 6)


@dataclass
class AgentResult:
    run_id: str
    structured: dict[str, Any]
    raw_output: str
    usage: LlmUsage
    model: str
    abstained: bool = False
    abstain_reason: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "structured": self.structured,
            "abstained": self.abstained,
            "abstain_reason": self.abstain_reason,
            "usage": {
                "prompt_tokens": self.usage.prompt_tokens,
                "completion_tokens": self.usage.completion_tokens,
                "total_tokens": self.usage.total_tokens,
                "cost_usd": self.usage.cost_usd(self.model),
            },
            "model": self.model,
            "tool_calls": self.tool_calls,
        }


class DeepSeekClient:
    """OpenAI-compatible chat client for DeepSeek with retry policy."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DEEPSEEK_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff_base: float = 2.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise LlmError("DEEPSEEK_API_KEY not set")
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> tuple[str, LlmUsage]:
        model = model or self.model
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        attempt = 0
        while True:
            try:
                resp = self._client.post("/chat/completions", json=payload)
                if resp.status_code in (429, 500, 502, 503, 504):
                    if attempt >= self.max_retries:
                        raise LlmError(f"LLM request failed after retries: HTTP {resp.status_code}")
                    attempt += 1
                    time.sleep(self.backoff_base**attempt)
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
            except httpx.HTTPError as exc:
                if attempt >= self.max_retries:
                    raise LlmError(f"LLM transport error: {exc}") from exc
                attempt += 1
                time.sleep(self.backoff_base**attempt)

        content = data["choices"][0]["message"]["content"]
        usage_raw = data.get("usage") or {}
        usage = LlmUsage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )
        return content, usage

    def close(self) -> None:
        self._client.close()


class AgentRuntime:
    """Runs one agent task: charter + context -> structured output."""

    def __init__(
        self,
        engine: Any,
        client: DeepSeekClient | None = None,
        charter_dir: Path | str | None = None,
    ) -> None:
        self.engine = engine
        self.client = client
        self.charter_dir = Path(charter_dir) if charter_dir else CHARTER_DIR

    # -------------------------------------------------------------- charters
    def load_charter(self, name: str) -> str:
        path = self.charter_dir / f"{name}.md"
        if not path.exists():
            raise FileNotFoundError(f"charter {name!r} not found in {self.charter_dir}")
        return path.read_text(encoding="utf-8")

    def list_charters(self) -> list[str]:
        return sorted(p.stem for p in self.charter_dir.glob("*.md"))

    # ------------------------------------------------------------------ runs
    def run(
        self,
        *,
        lineage_id: str,
        desk_id: str,
        section_id: str,
        capability_id: str,
        charter: str | None = None,
        context: dict[str, Any] | None = None,
        instructions: str | None = None,
        output_schema: dict[str, Any] | None = None,
        model: str | None = None,
        max_tokens: int = 2048,
        candidate_id: str | None = None,
    ) -> AgentResult:
        """Execute one agent run with structured output.

        Raises Abstention when the model abstains (verdict absent or
        abstain flag set). Token/cost are recorded on investigation_runs.
        """
        if self.client is None:
            raise LlmError("no LLM client configured")

        charter = charter or self.load_charter(f"{desk_id}-charter")
        system_prompt = _build_system_prompt(charter, output_schema)
        user_prompt = json.dumps(context or {}, ensure_ascii=False, default=str)
        if instructions:
            user_prompt = f"{user_prompt}\n\nInstructions: {instructions}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        from sqlalchemy import text

        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    INSERT INTO investigation_runs
                      (desk_id, section_id, capability_id, candidate_id,
                       agent_lineage_id, model_version, charter_version,
                       started_at, status)
                    VALUES
                      (:desk, :section, :capability, :candidate, :lineage,
                       :model, 'os-017', now(), 'running')
                    RETURNING id
                    """
                ),
                {
                    "desk": desk_id,
                    "section": section_id,
                    "capability": capability_id,
                    "candidate": candidate_id,
                    "lineage": lineage_id,
                    "model": model or DEFAULT_MODEL,
                },
            ).fetchone()
            run_id = str(row[0])

        try:
            content, usage = self.client.chat(
                messages, model=model, json_mode=output_schema is not None, max_tokens=max_tokens
            )
            structured = self._parse_structured(content, output_schema)

            abstained, reason = self._check_abstention(structured)
            status = "abstained" if abstained else "completed"
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE investigation_runs SET
                          completed_at = now(), status = :status,
                          total_input_tokens = :in_tokens,
                          total_output_tokens = :out_tokens,
                          total_tool_calls = 0,
                          estimated_cost_usd = :cost,
                          output_judgment = CAST(:output AS jsonb)
                        WHERE id = :id
                        """
                    ),
                    {
                        "status": status,
                        "in_tokens": usage.prompt_tokens,
                        "out_tokens": usage.completion_tokens,
                        "cost": usage.cost_usd(model or DEFAULT_MODEL),
                        "output": json.dumps(structured),
                        "id": run_id,
                    },
                )

            result = AgentResult(
                run_id=run_id,
                structured=structured,
                raw_output=content,
                usage=usage,
                model=model or DEFAULT_MODEL,
                abstained=abstained,
                abstain_reason=reason,
            )
            if abstained:
                raise Abstention(reason or "agent abstained", content)
            return result
        except Abstention:
            # expected path: run already recorded as 'abstained'
            raise
        except Exception as exc:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE investigation_runs SET completed_at = now(), "
                        "status = 'error', error_details = CAST(:err AS jsonb) "
                        "WHERE id = :id"
                    ),
                    {"err": json.dumps({"error": f"{type(exc).__name__}: {exc}"}), "id": run_id},
                )
            raise

    # ------------------------------------------------------------- structured
    @staticmethod
    def _parse_structured(content: str, schema: dict[str, Any] | None) -> dict[str, Any]:
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise StructuredOutputError(f"model returned non-JSON output: {exc}") from exc
        if not isinstance(data, dict):
            raise StructuredOutputError("model output is not a JSON object")
        if schema is not None:
            errors = list(Draft7Validator(schema).iter_errors(data))
            if errors:
                raise StructuredOutputError(f"structured output failed schema: {errors[0].message}")
        return data

    @staticmethod
    def _check_abstention(structured: dict[str, Any]) -> tuple[bool, str | None]:
        if structured.get("abstain") is True:
            return True, structured.get("abstain_reason") or structured.get("reason")
        if "verdict" in structured and structured.get("verdict") == "abstain":
            return True, structured.get("reason")
        return False, None


def _build_system_prompt(charter: str, output_schema: dict[str, Any] | None) -> str:
    prompt = f"你是 open-signal 的编辑 Agent。以下是你的 Charter：\n\n{charter}\n\n"
    if output_schema:
        prompt += (
            "必须只输出一个 JSON 对象，严格符合以下 JSON Schema，不得包含任何其他文本：\n"
            + json.dumps(output_schema, ensure_ascii=False)
            + "\n\n如证据不足，可输出 {\"verdict\": \"abstain\", \"reason\": \"...\"}。"
        )
    else:
        prompt += "如证据不足，请明确声明 abstain 而不是猜测。"
    return prompt

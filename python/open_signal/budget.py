"""Budget guard (spec §34, OS-032).

Enforces cost limits at three levels:
- per-run limit (one investigation run)
- daily desk limit (per desk per day)
- monthly global limit (whole system per month)

Soft limit (>=80%): degrades — warns and prefers cheaper models / fewer
runs. Hard limit (>=100%): deterministic-only mode — no new LLM runs
allowed until the window resets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

SOFT_LIMIT_RATIO = 0.8
HARD_LIMIT_RATIO = 1.0


@dataclass
class BudgetState:
    run_cost_usd: float
    desk_day_cost_usd: float
    month_cost_usd: float
    run_limit_usd: float
    desk_day_limit_usd: float
    month_limit_usd: float

    def soft_exceeded(self) -> bool:
        return self.desk_day_cost_usd >= SOFT_LIMIT_RATIO * self.desk_day_limit_usd

    def hard_exceeded(self) -> bool:
        return self.month_cost_usd >= HARD_LIMIT_RATIO * self.month_limit_usd or (
            self.desk_day_limit_usd > 0 and self.desk_day_cost_usd >= self.desk_day_limit_usd
        )

    def mode(self) -> str:
        if self.hard_exceeded():
            return "deterministic_only"
        if self.soft_exceeded():
            return "degraded"
        return "normal"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_cost_usd": self.run_cost_usd,
            "desk_day_cost_usd": self.desk_day_cost_usd,
            "month_cost_usd": self.month_cost_usd,
            "run_limit_usd": self.run_limit_usd,
            "desk_day_limit_usd": self.desk_day_limit_usd,
            "month_limit_usd": self.month_limit_usd,
            "soft_exceeded": self.soft_exceeded(),
            "hard_exceeded": self.hard_exceeded(),
            "mode": self.mode(),
        }


class BudgetGuard:
    """Reads actual spend from investigation_runs; enforces limits."""

    def __init__(
        self,
        engine: Any,
        *,
        run_limit_usd: float = 2.0,
        desk_day_limit_usd: float = 5.0,
        month_limit_usd: float = 100.0,
    ) -> None:
        self.engine = engine
        self.run_limit_usd = run_limit_usd
        self.desk_day_limit_usd = desk_day_limit_usd
        self.month_limit_usd = month_limit_usd

    # ------------------------------------------------------------------ state
    def state(self, desk_id: str | None = None) -> BudgetState:
        now = datetime.now(timezone.utc)
        day_start = (now - timedelta(hours=now.hour, minutes=now.minute, seconds=now.second)).replace(tzinfo=timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        with self.engine.connect() as conn:
            run = conn.execute(
                text(
                    "SELECT coalesce(max(estimated_cost_usd), 0) FROM investigation_runs "
                    "WHERE status = 'running' AND started_at > now() - interval '1 hour'"
                )
            ).scalar_one()
            desk_day = conn.execute(
                text(
                    "SELECT coalesce(sum(estimated_cost_usd), 0) FROM investigation_runs "
                    "WHERE desk_id = :desk AND started_at >= :day"
                ),
                {"desk": desk_id, "day": day_start},
            ).scalar_one()
            month = conn.execute(
                text(
                    "SELECT coalesce(sum(estimated_cost_usd), 0) FROM investigation_runs "
                    "WHERE started_at >= :month"
                ),
                {"month": month_start},
            ).scalar_one()

        return BudgetState(
            run_cost_usd=float(run),
            desk_day_cost_usd=float(desk_day),
            month_cost_usd=float(month),
            run_limit_usd=self.run_limit_usd,
            desk_day_limit_usd=self.desk_day_limit_usd,
            month_limit_usd=self.month_limit_usd,
        )

    # ------------------------------------------------------------------ gates
    def allow_llm_run(self, desk_id: str) -> tuple[bool, str, BudgetState]:
        """Whether a new LLM run may start; hard limit blocks LLM entirely."""
        state = self.state(desk_id)
        if state.hard_exceeded():
            return False, "hard limit: deterministic-only mode", state
        if state.soft_exceeded():
            return True, "soft limit: degrade (cheaper model / fewer runs)", state
        return True, "ok", state

    def record_cost(self, run_id: str, cost_usd: float) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE investigation_runs SET estimated_cost_usd = :cost WHERE id = :id"
                ),
                {"cost": cost_usd, "id": run_id},
            )

# Structured trace writer — see spec/spec.md §8 for JSONL schema
import json
from datetime import datetime, timezone
from pathlib import Path

from langfuse import observe

from src.models import PipelineState

TRACES_DIR = Path(__file__).parent.parent.parent / "traces"


@observe(name="log_structured_trace", as_type="tool")
def log_structured_trace(state: PipelineState) -> None:
    """Append one JSONL entry for this run to traces/YYYY-MM-DD.jsonl."""
    TRACES_DIR.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = TRACES_DIR / f"{today}.jsonl"

    entry = {
        "run_id": state.run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pr_url": state.pr_url,
        "risk_level": state.classification.risk_level if state.classification else None,
        "findings_count": len(state.findings.findings) if state.findings else 0,
        "verdict": state.findings.verdict if state.findings else None,
        "human_approved": state.human_approved,
        "total_cost_usd": state.total_cost_usd,
        "models_used": [state.classification.model_to_use] if state.classification else [],
        "error": state.error,
        "langfuse_trace_url": None,  # populated after flush
        "degraded": state.degraded,
        "agents_failed": state.agents_failed,
    }

    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def _ensure_dir(path: str | Path) -> Path:
    d = Path(path)
    d.mkdir(parents=True, exist_ok=True)
    return d


def kill_switch_path(control_dir: str | Path = "control") -> Path:
    return _ensure_dir(control_dir) / "kill_switch.flag"


def set_kill_switch(control_dir: str | Path = "control", reason: str = "manual") -> Path:
    path = kill_switch_path(control_dir)
    content = f"ON\nreason={reason}\ntimestamp={datetime.utcnow().isoformat()}Z\n"
    path.write_text(content, encoding="utf-8")
    return path


def clear_kill_switch(control_dir: str | Path = "control") -> bool:
    path = kill_switch_path(control_dir)
    if path.exists():
        path.unlink()
        return True
    return False


def is_kill_switch_active(control_dir: str | Path = "control") -> bool:
    return kill_switch_path(control_dir).exists()


def create_incident_note(
    *,
    title: str,
    severity: str,
    details: str,
    actions: str = "",
    output_dir: str | Path = "reports/incidents",
) -> Path:
    directory = _ensure_dir(output_dir)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"incident_{ts}.md"
    body = [
        f"# Incident: {title}",
        "",
        f"- Severity: {severity.upper()}",
        f"- Timestamp (UTC): {datetime.utcnow().isoformat()}Z",
        "",
        "## Details",
        details,
        "",
        "## Actions",
        actions or "TBD",
        "",
    ]
    path = directory / filename
    path.write_text("\n".join(body), encoding="utf-8")
    return path


def build_notify_template(kind: str, context: str = "") -> str:
    templates = {
        "broker_outage": (
            "ALERT: Broker connectivity degraded.\n"
            "Action: Enable kill switch, pause new entries, monitor reconciliation."
        ),
        "data_gap": (
            "ALERT: Market/alternative data gap detected.\n"
            "Action: Pause signal generation, trigger backfill, verify feed integrity."
        ),
        "alerts_down": (
            "ALERT: Notification delivery failure.\n"
            "Action: Switch to fallback channel, review Telegram/API tokens and rate limits."
        ),
    }
    base = templates.get(kind, "ALERT: Manual incident notification.")
    if context.strip():
        return f"{base}\nContext: {context.strip()}"
    return base

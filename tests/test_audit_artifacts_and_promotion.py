from __future__ import annotations

import json

from trading_bot.monitoring import promotion_gate
from trading_bot.monitoring.audit_artifacts import write_promotion_bundle, write_weekly_audit_artifact
from trading_bot.monitoring.performance_audit import AuditThresholds


def test_write_weekly_audit_artifact(tmp_path):
    payload = {"ready_for_live": False, "metrics": {"sharpe_ratio": 0.1}}
    out = write_weekly_audit_artifact(payload, output_dir=tmp_path, prefix="weekly_audit")
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["metrics"]["sharpe_ratio"] == 0.1


def test_write_promotion_bundle(tmp_path):
    bundle = write_promotion_bundle(
        preflight={"status": "ok"},
        weekly_audit={"ready_for_live": False},
        summary={"ready_for_live": False},
        output_dir=tmp_path,
    )
    assert bundle.exists()
    assert (bundle / "preflight.json").exists()
    assert (bundle / "weekly_audit.json").exists()
    assert (bundle / "summary.json").exists()


def test_run_promotion_gate_uses_checks(monkeypatch, tmp_path):
    monkeypatch.setattr(promotion_gate, "health_status", lambda **kwargs: {"status": "ok"})
    monkeypatch.setattr(
        promotion_gate,
        "run_weekly_audit",
        lambda *args, **kwargs: {"ready_for_live": True, "gates": {"sharpe_ratio": {"passed": True}}},
    )

    result = promotion_gate.run_promotion_gate(
        engine=object(),
        weeks=4,
        thresholds=AuditThresholds(),
        include_broker=True,
        fail_on_broker=True,
        write_bundle=True,
        output_dir=str(tmp_path),
    )

    assert result["ready_for_live"] is True
    assert result["bundle_path"] is not None

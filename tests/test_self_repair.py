import json
import logging

from omega.core.self_repair import RepairReport, SelfRepairLoop


def test_repair_report_defaults():
    r = RepairReport()
    assert r.healthy is True
    assert r.errors_found == 0
    assert r.repairs_attempted == 0
    assert r.repairs_succeeded == 0


def test_parse_errors_finds_critical_lines(tmp_path):
    log_file = tmp_path / "omega.log"
    log_file.write_text(
        "2026-03-29 01:00:00 INFO  Starting\n"
        "2026-03-29 01:00:01 ERROR Failed to connect to database: timeout\n"
        "2026-03-29 01:00:02 INFO  Retrying\n"
        "2026-03-29 01:00:03 CRITICAL Signal import failed: momentum_factor\n"
    )
    loop = SelfRepairLoop(skip_db=True, skip_signals=True)
    errors = loop._parse_log_errors(str(log_file), last_n_lines=100)
    assert len(errors) == 2
    assert any("database" in e.message.lower() for e in errors)
    assert any("signal" in e.message.lower() for e in errors)


def test_parse_errors_empty_log(tmp_path):
    log_file = tmp_path / "empty.log"
    log_file.write_text("")
    loop = SelfRepairLoop(skip_db=True, skip_signals=True)
    errors = loop._parse_log_errors(str(log_file))
    assert errors == []


def test_parse_errors_missing_log():
    loop = SelfRepairLoop(skip_db=True, skip_signals=True)
    errors = loop._parse_log_errors("/nonexistent/path.log")
    assert errors == []


def test_check_and_repair_returns_report():
    loop = SelfRepairLoop(skip_db=True, skip_signals=True)
    report = loop.check_and_repair()
    assert isinstance(report, RepairReport)
    assert isinstance(report.healthy, bool)
    assert isinstance(report.errors_found, int)


def test_notification_uses_logger(caplog):
    loop = SelfRepairLoop(skip_db=True, skip_signals=True)
    report = RepairReport(
        healthy=False,
        errors_found=3,
        repairs_attempted=2,
        repairs_succeeded=1,
        details=["DB timeout", "Signal import failed"],
    )
    with caplog.at_level(logging.CRITICAL, logger="omega.core.self_repair"):
        loop._notify(report)
    assert any(
        "errors_found" in rec.message or "unhealthy" in rec.message.lower()
        for rec in caplog.records
    )


def test_to_dict_serializable():
    report = RepairReport(
        healthy=False,
        errors_found=2,
        repairs_attempted=1,
        repairs_succeeded=1,
        details=["detail1"],
    )
    d = report.to_dict()
    assert json.dumps(d)
    assert d["healthy"] is False
    assert d["errors_found"] == 2

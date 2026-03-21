"""Unit tests for ChallengeRegistry."""
import pytest
from omega.core.challenge_registry import (
    ChallengeRegistry, Challenge, ChallengeSeverity, ChallengeStatus,
)


class TestChallengeRegistry:
    def setup_method(self):
        self.reg = ChallengeRegistry(db_path=":memory:")

    def test_add_and_get(self):
        cid = self.reg.add(
            target_subsystem="orchestrator",
            severity=ChallengeSeverity.HIGH,
            description="Test challenge",
            evidence="Some evidence",
        )
        ch = self.reg.get(cid)
        assert ch is not None
        assert ch.description == "Test challenge"
        assert ch.status == ChallengeStatus.OPEN
        assert ch.severity == ChallengeSeverity.HIGH

    def test_update_status_resolved(self):
        cid = self.reg.add("memory", ChallengeSeverity.MEDIUM, "Memory test", "Evidence")
        self.reg.update_status(cid, ChallengeStatus.RESOLVED, resolution_notes="Fixed it")
        ch = self.reg.get(cid)
        assert ch.status == ChallengeStatus.RESOLVED
        assert ch.resolution_notes == "Fixed it"

    def test_update_status_wontfix(self):
        cid = self.reg.add("sys", ChallengeSeverity.LOW, "Low priority", "E")
        self.reg.update_status(cid, ChallengeStatus.WONTFIX)
        assert self.reg.get(cid).status == ChallengeStatus.WONTFIX

    def test_open_challenges_excludes_resolved(self):
        self.reg.add("sys", ChallengeSeverity.CRITICAL, "Critical issue", "E")
        self.reg.add("sys", ChallengeSeverity.LOW, "Low issue", "E")
        cid3 = self.reg.add("sys", ChallengeSeverity.HIGH, "High issue", "E")
        self.reg.update_status(cid3, ChallengeStatus.WONTFIX)
        open_chs = self.reg.open_challenges()
        assert len(open_chs) == 2

    def test_open_challenges_filter_by_severity(self):
        self.reg.add("sys", ChallengeSeverity.CRITICAL, "C", "E")
        self.reg.add("sys", ChallengeSeverity.HIGH, "H", "E")
        self.reg.add("sys", ChallengeSeverity.MEDIUM, "M", "E")
        critical = self.reg.open_challenges(severity=ChallengeSeverity.CRITICAL)
        assert len(critical) == 1
        assert critical[0].severity == ChallengeSeverity.CRITICAL

    def test_all_challenges_subsystem_filter(self):
        self.reg.add("orchestrator.routing", ChallengeSeverity.HIGH, "A", "E")
        self.reg.add("memory.episodic", ChallengeSeverity.MEDIUM, "B", "E")
        self.reg.add("orchestrator.convergence", ChallengeSeverity.LOW, "C", "E")
        orch = self.reg.all_challenges(subsystem="orchestrator")
        assert len(orch) == 2

    def test_resolution_rate_zero_when_all_open(self):
        self.reg.add("sys", ChallengeSeverity.HIGH, "A", "E")
        self.reg.add("sys", ChallengeSeverity.HIGH, "B", "E")
        assert self.reg.resolution_rate() == 0.0

    def test_resolution_rate_full_when_all_resolved(self):
        cid1 = self.reg.add("sys", ChallengeSeverity.HIGH, "A", "E")
        cid2 = self.reg.add("sys", ChallengeSeverity.HIGH, "B", "E")
        self.reg.update_status(cid1, ChallengeStatus.RESOLVED)
        self.reg.update_status(cid2, ChallengeStatus.WONTFIX)
        assert self.reg.resolution_rate() == pytest.approx(1.0)

    def test_resolution_rate_partial(self):
        cid1 = self.reg.add("sys", ChallengeSeverity.HIGH, "A", "E")
        self.reg.add("sys", ChallengeSeverity.HIGH, "B", "E")
        self.reg.update_status(cid1, ChallengeStatus.RESOLVED)
        assert self.reg.resolution_rate() == pytest.approx(0.5)

    def test_resolution_rate_one_when_empty(self):
        assert self.reg.resolution_rate() == 1.0

    def test_has_blocking_challenges_true_when_critical_open(self):
        self.reg.add("sys", ChallengeSeverity.CRITICAL, "Blocker", "E")
        assert self.reg.has_blocking_challenges() is True

    def test_has_blocking_challenges_false_when_critical_resolved(self):
        cid = self.reg.add("sys", ChallengeSeverity.CRITICAL, "Blocker", "E")
        self.reg.update_status(cid, ChallengeStatus.RESOLVED)
        assert self.reg.has_blocking_challenges() is False

    def test_has_blocking_challenges_false_when_only_high(self):
        self.reg.add("sys", ChallengeSeverity.HIGH, "High but not critical", "E")
        assert self.reg.has_blocking_challenges() is False

    def test_seed_challenges_count(self):
        inserted = self.reg.seed_initial_challenges()
        assert inserted >= 16
        all_chs = self.reg.all_challenges()
        assert len(all_chs) >= 16

    def test_seed_covers_multiple_subsystems(self):
        self.reg.seed_initial_challenges()
        subsystems = {c.target_subsystem for c in self.reg.all_challenges()}
        assert len(subsystems) >= 4

    def test_seed_has_critical_challenges(self):
        self.reg.seed_initial_challenges()
        severities = {c.severity for c in self.reg.all_challenges()}
        assert ChallengeSeverity.CRITICAL in severities

    def test_seed_is_idempotent(self):
        self.reg.seed_initial_challenges()
        count1 = len(self.reg.all_challenges())
        self.reg.seed_initial_challenges()
        assert len(self.reg.all_challenges()) == count1

    def test_seed_covers_planned_architecture(self):
        self.reg.seed_initial_challenges()
        all_chs = self.reg.all_challenges()
        descriptions = " ".join(c.description for c in all_chs).lower()
        # Challenges about planned subsystems must be present
        assert "ewc" in descriptions or "elastic weight" in descriptions.lower()
        assert "nash" in descriptions
        assert "bocpd" in descriptions or "changepoint" in descriptions

    def test_get_returns_none_for_missing(self):
        assert self.reg.get("nonexistent-id") is None

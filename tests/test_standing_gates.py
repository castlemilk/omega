"""Tests for the standing-baseline gates (omega/eval/standing_gates.py).

These replace the v49 sibling-comparison gates as the live path. The v49 module
and its tests stay green on purpose — this suite asserts the behaviours that
module could not deliver:

* family matching against the REAL cell names in `data/`;
* the journal's exact floors (crisis +$599 / trend +$2,997 / recent +$30);
* NO_BASELINE instead of a silent skip;
* not_evaluated instead of a vacuous pass for absent input blocks;
* NO_OP instead of a green board for a deterministic replay;
* an ERROR file instead of a swallowed exception;
* and a regression guard that the 18 identical-summary shapes no longer read
  as a bare PASS.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from omega.eval.standing_gates import (
    ADVISORY_BELOW_CAMPAIGN_MEAN,
    DEFAULT_BASELINE_PATH,
    DEFAULT_PER_CELL_FLOOR_USD,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    VERDICT_ERROR,
    VERDICT_FAIL,
    VERDICT_NO_BASELINE,
    VERDICT_NO_OP,
    VERDICT_PASS,
    check_standing_gates,
    error_payload,
    load_baseline_config,
    resolve_family,
    trades_fingerprint,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def config() -> dict:
    return load_baseline_config()


@pytest.fixture(scope="module")
def real_cell_labels() -> list[str]:
    """Every cell label that actually exists in `data/`, from its results file.

    Read from disk rather than hard-coded so the family patterns are tested
    against the corpus as it is, not as it was when this test was written.
    """
    return sorted(p.name[: -len("_results.json")] for p in DATA_DIR.glob("*_results.json"))


def _results(
    tmp_path: Path,
    label: str,
    *,
    pnl: float | None = 1000.0,
    trades: int | None = 42,
    snapshot: str | None = None,
    frozen_cache: bool = False,
    max_dd: float | None = None,
    omit_trades_block: bool = False,
    omit_observability: bool = True,
) -> Path:
    """Write a results.json shaped like the real ones run_training.py emits."""
    trades_block: dict = {}
    if not omit_trades_block:
        if pnl is not None:
            trades_block["total_pnl_usd"] = pnl
        if trades is not None:
            trades_block["total_closed"] = trades
        trades_block["win_rate"] = 0.44
    payload: dict = {
        "version": label,
        "provenance": {
            "cell_label": label,
            "git_sha": "deadbeef" * 5,
            "git_dirty": False,
            "features": ["crisis_skew_enabled", "universe_selective_enabled"],
            "snapshot": snapshot,
            "frozen_cache": frozen_cache,
        },
        "trades": trades_block,
    }
    if not omit_observability:
        payload["observability"] = {"max_drawdown_usd": max_dd}
    p = tmp_path / f"{label}_results.json"
    p.write_text(json.dumps(payload))
    return p


def _trades(tmp_path: Path, label: str, rows: list[dict], *, timestamp: str = "2026-01-01T00:00:00Z") -> Path:
    p = tmp_path / f"{label}_trades.csv"
    cols = ["cycle", "timestamp", "symbol", "side", "pnl", "regime"]
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for i, row in enumerate(rows):
            w.writerow({"cycle": i, "timestamp": timestamp, **row})
    return p


_TWO_TRADES = [
    {"symbol": "ETH", "side": "long", "pnl": 120.5, "regime": "crisis"},
    {"symbol": "SOL", "side": "short", "pnl": -20.5, "regime": "normal"},
]


# ---------------------------------------------------------------------------
# The standing baseline itself
# ---------------------------------------------------------------------------


def test_standing_baseline_carries_the_journal_campaign_means(config: dict):
    """crisis +$599 / trend +$2,997 / recent +$30 — training_log/V271.md:6.

    These are the CAMPAIGN MEANS. They are kept, cited and reported — but they
    are not the per-cell bar (see the next test for why they cannot be).
    """
    assert config["families"]["crisis"]["campaign_mean_usd"] == 599.0
    assert config["families"]["trend"]["campaign_mean_usd"] == 2997.0
    assert config["families"]["recent"]["campaign_mean_usd"] == 30.0


def test_per_cell_floor_is_zero_for_every_family(config: dict):
    """The per-cell bar is $0: a cell that loses money fails, nothing else does.

    The campaign means are means of skewed walk-forward distributions (crisis's
    median is +$65 against its +$599 mean), so applying one as a per-cell bar
    would fail the majority of legitimate crisis cells.
    """
    for fam in ("crisis", "trend", "recent"):
        assert config["families"][fam]["per_cell_floor_usd"] == 0.0


def test_config_round_trips_both_numbers_for_every_family(config: dict):
    """Config shape: every family carries both numbers, in their distinct roles."""
    for fam in ("crisis", "trend", "recent"):
        spec = config["families"][fam]
        assert set(spec) >= {"per_cell_floor_usd", "campaign_mean_usd", "journal_cite", "n_windows"}
        assert isinstance(spec["per_cell_floor_usd"], (int, float))
        assert isinstance(spec["campaign_mean_usd"], (int, float))
        assert spec["campaign_mean_usd"] > spec["per_cell_floor_usd"]
    # And the notes say, in words, why the mean is not the bar.
    joined = " ".join(config["notes"])
    assert "NOT a per-cell bar" in joined
    assert "MEDIAN" in joined or "median" in joined


def test_standing_baseline_carries_provenance(config: dict):
    assert "V271.md" in config["source"]
    assert config["updated"]
    assert config["notes"]
    for fam in ("crisis", "trend", "recent"):
        assert config["families"][fam]["journal_cite"]


def test_standing_baseline_file_is_committed():
    assert DEFAULT_BASELINE_PATH.exists()


# ---------------------------------------------------------------------------
# Family matching against the real corpus
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        # Bare-token cells — the dominant shape.
        ("v199_crisis", "crisis"),
        ("v199_trend", "trend"),
        ("v199_recent", "recent"),
        ("bt_v132a_crisis", "crisis"),
        ("bt500_v137a_trend", "trend"),
        ("v229_grid_off_recent_r2", "recent"),
        ("v203_v199_crisis_s42", "crisis"),
        ("v213loc2_recent_r1", "recent"),
        ("v231smoke_crisis_r1", "crisis"),
        # Snapshot-named cells.
        ("v233_smoke_pre_demean_w0.2_snap_crisis_2024aug", "crisis"),
        ("v232_crisis_snap_crisis_2020q1_off_crisis_r2", "crisis"),
        # No family token at all.
        ("v48", None),
        ("v45_full", None),
        ("brain_eval", None),
    ],
)
def test_family_matching_on_real_cell_names(config: dict, label: str, expected: str | None):
    family, _source, _notes = resolve_family(label, None, config)
    assert family == expected


@pytest.fixture(scope="module")
def real_snapshot_names() -> list[str]:
    """Every snapshot basename recorded in a real results file's provenance.

    Two of the family patterns (`snap_crisis_`, `snap_trending_`) exist to match
    the SNAPSHOT rather than the label — `snap_trending_2023q4` never appears in
    a cell name, only in `provenance.snapshot` of 11 results files.
    """
    names: set[str] = set()
    for p in DATA_DIR.glob("*_results.json"):
        try:
            snap = (json.loads(p.read_text()).get("provenance") or {}).get("snapshot")
        except Exception:
            continue
        if snap:
            names.add(Path(str(snap)).name)
    return sorted(names)


def test_every_family_pattern_matches_at_least_one_real_cell(
    config: dict, real_cell_labels: list[str], real_snapshot_names: list[str]
):
    """A pattern that matches nothing in `data/` is a pattern nobody verified."""
    import re

    corpus = real_cell_labels + real_snapshot_names
    if not real_snapshot_names:
        # Two of the patterns (snap_crisis_, snap_trending_) match only
        # provenance.snapshot, which lives in walk-forward results files. Those are
        # gitignored run artifacts and absent from a fresh clone, so with no
        # snapshots present this cannot tell an unverified pattern from a data dir
        # that simply has not had a grid run in it. Failing here fails everywhere
        # except one developer's machine, which is not a check.
        pytest.skip("no provenance.snapshot in data/ (gitignored walk-forward artifacts)")
    for entry in config["family_patterns"]:
        hits = [c for c in corpus if re.search(entry["pattern"], c)]
        assert hits, f"family_patterns entry {entry['pattern']!r} matches no real cell in data/"
        assert entry["why"], "every pattern must document why it exists"


def test_no_real_cell_label_matches_two_families(config: dict, real_cell_labels: list[str]):
    """Family resolution must be unambiguous over the corpus as it stands."""
    import re

    fams = {"crisis", "trend", "recent"}
    for label in real_cell_labels:
        matched = {
            e["family"]
            for e in config["family_patterns"]
            if re.search(e["pattern"], label)
        }
        assert len(matched & fams) <= 1, f"{label} matched {matched}"


def test_walk_forward_snapshot_resolves_via_the_manifest(tmp_path: Path, config: dict):
    """`v252_replay_2023-09-12` carries a DATE, not a regime — the manifest decides.

    training_log/V253_MATIC_POL_REMAP.md:45-47 records the mapping:
    snap_wf_20240310 = crisis, snap_wf_20230912 = trend, snap_wf_20250305 = recent.
    """
    cases = {
        "snap_wf_20240310": "crisis",
        "snap_wf_20230912": "trend",
        "snap_wf_20250305": "recent",
    }
    for snap, expected in cases.items():
        results = json.loads(
            _results(
                tmp_path,
                f"v252_replay_{snap}",
                snapshot=f"data/snapshots/walk_forward/{snap}.json",
            ).read_text()
        )
        family, source, _ = resolve_family(f"v252_replay_{snap}", results, config)
        assert (family, source) == (expected, "manifest")


def test_snapshot_beats_label_and_records_the_conflict(tmp_path: Path, config: dict):
    results = json.loads(
        _results(
            tmp_path,
            "v300_trend_r1",
            snapshot="data/snapshots/snap_crisis_2022h1.json",
        ).read_text()
    )
    family, source, notes = resolve_family("v300_trend_r1", results, config)
    assert family == "crisis"
    assert source == "snapshot_pattern"
    assert any("family conflict" in n for n in notes)


# ---------------------------------------------------------------------------
# The per-cell floor — the bar
# ---------------------------------------------------------------------------


def test_exactly_zero_pnl_passes(tmp_path: Path, config: dict):
    """The bar is `>= 0`, so a cell that broke exactly even is not a failure."""
    res = _results(tmp_path, "v300_crisis_r1", pnl=0.0, trades=42)
    out = check_standing_gates(res, _trades(tmp_path, "v300_crisis_r1", _TWO_TRADES), config)
    assert out.verdict == VERDICT_PASS
    assert out.family == "crisis"
    g = out.gates["cell_pnl_floor"]
    assert g.status == STATUS_PASS
    assert g.detail["floor_usd"] == 0.0
    assert g.detail["margin_usd"] == 0.0


def test_one_cent_below_zero_fails(tmp_path: Path, config: dict):
    """-$0.01 is a cell that lost money — the one unambiguous per-cell failure."""
    res = _results(tmp_path, "v300_crisis_r1", pnl=-0.01, trades=42)
    out = check_standing_gates(res, _trades(tmp_path, "v300_crisis_r1", _TWO_TRADES), config)
    assert out.verdict == VERDICT_FAIL
    assert out.passed is False
    g = out.gates["cell_pnl_floor"]
    assert g.status == STATUS_FAIL
    assert g.detail["margin_usd"] == pytest.approx(-0.01)
    assert any("cell_pnl_floor[crisis]" in f for f in out.failures)
    # A failing cell carries no advisory: the failure is the message.
    assert "advisory" not in g.detail


def test_a_losing_cell_fails_in_every_family(tmp_path: Path, config: dict):
    for fam in ("crisis", "trend", "recent"):
        res = _results(tmp_path, f"v300_{fam}_r1", pnl=-1.0, trades=42)
        out = check_standing_gates(res, _trades(tmp_path, f"v300_{fam}_r1", _TWO_TRADES), config)
        assert out.verdict == VERDICT_FAIL, fam
        assert out.gates["cell_pnl_floor"].detail["floor_usd"] == 0.0, fam


def test_the_campaign_mean_is_never_a_bar(tmp_path: Path, config: dict):
    """The revision, in one test.

    Crisis's median walk-forward window is +$65 — an order of magnitude under
    its +$599 campaign mean. Under a mean-as-floor rule that legitimate cell
    fails; under the per-cell floor it passes, with the shortfall stated.
    """
    res = _results(tmp_path, "v300_crisis_r1", pnl=65.0, trades=42)
    out = check_standing_gates(res, _trades(tmp_path, "v300_crisis_r1", _TWO_TRADES), config)
    assert out.verdict == VERDICT_PASS
    assert out.gates["cell_pnl_floor"].status == STATUS_PASS
    assert out.failures == []


def test_per_family_floor_override_is_honoured(tmp_path: Path, config: dict):
    """A family may raise its own bar; the override, not the default, applies."""
    cfg = json.loads(json.dumps(config))
    cfg["families"]["crisis"]["per_cell_floor_usd"] = 250.0
    res = _results(tmp_path, "v300_crisis_r1", pnl=100.0, trades=42)
    out = check_standing_gates(res, _trades(tmp_path, "v300_crisis_r1", _TWO_TRADES), cfg)
    assert out.verdict == VERDICT_FAIL
    assert out.gates["cell_pnl_floor"].detail["floor_usd"] == 250.0
    assert out.standing_baseline_used["per_cell_floor_usd"] == 250.0
    # Other families keep theirs.
    res_t = _results(tmp_path, "v300_trend_r1", pnl=100.0, trades=42)
    out_t = check_standing_gates(res_t, _trades(tmp_path, "v300_trend_r1", _TWO_TRADES), cfg)
    assert out_t.verdict == VERDICT_PASS
    assert out_t.gates["cell_pnl_floor"].detail["floor_usd"] == 0.0


def test_absent_per_cell_floor_defaults_to_zero(tmp_path: Path, config: dict):
    cfg = json.loads(json.dumps(config))
    del cfg["families"]["crisis"]["per_cell_floor_usd"]
    res = _results(tmp_path, "v300_crisis_r1", pnl=-5.0, trades=42)
    out = check_standing_gates(res, _trades(tmp_path, "v300_crisis_r1", _TWO_TRADES), cfg)
    assert out.gates["cell_pnl_floor"].detail["floor_usd"] == DEFAULT_PER_CELL_FLOOR_USD == 0.0
    assert out.verdict == VERDICT_FAIL


# ---------------------------------------------------------------------------
# The campaign mean — informational only
# ---------------------------------------------------------------------------


def test_positive_below_the_mean_passes_with_an_advisory(tmp_path: Path, config: dict):
    """+$412.55 in crisis: over the floor, under the +$599 mean. PASS + advisory."""
    res = _results(tmp_path, "v300_crisis_r1", pnl=412.55, trades=42)
    out_path = tmp_path / "v300_crisis_r1_gate_result.json"
    out = check_standing_gates(
        res, _trades(tmp_path, "v300_crisis_r1", _TWO_TRADES), config, out_path=out_path
    )
    assert out.verdict == VERDICT_PASS
    assert out.passed is True
    # The advisory survives the round-trip to disk — this is the shape the Go
    # handler passes through and the Foreman board renders as an amber note.
    on_disk = json.loads(out_path.read_text())
    assert on_disk["verdict"] == VERDICT_PASS
    assert on_disk["passed"] is True
    assert on_disk["failures"] == []
    assert on_disk["gates"]["cell_pnl_floor"]["advisory"] == ADVISORY_BELOW_CAMPAIGN_MEAN
    assert on_disk["gates"]["cell_pnl_floor"]["campaign_mean_margin_usd"] == pytest.approx(-186.45)
    g = out.gates["cell_pnl_floor"]
    assert g.status == STATUS_PASS
    assert g.detail["advisory"] == ADVISORY_BELOW_CAMPAIGN_MEAN
    assert g.detail["campaign_mean_usd"] == 599.0
    assert g.detail["campaign_mean_margin_usd"] == pytest.approx(-186.45)
    # …and it stays out of `failures`, which is what the verdict is computed from.
    assert out.failures == []
    assert any(ADVISORY_BELOW_CAMPAIGN_MEAN in n for n in out.notes)


def test_above_the_mean_carries_no_advisory(tmp_path: Path, config: dict):
    res = _results(tmp_path, "v300_crisis_r1", pnl=700.0, trades=42)
    out = check_standing_gates(res, _trades(tmp_path, "v300_crisis_r1", _TWO_TRADES), config)
    assert out.verdict == VERDICT_PASS
    g = out.gates["cell_pnl_floor"]
    assert "advisory" not in g.detail
    # The mean is still reported — it is context, just not a bar.
    assert g.detail["campaign_mean_usd"] == 599.0
    assert g.detail["campaign_mean_margin_usd"] == pytest.approx(101.0)
    assert not any(ADVISORY_BELOW_CAMPAIGN_MEAN in n for n in out.notes)


def test_exactly_at_the_mean_carries_no_advisory(tmp_path: Path, config: dict):
    res = _results(tmp_path, "v300_recent_r1", pnl=30.0, trades=42)
    out = check_standing_gates(res, _trades(tmp_path, "v300_recent_r1", _TWO_TRADES), config)
    assert out.verdict == VERDICT_PASS
    assert "advisory" not in out.gates["cell_pnl_floor"].detail


def test_advisory_fires_per_family_with_its_own_mean(tmp_path: Path, config: dict):
    """$1,000 is above crisis's mean and below trend's — same number, different advice."""
    crisis = check_standing_gates(
        _results(tmp_path, "v300_crisis_r1", pnl=1000.0, trades=42),
        _trades(tmp_path, "v300_crisis_r1", _TWO_TRADES),
        config,
    )
    trend = check_standing_gates(
        _results(tmp_path, "v300_trend_r1", pnl=1000.0, trades=42),
        _trades(tmp_path, "v300_trend_r1", _TWO_TRADES),
        config,
    )
    assert "advisory" not in crisis.gates["cell_pnl_floor"].detail
    assert trend.gates["cell_pnl_floor"].detail["advisory"] == ADVISORY_BELOW_CAMPAIGN_MEAN
    assert trend.gates["cell_pnl_floor"].detail["campaign_mean_margin_usd"] == pytest.approx(-1997.0)
    assert trend.verdict == VERDICT_PASS


def test_trade_count_floor_still_bites(tmp_path: Path, config: dict):
    res = _results(tmp_path, "v300_crisis_r1", pnl=10_000.0, trades=19)
    out = check_standing_gates(res, _trades(tmp_path, "v300_crisis_r1", _TWO_TRADES), config)
    assert out.verdict == VERDICT_FAIL
    assert out.gates["trade_count_floor"].status == STATUS_FAIL
    assert out.gates["trade_count_floor"].detail == {"trades": 19, "floor": 20}


# ---------------------------------------------------------------------------
# NO_BASELINE
# ---------------------------------------------------------------------------


def test_unmatched_family_is_no_baseline_not_a_pass(tmp_path: Path, config: dict):
    res = _results(tmp_path, "v300_mystery_cell", pnl=1_000_000.0, trades=999)
    out = check_standing_gates(res, _trades(tmp_path, "v300_mystery_cell", _TWO_TRADES), config)
    assert out.verdict == VERDICT_NO_BASELINE
    assert out.passed is False
    assert out.family is None
    assert out.gates["cell_pnl_floor"].status == STATUS_NOT_EVALUATED


def test_no_baseline_still_writes_the_file(tmp_path: Path, config: dict):
    res = _results(tmp_path, "v300_mystery_cell", pnl=1.0, trades=42)
    out_path = tmp_path / "v300_mystery_cell_gate_result.json"
    check_standing_gates(
        res, _trades(tmp_path, "v300_mystery_cell", _TWO_TRADES), config, out_path=out_path
    )
    payload = json.loads(out_path.read_text())
    assert payload["verdict"] == VERDICT_NO_BASELINE
    assert payload["passed"] is False


def test_no_baseline_still_evaluates_the_other_gates(tmp_path: Path, config: dict):
    res = _results(tmp_path, "v300_mystery_cell", pnl=1.0, trades=3)
    out = check_standing_gates(res, _trades(tmp_path, "v300_mystery_cell", _TWO_TRADES), config)
    # A trade-count failure outranks NO_BASELINE: a real failure is never masked.
    assert out.verdict == VERDICT_FAIL
    assert out.gates["trade_count_floor"].status == STATUS_FAIL


# ---------------------------------------------------------------------------
# NOT_EVALUATED for absent blocks
# ---------------------------------------------------------------------------


def test_drawdown_is_not_evaluated_when_absent(tmp_path: Path, config: dict):
    """The v49 bug: max_drawdown defaulted to 0.0, so 0.0 <= 0.0 was forever green."""
    res = _results(tmp_path, "v300_crisis_r1", pnl=700.0, trades=42, omit_observability=True)
    out = check_standing_gates(res, _trades(tmp_path, "v300_crisis_r1", _TWO_TRADES), config)
    g = out.gates["drawdown_ceiling"]
    assert g.status == STATUS_NOT_EVALUATED
    assert "max_drawdown_usd" in g.detail["reason"]
    # not_evaluated is not a failure — the run still passes on its real gates.
    assert out.verdict == VERDICT_PASS


def test_drawdown_evaluated_when_present_and_ceiling_configured(tmp_path: Path, config: dict):
    res = _results(
        tmp_path, "v300_crisis_r1", pnl=700.0, trades=42, max_dd=250.0, omit_observability=False
    )
    cfg = {**config, "max_drawdown_ceiling_usd": 100.0}
    out = check_standing_gates(res, _trades(tmp_path, "v300_crisis_r1", _TWO_TRADES), cfg)
    assert out.gates["drawdown_ceiling"].status == STATUS_FAIL
    assert out.verdict == VERDICT_FAIL

    cfg_ok = {**config, "max_drawdown_ceiling_usd": 400.0}
    out_ok = check_standing_gates(res, _trades(tmp_path, "v300_crisis_r1", _TWO_TRADES), cfg_ok)
    assert out_ok.gates["drawdown_ceiling"].status == STATUS_PASS


def test_absent_trades_block_is_not_evaluated_never_pass(tmp_path: Path, config: dict):
    res = _results(tmp_path, "v300_crisis_r1", omit_trades_block=True)
    out = check_standing_gates(res, _trades(tmp_path, "v300_crisis_r1", _TWO_TRADES), config)
    for name in ("cell_pnl_floor", "trade_count_floor", "drawdown_ceiling"):
        assert out.gates[name].status == STATUS_NOT_EVALUATED, name


def test_no_gate_ever_reports_pass_from_an_absent_block(tmp_path: Path, config: dict):
    """The invariant, stated once: absent input => not_evaluated, never pass."""
    res = _results(tmp_path, "v300_mystery_cell", omit_trades_block=True)
    out = check_standing_gates(res, _trades(tmp_path, "v300_mystery_cell", _TWO_TRADES), config)
    assert all(c.status != STATUS_PASS for c in out.gates.values())
    assert out.passed is False


# ---------------------------------------------------------------------------
# NO_OP
# ---------------------------------------------------------------------------


def test_no_op_when_frozen_cache_reproduces_the_sibling(tmp_path: Path, config: dict):
    rows = _TWO_TRADES
    sib_res = _results(tmp_path, "v299_crisis_r1", pnl=700.0, trades=42, frozen_cache=True)
    sib_trades = _trades(tmp_path, "v299_crisis_r1", rows, timestamp="2026-01-01T00:00:00Z")
    cand_res = _results(tmp_path, "v300_crisis_r1", pnl=700.0, trades=42, frozen_cache=True)
    # Different wall-clock timestamps, identical content — the fingerprint drops
    # the timestamp column precisely so this still reads as a reproduction.
    cand_trades = _trades(tmp_path, "v300_crisis_r1", rows, timestamp="2026-08-18T09:00:00Z")

    out = check_standing_gates(
        cand_res,
        cand_trades,
        config,
        sibling_label="v299_crisis_r1",
        sibling_results=sib_res,
        sibling_trades_path=sib_trades,
    )
    assert out.verdict == VERDICT_NO_OP
    assert out.passed is False
    assert out.sibling_comparison["identical_trade_fingerprint"] is True
    assert out.sibling_comparison["status"] == "informational"
    assert any("NO_OP" in n for n in out.notes)


def test_not_a_no_op_when_the_cache_was_not_frozen(tmp_path: Path, config: dict):
    sib_res = _results(tmp_path, "v299_crisis_r1", pnl=700.0, trades=42)
    sib_trades = _trades(tmp_path, "v299_crisis_r1", _TWO_TRADES)
    cand_res = _results(tmp_path, "v300_crisis_r1", pnl=700.0, trades=42, frozen_cache=False)
    cand_trades = _trades(tmp_path, "v300_crisis_r1", _TWO_TRADES)
    out = check_standing_gates(
        cand_res, cand_trades, config,
        sibling_label="v299_crisis_r1", sibling_results=sib_res, sibling_trades_path=sib_trades,
    )
    assert out.verdict == VERDICT_PASS
    assert out.sibling_comparison["identical_numbers"] is True


def test_no_op_never_masks_a_real_failure(tmp_path: Path, config: dict):
    sib_res = _results(tmp_path, "v299_crisis_r1", pnl=-10.0, trades=42, frozen_cache=True)
    sib_trades = _trades(tmp_path, "v299_crisis_r1", _TWO_TRADES)
    cand_res = _results(tmp_path, "v300_crisis_r1", pnl=-10.0, trades=42, frozen_cache=True)
    cand_trades = _trades(tmp_path, "v300_crisis_r1", _TWO_TRADES)
    out = check_standing_gates(
        cand_res, cand_trades, config,
        sibling_label="v299_crisis_r1", sibling_results=sib_res, sibling_trades_path=sib_trades,
    )
    assert out.verdict == VERDICT_FAIL  # -$10 is a cell that lost money


def test_sibling_absent_is_fine_and_never_decides(tmp_path: Path, config: dict):
    res = _results(tmp_path, "v300_crisis_r1", pnl=700.0, trades=42, frozen_cache=True)
    out = check_standing_gates(res, _trades(tmp_path, "v300_crisis_r1", _TWO_TRADES), config)
    assert out.verdict == VERDICT_PASS
    assert out.sibling_comparison is None


def test_trades_fingerprint_ignores_timestamp_only(tmp_path: Path):
    a = _trades(tmp_path, "a", _TWO_TRADES, timestamp="2020-01-01T00:00:00Z")
    b = _trades(tmp_path, "b", _TWO_TRADES, timestamp="2026-08-18T09:00:00Z")
    c = _trades(
        tmp_path, "c",
        [{**_TWO_TRADES[0], "pnl": 120.6}, _TWO_TRADES[1]],
        timestamp="2020-01-01T00:00:00Z",
    )
    assert trades_fingerprint(a) == trades_fingerprint(b)
    assert trades_fingerprint(a) != trades_fingerprint(c)
    assert trades_fingerprint(tmp_path / "does_not_exist.csv") is None


# ---------------------------------------------------------------------------
# ERROR
# ---------------------------------------------------------------------------


def test_error_payload_writes_a_record(tmp_path: Path):
    out_path = tmp_path / "v300_crisis_r1_gate_result.json"
    payload = error_payload("v300_crisis_r1", ValueError("boom"), out_path=out_path)
    assert payload["verdict"] == VERDICT_ERROR
    assert payload["passed"] is False
    on_disk = json.loads(out_path.read_text())
    assert on_disk["error"] == "boom"
    assert on_disk["error_type"] == "ValueError"
    assert on_disk["failures"]


def test_gate_crash_is_recorded_not_swallowed(tmp_path: Path, config: dict):
    """A malformed results file must produce an ERROR file, not silence."""
    bad = tmp_path / "v300_crisis_r1_results.json"
    bad.write_text("{not json")
    out_path = tmp_path / "v300_crisis_r1_gate_result.json"
    try:
        check_standing_gates(bad, None, config, out_path=out_path)
        raise AssertionError("expected a parse error")
    except AssertionError:
        raise
    except Exception as exc:
        error_payload("v300_crisis_r1", exc, out_path=out_path)
    assert json.loads(out_path.read_text())["verdict"] == VERDICT_ERROR


# ---------------------------------------------------------------------------
# Emitted shape
# ---------------------------------------------------------------------------


def test_emitted_file_shape(tmp_path: Path, config: dict):
    res = _results(
        tmp_path, "v300_crisis_r1", pnl=700.0, trades=42,
        snapshot="data/snapshots/snap_crisis_2022h1.json", frozen_cache=True,
    )
    out_path = tmp_path / "v300_crisis_r1_gate_result.json"
    check_standing_gates(res, _trades(tmp_path, "v300_crisis_r1", _TWO_TRADES), config, out_path=out_path)
    payload = json.loads(out_path.read_text())

    assert payload["version"] == "v300_crisis_r1"
    assert payload["family"] == "crisis"
    assert payload["verdict"] == VERDICT_PASS
    assert set(payload["gates"]) == {"cell_pnl_floor", "trade_count_floor", "drawdown_ceiling"}
    for gate in payload["gates"].values():
        assert gate["status"] in {STATUS_PASS, STATUS_FAIL, STATUS_NOT_EVALUATED}
    # Both numbers are recorded, in their distinct roles.
    assert payload["standing_baseline_used"]["per_cell_floor_usd"] == 0.0
    assert payload["standing_baseline_used"]["campaign_mean_usd"] == 599.0
    assert "V271.md" in payload["standing_baseline_used"]["source"]
    assert payload["provenance"]["git_sha"]
    assert payload["provenance"]["features"] == [
        "crisis_skew_enabled",
        "universe_selective_enabled",
    ]
    assert payload["provenance"]["trades_fingerprint"]
    # candidate_summary uses the LEGACY GateSummary key names on purpose, so the
    # Go handler and the Foreman board render it without a shim.
    assert set(payload["candidate_summary"]) == {
        "version",
        "pnl",
        "trades",
        "win_rate",
        "max_drawdown",
    }
    assert payload["candidate_summary"]["pnl"] == 700.0
    assert payload["candidate_summary"]["max_drawdown"] is None


# ---------------------------------------------------------------------------
# Regression: the 18 vacuous self-comparisons
# ---------------------------------------------------------------------------


def test_old_vacuous_self_comparison_no_longer_reads_as_a_bare_pass(tmp_path: Path, config: dict):
    """The 18-file shape: a deterministic replay gated against itself.

    Under v49 this produced `passed: true` with six green gates and zero deltas.
    Under the standing gates it must be either NO_OP (nothing new was measured)
    or a real FAIL against the per-cell floor — never a bare PASS whose only
    evidence is a comparison with itself.
    """
    identical = dict(pnl=1149.76, trades=42, frozen_cache=True)
    sib_res = _results(tmp_path, "v251_crisis_r1", **identical)
    sib_trades = _trades(tmp_path, "v251_crisis_r1", _TWO_TRADES)
    cand_res = _results(tmp_path, "v252_crisis_r1", **identical)
    cand_trades = _trades(tmp_path, "v252_crisis_r1", _TWO_TRADES)

    out = check_standing_gates(
        cand_res, cand_trades, config,
        sibling_label="v251_crisis_r1", sibling_results=sib_res, sibling_trades_path=sib_trades,
    )
    # $1,149.76 clears the per-cell floor (and crisis's campaign mean), so both
    # v49 logic and the per-cell floor say PASS.
    assert out.gates["cell_pnl_floor"].status == STATUS_PASS
    assert "advisory" not in out.gates["cell_pnl_floor"].detail
    # …but the run reproduced its sibling, so the verdict names that.
    assert out.verdict == VERDICT_NO_OP
    assert out.passed is False
    assert out.sibling_comparison["delta_pnl_usd"] == 0.0
    assert out.sibling_comparison["status"] == "informational"


def test_real_corpus_gate_files_are_reported_against_the_per_cell_floor(tmp_path: Path, config: dict):
    """A real archived cell, re-gated: v252_replay_2024-03-10 is a crisis window.

    Its recorded PnL is $1,149.76 (CAMPAIGN_STATUS.md:30-31), which clears the
    per-cell floor. The point of the assertion is the FAMILY: the label carries
    a date, so v49's sibling lookup resolved nothing at all and wrote no file.
    """
    real = DATA_DIR / "v252_replay_2024-03-10_results.json"
    if not real.exists():
        pytest.skip("archived replay results not present in this checkout")
    out = check_standing_gates(real, None, config)
    assert out.family == "crisis"
    assert out.standing_baseline_used["family_source"] == "manifest"
    assert out.gates["cell_pnl_floor"].detail["floor_usd"] == 0.0
    assert out.gates["cell_pnl_floor"].detail["campaign_mean_usd"] == 599.0
    assert out.verdict in {VERDICT_PASS, VERDICT_FAIL}

"""Tests for the grid-level campaign ruler (omega/eval/grid_ruler.py).

The centrepiece is not a hand-built fixture: it is
`tests/fixtures/v247_paired_grids.json`, the REAL candidate arms of the four
completed walk-forward grids that `training_log/V247_RULER.md` §3 calibrated the
instrument from. Pairing them against the standing baseline committed in
`data/standing_baseline.json` must reproduce all 16 published mean-Δ figures and
all 16 published Δ-sd figures. If the ruler's arithmetic ever drifts from the
journal's, these tests say so in the journal's own numbers.

Everything else is here because it is a way the ruler could lie:

* an MDE that does not reproduce §7's standing thresholds;
* INSUFFICIENT_GRID rendered as (or masking) something else;
* a partial grid judged against the n=32 bar;
* an unpairable cell counted as a zero;
* two cells disagreeing about one window, quietly tie-broken;
* a config with no per-window values silently falling back to a mean-vs-mean
  comparison — the OFF-arm LEVEL ruler the doc says "can never be the gate".
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from omega.eval.grid_ruler import (
    ADVISORY_BELOW_RECENT_FLOOR,
    ADVISORY_REGRESSION_WITHIN_NOISE,
    PAIRING_PAIRED,
    PAIRING_UNPAIRED,
    POOLED,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    VERDICT_ERROR,
    VERDICT_FAIL,
    VERDICT_INSUFFICIENT_GRID,
    VERDICT_PASS,
    GridCell,
    check_grid_ruler,
    error_payload,
    load_manifest,
    mde,
    percentile,
)
from omega.eval.standing_gates import load_baseline_config

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "v247_paired_grids.json"
FAMILIES = ("crisis", "recent", "trend", POOLED)


@pytest.fixture(scope="module")
def config() -> dict:
    return load_baseline_config()


@pytest.fixture(scope="module")
def manifest() -> dict:
    return load_manifest()


@pytest.fixture(scope="module")
def grids() -> dict:
    data: dict = json.loads(FIXTURE.read_text())
    return data


def cells_for(grids: dict, name: str) -> list[GridCell]:
    spec = grids["grids"][name]
    return [
        GridCell(
            label=f"{name}_{c['window']}",
            window=c["window"],
            family=c["regime"],
            pnl_usd=c["pnl_usd"],
            trades=c["trades"],
        )
        for c in spec["cells"]
    ]


def baseline_cells(config: dict) -> list[GridCell]:
    """The standing baseline itself, re-presented as a candidate grid."""
    return [
        GridCell(
            label=f"base_{w['window']}", window=w["window"], family=family, pnl_usd=w["pnl_usd"]
        )
        for family, spec in config["distributions"]["per_family"].items()
        for w in spec["windows"]
    ]


# ── the committed standing distribution ──────────────────────────────────────


def test_standing_distribution_covers_the_whole_manifest(config, manifest):
    """32 windows, and every one of them is a manifest id with the same regime."""
    per_family = config["distributions"]["per_family"]
    manifest_regimes = {w["id"]: w["regime"] for w in manifest["windows"]}
    assert len(manifest_regimes) == 32

    seen = {}
    for family, spec in per_family.items():
        assert spec["n"] == len(spec["windows"])
        for row in spec["windows"]:
            assert row["window"] in manifest_regimes, row["window"]
            assert manifest_regimes[row["window"]] == family
            seen[row["window"]] = row["pnl_usd"]
    assert len(seen) == 32
    assert {f: per_family[f]["n"] for f in ("crisis", "trend", "recent")} == {
        "crisis": 12,
        "trend": 10,
        "recent": 10,
    }


def test_standing_distribution_means_match_the_journal(config):
    """+$599 / +$2,997 / +$30 — README.md:36-38, to the journal's rounding."""
    per_family = config["distributions"]["per_family"]
    families = config["families"]
    for family, expected in (("crisis", 599.0), ("trend", 2997.0), ("recent", 30.0)):
        values = [w["pnl_usd"] for w in per_family[family]["windows"]]
        mean = sum(values) / len(values)
        assert round(mean) == pytest.approx(expected, abs=1.0), family
        # and the summary the cell layer already used agrees with the values
        assert families[family]["campaign_mean_usd"] == pytest.approx(expected)
        assert per_family[family]["mean_usd"] == pytest.approx(mean, abs=0.01)


# ── the bars ─────────────────────────────────────────────────────────────────


def test_mde_reproduces_the_published_standing_thresholds(config):
    """V247_RULER.md §7: recent $1,043 / trend $4,118 / crisis $1,565; §4 pooled $1,425."""
    ruler = config["grid_ruler"]
    sds = ruler["delta_sd_usd"]["median"]
    ns = ruler["n_at_publication"]
    for family, published in ruler["published_mde_usd_at_current_n"].items():
        if family.startswith("_"):
            continue
        assert mde(sds[family], ns[family]) == pytest.approx(published, abs=1.0), family


def test_pooled_mde_reproduces_the_mechanism_conditional_rows(config):
    """§4: $875 low-coupling, $633 near-inert, $2,180 heavy — all at n=32."""
    table = config["grid_ruler"]["delta_sd_usd"]
    assert mde(table["low"]["pooled"], 32) == pytest.approx(875, abs=1)
    assert mde(table["inert"]["pooled"], 32) == pytest.approx(633, abs=1)
    assert mde(table["heavy"]["pooled"], 32) == pytest.approx(2180, abs=2)


def test_mde_scales_as_one_over_sqrt_n():
    assert mde(1000.0, 4) == pytest.approx(2 * mde(1000.0, 16))


def test_percentile_matches_numpy_linear_interpolation():
    xs = [1.0, 2.0, 3.0, 4.0]
    assert percentile(xs, 25) == pytest.approx(1.75)
    assert percentile(xs, 50) == pytest.approx(2.5)
    assert percentile([5.0], 90) == 5.0


# ── the centrepiece: the real grids ──────────────────────────────────────────


@pytest.mark.parametrize(
    "grid_name", ["v241_reasoning", "v243a_blacklist_ext", "v245_gdelt", "v246_exit_adapt"]
)
def test_real_grids_reproduce_the_published_paired_delta_table(grids, config, manifest, grid_name):
    """Every mean-Δ and Δ-sd in V247_RULER.md §3, from the real committed grids."""
    result = check_grid_ruler(cells_for(grids, grid_name), config, manifest, run_label=grid_name)
    published_mean = grids["published_delta_mean_usd"][grid_name]
    published_sd = grids["published_delta_sd_usd"][grid_name]

    assert result.coverage["complete"] is True
    assert result.coverage["pairing"] == PAIRING_PAIRED
    for family in FAMILIES:
        ruling = result.families[family]
        assert ruling.mean_delta_usd == pytest.approx(published_mean[family], abs=1.0), family
        assert ruling.sd_usd == pytest.approx(published_sd[family], abs=1.0), family


@pytest.mark.parametrize(
    "grid_name", ["v241_reasoning", "v243a_blacklist_ext", "v245_gdelt", "v246_exit_adapt"]
)
def test_no_completed_grid_regressed_the_standing_baseline(grids, config, manifest, grid_name):
    """All four PASS the no-regression ruler — and that is the correct answer.

    None of these mechanisms SHIPPED: V241/V243-A/V245/V246 were all refuted as
    IMPROVEMENTS, against pre-registered acceptance bars. This ruler asks the
    opposite question — did the standing baseline go backwards — and the honest
    answer for all four is no. A ruler that returned FAIL here would be
    re-adjudicating settled verdicts under a bar invented afterwards, which
    V247_RULER_CANDIDATES.md's standing anti-Goodhart guard forbids.
    """
    result = check_grid_ruler(cells_for(grids, grid_name), config, manifest, run_label=grid_name)
    assert result.verdict == VERDICT_PASS
    assert result.failures == []
    assert result.passed is True


def test_v245_near_inert_grid_carries_the_within_noise_advisory(grids, config, manifest):
    """v245's pooled −$31 is a regression the instrument cannot resolve.

    §7 forbids reading signal into it; it must therefore be neither a FAIL nor a
    silence. It is an advisory, exactly as the cell layer treats
    `below_campaign_mean`.
    """
    result = check_grid_ruler(cells_for(grids, "v245_gdelt"), config, manifest, run_label="v245")
    pooled = result.families[POOLED]
    assert pooled.mean_delta_usd < 0
    assert abs(pooled.mean_delta_usd) < pooled.mde_usd
    assert pooled.status == STATUS_PASS
    assert ADVISORY_REGRESSION_WITHIN_NOISE in pooled.advisories
    assert result.verdict == VERDICT_PASS


def test_identity_grid_is_all_zero_deltas(config, manifest):
    """Re-running the baseline against itself: every Δ is exactly $0.00."""
    result = check_grid_ruler(baseline_cells(config), config, manifest, run_label="identity")
    assert result.verdict == VERDICT_PASS
    for family in FAMILIES:
        ruling = result.families[family]
        assert ruling.mean_delta_usd == 0.0
        assert ruling.sd_usd == 0.0
        assert ruling.advisories == []


def test_bootstrap_ci_is_deterministic_and_order_independent(grids, config, manifest):
    cells = cells_for(grids, "v246_exit_adapt")
    a = check_grid_ruler(cells, config, manifest, run_label="a")
    b = check_grid_ruler(list(reversed(cells)), config, manifest, run_label="b")
    for family in FAMILIES:
        assert a.families[family].bootstrap_ci95_usd == b.families[family].bootstrap_ci95_usd
        assert a.families[family].bootstrap_ci95_usd is not None


# ── FAIL ─────────────────────────────────────────────────────────────────────


def test_a_regression_past_the_pooled_mde_fails(config, manifest):
    """Every window down by $2,000 — comfortably past every family's bar."""
    cells = [
        GridCell(label=c.label, window=c.window, family=c.family, pnl_usd=c.pnl_usd - 2000.0)
        for c in baseline_cells(config)
    ]
    result = check_grid_ruler(cells, config, manifest, run_label="down2k")
    assert result.verdict == VERDICT_FAIL
    pooled = result.families[POOLED]
    assert pooled.status == STATUS_FAIL
    assert pooled.mean_delta_usd == pytest.approx(-2000.0)
    assert pooled.margin_usd < 0
    assert any("grid_regression[pooled]" in f for f in result.failures)
    # crisis ($1,565) and recent ($1,043) breach too; trend's bar is $4,118.
    assert result.families["crisis"].status == STATUS_FAIL
    assert result.families["recent"].status == STATUS_FAIL
    assert result.families["trend"].status == STATUS_PASS


def test_a_regression_just_inside_the_bar_passes_with_an_advisory(config, manifest):
    """$1,400 down: under the pooled $1,424 bar, over recent's $1,044 and crisis's $1,565? no."""
    cells = [
        GridCell(label=c.label, window=c.window, family=c.family, pnl_usd=c.pnl_usd - 1400.0)
        for c in baseline_cells(config)
    ]
    result = check_grid_ruler(cells, config, manifest, run_label="down1400")
    assert result.families[POOLED].status == STATUS_PASS
    assert ADVISORY_REGRESSION_WITHIN_NOISE in result.families[POOLED].advisories
    # recent's bar is $1,043.64 — $1,400 clears it, so the grid still FAILs there.
    assert result.families["recent"].status == STATUS_FAIL
    assert result.verdict == VERDICT_FAIL


def test_the_recent_floor_is_an_advisory_not_a_failure(config, manifest):
    """β's −$360 recent floor is reported; it does not move the verdict."""
    cells = [
        GridCell(
            label=c.label,
            window=c.window,
            family=c.family,
            pnl_usd=c.pnl_usd - (500.0 if c.family == "recent" else 0.0),
        )
        for c in baseline_cells(config)
    ]
    result = check_grid_ruler(cells, config, manifest, run_label="recent500")
    recent = result.families["recent"]
    assert recent.mean_delta_usd == pytest.approx(-500.0)
    assert recent.status == STATUS_PASS
    assert ADVISORY_BELOW_RECENT_FLOOR in recent.advisories
    assert result.verdict == VERDICT_PASS
    assert not any("recent_no_regression_floor" in f for f in result.failures)


def test_a_pre_registration_can_gate_the_recent_floor(config, manifest):
    gated = json.loads(json.dumps(config))
    gated["grid_ruler"]["gate_advisory_recent_floor"] = True
    cells = [
        GridCell(
            label=c.label,
            window=c.window,
            family=c.family,
            pnl_usd=c.pnl_usd - (500.0 if c.family == "recent" else 0.0),
        )
        for c in baseline_cells(config)
    ]
    result = check_grid_ruler(cells, gated, manifest, run_label="recent500gated")
    assert result.verdict == VERDICT_FAIL
    assert result.families["recent"].status == STATUS_FAIL
    assert any("recent_no_regression_floor" in f for f in result.failures)


# ── INSUFFICIENT_GRID ────────────────────────────────────────────────────────


def test_a_partial_grid_is_insufficient_and_names_the_missing_windows(config, manifest):
    cells = [c for c in baseline_cells(config) if c.family == "crisis"][:6]
    result = check_grid_ruler(cells, config, manifest, run_label="partial")

    assert result.verdict == VERDICT_INSUFFICIENT_GRID
    assert result.passed is False
    coverage = result.coverage
    assert coverage["complete"] is False
    assert coverage["covered_windows"] == 6
    assert coverage["expected_windows"] == 32
    assert len(coverage["per_family"]["crisis"]["missing"]) == 6
    assert len(coverage["per_family"]["trend"]["missing"]) == 10
    assert len(coverage["per_family"]["recent"]["missing"]) == 10
    # every missing id is named, per family — not just counted
    assert all(w.startswith("snap_wf_") for w in coverage["per_family"]["recent"]["missing"])
    assert any("INSUFFICIENT_GRID" in n for n in result.ruler_notes)


def test_a_family_with_no_cells_is_not_evaluated_not_passed(config, manifest):
    cells = [c for c in baseline_cells(config) if c.family == "crisis"]
    result = check_grid_ruler(cells, config, manifest, run_label="crisisonly")
    assert result.families["trend"].status == STATUS_NOT_EVALUATED
    assert result.families["recent"].status == STATUS_NOT_EVALUATED
    assert result.families["trend"].n == 0
    assert result.verdict == VERDICT_INSUFFICIENT_GRID


def test_a_short_grid_gets_a_wider_bar_not_the_published_one(config, manifest):
    """MDE ∝ 1/√n, so 3 crisis windows are judged against ~$3,130, not $1,565."""
    cells = [c for c in baseline_cells(config) if c.family == "crisis"][:3]
    result = check_grid_ruler(cells, config, manifest, run_label="short")
    crisis = result.families["crisis"]
    assert crisis.n == 3
    assert crisis.mde_usd == pytest.approx(mde(1935.0, 3), abs=0.01)
    assert crisis.mde_usd > crisis.published_mde_usd
    assert "actual n=3" in (crisis.reason or "")


def test_a_real_regression_on_a_partial_grid_still_fails(config, manifest):
    """FAIL outranks INSUFFICIENT_GRID — the bar it cleared was the partial one."""
    cells = [
        GridCell(label=c.label, window=c.window, family=c.family, pnl_usd=c.pnl_usd - 20000.0)
        for c in baseline_cells(config)
        if c.family == "crisis"
    ][:4]
    result = check_grid_ruler(cells, config, manifest, run_label="partialfail")
    assert result.verdict == VERDICT_FAIL
    assert result.coverage["complete"] is False
    assert result.families["crisis"].status == STATUS_FAIL


def test_a_config_with_no_per_window_values_refuses_to_rule(config, manifest):
    """The summary-stats fallback is LOUD and is never a pass.

    V247_RULER.md §1 on the OFF-arm level distribution: "it can never be the
    gate". A mean-vs-mean comparison IS that ruler, so the module declines
    rather than quietly producing a worse verdict that looks the same.
    """
    stripped = json.loads(json.dumps(config))
    stripped.pop("distributions")
    result = check_grid_ruler(baseline_cells(config), stripped, manifest, run_label="nodist")
    assert result.verdict == VERDICT_INSUFFICIENT_GRID
    assert result.coverage["pairing"] == PAIRING_UNPAIRED
    assert any("LIMITATION" in n for n in result.ruler_notes)
    assert any("no_standing_distribution" in f for f in result.failures)
    assert result.families == {}


# ── cells that cannot be paired ──────────────────────────────────────────────


def test_an_unknown_window_is_excluded_not_zeroed(config, manifest):
    cells = [
        *baseline_cells(config),
        GridCell(
            label="v231smoke_crisis_r1",
            window="snap_crisis_2020q1",
            family="crisis",
            pnl_usd=-9999.0,
        ),
    ]
    result = check_grid_ruler(cells, config, manifest, run_label="stray")
    assert result.verdict == VERDICT_PASS
    assert result.families["crisis"].n == 12
    assert result.families["crisis"].mean_delta_usd == 0.0
    unpairable = result.coverage["unpairable_cells"]
    assert len(unpairable) == 1
    assert unpairable[0]["label"] == "v231smoke_crisis_r1"
    assert any("EXCLUDED" in n for n in result.ruler_notes)


def test_two_cells_disagreeing_about_one_window_is_a_hole_not_a_tiebreak(config, manifest):
    base = baseline_cells(config)
    window = base[0].window
    cells = [
        *base,
        GridCell(
            label="dupe", window=window, family=base[0].family, pnl_usd=base[0].pnl_usd + 5000.0
        ),
    ]
    result = check_grid_ruler(cells, config, manifest, run_label="dupe")
    assert result.verdict == VERDICT_FAIL
    assert any(f"ambiguous_window[{window}]" in f for f in result.failures)
    assert window in result.coverage["per_family"][base[0].family]["missing"]


def test_an_exactly_duplicated_cell_is_deduped_quietly_but_noted(config, manifest):
    base = baseline_cells(config)
    cells = [
        *base,
        GridCell(
            label="replicate_r2",
            window=base[0].window,
            family=base[0].family,
            pnl_usd=base[0].pnl_usd,
        ),
    ]
    result = check_grid_ruler(cells, config, manifest, run_label="replicate")
    assert result.verdict == VERDICT_PASS
    assert result.coverage["complete"] is True
    assert any("duplicate cells" in n for n in result.ruler_notes)


def test_a_cell_whose_family_contradicts_the_manifest_uses_the_manifest(config, manifest):
    base = baseline_cells(config)
    lied = [
        GridCell(
            label=c.label,
            window=c.window,
            family="trend" if c.family == "crisis" else c.family,
            pnl_usd=c.pnl_usd,
        )
        for c in base
    ]
    result = check_grid_ruler(lied, config, manifest, run_label="lied")
    assert result.families["crisis"].n == 12
    assert result.families["trend"].n == 10
    assert any("family conflict" in n for n in result.ruler_notes)


# ── coupling class ───────────────────────────────────────────────────────────


def test_declaring_low_coupling_narrows_the_pooled_bar(grids, config, manifest):
    cells = cells_for(grids, "v246_exit_adapt")
    default = check_grid_ruler(cells, config, manifest, run_label="d")
    low = check_grid_ruler(cells, config, manifest, run_label="l", coupling_class="low")
    assert default.families[POOLED].mde_usd == pytest.approx(1424.35, abs=0.5)
    assert low.families[POOLED].mde_usd == pytest.approx(875.1, abs=0.5)
    assert low.families[POOLED].mde_usd < default.families[POOLED].mde_usd
    assert default.provenance["coupling_class"] == "median"
    assert default.provenance["coupling_class_declared"] is None
    assert low.provenance["coupling_class"] == "low"


def test_an_undeclared_coupling_class_is_confessed_in_the_notes(grids, config, manifest):
    result = check_grid_ruler(cells_for(grids, "v246_exit_adapt"), config, manifest, run_label="d")
    assert any("no coupling class was declared" in n for n in result.ruler_notes)


def test_an_unknown_coupling_class_falls_back_and_says_so(grids, config, manifest):
    result = check_grid_ruler(
        cells_for(grids, "v246_exit_adapt"),
        config,
        manifest,
        run_label="d",
        coupling_class="banana",
    )
    assert result.provenance["coupling_class"] == "median"
    assert any("banana" in n for n in result.ruler_notes)


# ── output ───────────────────────────────────────────────────────────────────


def test_verdict_file_round_trips(config, manifest, tmp_path):
    out = tmp_path / "run_grid_verdict.json"
    result = check_grid_ruler(
        baseline_cells(config), config, manifest, run_label="run", out_path=out
    )
    payload = json.loads(out.read_text())
    assert payload["verdict"] == VERDICT_PASS == result.verdict
    assert payload["passed"] is True
    assert payload["run_label"] == "run"
    assert payload["ruler_module"] == "omega/eval/grid_ruler.py"
    assert set(payload["families"]) == set(FAMILIES)
    assert payload["families"][POOLED]["n"] == 32
    assert payload["standing_distribution_used"]["per_family"]["crisis"]["n"] == 12
    assert payload["provenance"]["bootstrap"] == {"resamples": 20000, "seed": 42}
    assert len(payload["cells"]) == 32


def test_error_payload_is_a_record_not_a_silence(tmp_path):
    out = tmp_path / "boom_grid_verdict.json"
    payload = error_payload("boom", ValueError("nope"), out_path=out)
    assert payload["verdict"] == VERDICT_ERROR
    assert payload["passed"] is False
    assert json.loads(out.read_text())["error_type"] == "ValueError"


# ── the CLI ──────────────────────────────────────────────────────────────────


def test_cli_resolves_a_real_prefix_over_the_real_data_dir(tmp_path):
    """v252_replay is three REAL walk-forward cells in data/ — a genuine partial grid.

    The data dir is read-only here: `--out` points at tmp_path.

    SKIPPED when those cells are absent. Run artifacts (data/v*_results.json) are
    gitignored and, per CLAUDE.md, do not even propagate to worktrees — so on a
    fresh clone or in CI this test could only ever fail. A check that fails
    everywhere except one developer's machine is not a check, and it was one of the
    33 standing failures that made the whole suite unreadable.
    """
    if not list((ROOT / "data").glob("v252_replay*_results.json")):
        pytest.skip("v252_replay cells not present in data/ (gitignored run artifacts)")
    out = tmp_path / "v252_replay_grid_verdict.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_grid_ruler.py"),
            "--run",
            "v252_replay",
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert proc.returncode == 1, proc.stderr
    assert "INSUFFICIENT_GRID" in proc.stdout
    payload = json.loads(out.read_text())
    assert payload["verdict"] == VERDICT_INSUFFICIENT_GRID
    assert payload["coverage"]["covered_windows"] == 3
    assert payload["coverage"]["expected_windows"] == 32
    # the three cells are one per regime — the manifest says so, their labels do not
    assert {c["family"] for c in payload["cells"]} == {"crisis", "trend", "recent"}
    assert {c["window"] for c in payload["cells"]} == {
        "snap_wf_20230912",
        "snap_wf_20240310",
        "snap_wf_20250305",
    }


def test_cli_no_write_writes_nothing(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_grid_ruler.py"),
            "--run",
            "v252_replay",
            "--no-write",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert proc.returncode == 1
    assert "wrote" not in proc.stdout
    assert not (ROOT / "data" / "v252_replay_grid_verdict.json").exists()


def test_cli_reports_an_unmatched_prefix_as_insufficient(tmp_path):
    out = tmp_path / "nothing_grid_verdict.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_grid_ruler.py"),
            "--run",
            "no_such_run_prefix_xyz",
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert proc.returncode == 1
    payload = json.loads(out.read_text())
    assert payload["verdict"] == VERDICT_INSUFFICIENT_GRID
    assert payload["coverage"]["covered_windows"] == 0
    assert len(payload["coverage"]["per_family"]["crisis"]["missing"]) == 12

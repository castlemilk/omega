"""omega.eval.overfitting_gate — CI-based overfitting detection for TPE.

After TPE completes, call check_overfitting() with the Sharpe on the validate
split and the Sharpe on the held-out test split. The gate rejects improvement
proposals where the test Sharpe falls more than 1 bootstrap std-dev below the
validate Sharpe — the canonical sign of optimisation overfitting.

Usage::

    from omega.eval.overfitting_gate import check_overfitting

    result = check_overfitting(
        validate_sharpe=validate_metrics["sharpe"],
        validate_ci_lower=validate_metrics["sharpe_ci_lower"],
        validate_ci_upper=validate_metrics["sharpe_ci_upper"],
        test_sharpe=test_metrics["sharpe"],
    )
    if not result.passed:
        logger.warning("Rejecting proposal: %s", result.reason)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OverfittingResult:
    """Result of the overfitting gate check."""

    passed: bool  # True = not overfitting; proposal is acceptable
    reason: str  # Human-readable explanation with all numeric context
    threshold: float  # Minimum acceptable test Sharpe (validate_sharpe - 1 std_dev)
    gap: float  # validate_sharpe - test_sharpe; positive = test is worse


def check_overfitting(
    validate_sharpe: float,
    validate_ci_lower: float,
    validate_ci_upper: float,
    test_sharpe: float,
) -> OverfittingResult:
    """
    Gate: reject if test Sharpe is more than 1 std-dev below validate Sharpe.

    The std-dev is estimated from the bootstrap 95% CI width:
        std_dev ~= (ci_upper - ci_lower) / (2 * 1.96)

    Threshold: validate_sharpe - std_dev
    Pass condition: test_sharpe >= threshold

    Parameters
    ----------
    validate_sharpe   : Best-trial Sharpe on the validate split (TPE objective).
    validate_ci_lower : Lower bound of 95% bootstrap CI on validate Sharpe.
    validate_ci_upper : Upper bound of 95% bootstrap CI on validate Sharpe.
    test_sharpe       : Sharpe on the held-out test split (never seen by TPE).

    Returns
    -------
    OverfittingResult — check .passed before accepting the improvement proposal.
    """
    std_dev = (validate_ci_upper - validate_ci_lower) / (2.0 * 1.96)
    threshold = validate_sharpe - std_dev
    gap = validate_sharpe - test_sharpe
    passed = test_sharpe >= threshold

    if passed:
        reason = (
            f"test_sharpe={test_sharpe:.4f} >= threshold={threshold:.4f} "
            f"(validate={validate_sharpe:.4f}, std_dev={std_dev:.4f}, gap={gap:.4f})"
        )
    else:
        reason = (
            f"overfitting detected: test_sharpe={test_sharpe:.4f} < "
            f"threshold={threshold:.4f} "
            f"(validate={validate_sharpe:.4f}, std_dev={std_dev:.4f}, gap={gap:.4f})"
        )

    return OverfittingResult(passed=passed, reason=reason, threshold=threshold, gap=gap)

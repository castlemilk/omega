"""
omega.nodes.vectora
~~~~~~~~~~~~~~~~~~~~
Vectora domain nodes for quantitative market research.

Nodes:
  - DataIngestionNode       : fetches OHLCV data from Yahoo Finance (free)
  - SignalGenerationNode    : computes technical trading signals
  - StrategyNode            : constructs portfolios and backtests strategies
  - RiskManagementNode      : estimates VaR, CVaR, position sizing
  - ReportingNode           : generates human-readable market analysis reports
  - LintNode                : data quality linter (NaN, missing fields, outliers)
  - DataIntegrityNode       : freshness, coverage, bar count, volume, gap checks
  - VerificationNode        : verifies self-improvements don't break invariants
  - PropertyTestNode        : tests mathematical/logical properties on pipeline outputs
  - InvariantDiscoveryNode  : observes pipeline state and discovers statistical invariants
  - ConvergenceMonitorNode  : tracks long-term convergence of the self-improvement loop
"""

from omega.nodes.vectora.cleaners import DataIntegrityNode, LintNode
from omega.nodes.vectora.dashboard import DashboardNode
from omega.nodes.vectora.data_ingestion import DataIngestionNode
from omega.nodes.vectora.reporting import ReportingNode
from omega.nodes.vectora.risk_management import RiskManagementNode
from omega.nodes.vectora.signal_generation import SignalGenerationNode
from omega.nodes.vectora.strategy import StrategyNode
from omega.nodes.vectora.verification import (
    ConvergenceMonitorNode,
    InvariantDiscoveryNode,
    PropertyTestNode,
    VerificationNode,
)

__all__ = [
    "ConvergenceMonitorNode",
    "DashboardNode",
    "DataIngestionNode",
    "DataIntegrityNode",
    "InvariantDiscoveryNode",
    "LintNode",
    "PropertyTestNode",
    "ReportingNode",
    "RiskManagementNode",
    "SignalGenerationNode",
    "StrategyNode",
    "VerificationNode",
]

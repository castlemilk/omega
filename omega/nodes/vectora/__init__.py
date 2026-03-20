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

from omega.nodes.vectora.data_ingestion import DataIngestionNode
from omega.nodes.vectora.signal_generation import SignalGenerationNode
from omega.nodes.vectora.strategy import StrategyNode
from omega.nodes.vectora.risk_management import RiskManagementNode
from omega.nodes.vectora.reporting import ReportingNode
from omega.nodes.vectora.cleaners import LintNode, DataIntegrityNode
from omega.nodes.vectora.verification import (
    VerificationNode,
    PropertyTestNode,
    InvariantDiscoveryNode,
    ConvergenceMonitorNode,
)
from omega.nodes.vectora.dashboard import DashboardNode

__all__ = [
    "DataIngestionNode",
    "SignalGenerationNode",
    "StrategyNode",
    "RiskManagementNode",
    "ReportingNode",
    "LintNode",
    "DataIntegrityNode",
    "VerificationNode",
    "PropertyTestNode",
    "InvariantDiscoveryNode",
    "ConvergenceMonitorNode",
    "DashboardNode",
]

"""
omega.adversarial
~~~~~~~~~~~~~~~~~
Adversarial debate layer for Omega/Vectora.

Provides structured Bull/Bear debate (DebateGate) and three-perspective
risk persona debate (RiskPersonas) for signal disagreement resolution.
Both modules operate entirely with rule-based/quantitative logic —
zero LLM calls in the critical path.

Exports
-------
DebateGate, SignalContext, DebateVerdict
RiskPersonas, RiskContext, RiskDebate
"""

from omega.adversarial.debate_gate import DebateGate, DebateVerdict, SignalContext
from omega.adversarial.risk_personas import RiskContext, RiskDebate

__all__ = [
    "DebateGate",
    "DebateVerdict",
    "RiskContext",
    "RiskDebate",
    "SignalContext",
]

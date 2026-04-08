"""
omega.nodes.victoria.geometry
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Information geometry for market manifold modeling.

Exports the primary public interface:
  MarketManifold        — Fisher-Rao statistical manifold of return distributions.
  OllivierRicciCurvature — ORC on the dynamic asset correlation network.
"""

from omega.nodes.victoria.geometry.market_manifold import MarketManifold, ManifoldState
from omega.nodes.victoria.geometry.ollivier_ricci import OllivierRicciCurvature, OrcState

__all__ = ["MarketManifold", "ManifoldState", "OllivierRicciCurvature", "OrcState"]

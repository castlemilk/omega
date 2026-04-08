"""
omega.nodes.victoria.geometry
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Information geometry for market manifold modeling.

Exports the primary public interface:
  MarketManifold — statistical manifold of return distributions.
"""

from omega.nodes.victoria.geometry.market_manifold import MarketManifold, ManifoldState

__all__ = ["MarketManifold", "ManifoldState"]

"""Adapter interfaces and provider implementations."""

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.brave import BraveAdapter
from freesearch.adapters.exa import ExaAdapter
from freesearch.adapters.firecrawl import FirecrawlAdapter
from freesearch.adapters.keenable import KeenableAdapter
from freesearch.adapters.parallel import ParallelAdapter
from freesearch.adapters.tavily import TavilyAdapter
from freesearch.adapters.youcom import YoucomAdapter

__all__ = [
    "BraveAdapter",
    "ExaAdapter",
    "FirecrawlAdapter",
    "KeenableAdapter",
    "ParallelAdapter",
    "ProviderAdapter",
    "TavilyAdapter",
    "YoucomAdapter",
]

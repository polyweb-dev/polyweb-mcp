"""Adapter interfaces and provider implementations."""

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.parallel import ParallelAdapter
from freesearch.adapters.tavily import TavilyAdapter

__all__ = ["ParallelAdapter", "ProviderAdapter", "TavilyAdapter"]

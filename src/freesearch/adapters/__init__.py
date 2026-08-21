"""Adapter interfaces and provider implementations."""

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.firecrawl import FirecrawlAdapter
from freesearch.adapters.tavily import TavilyAdapter

__all__ = ["FirecrawlAdapter", "ProviderAdapter", "TavilyAdapter"]

"""Tavily parameter models and pure depth and debit helpers.

These models stay independent of the request contracts, the adapter, and the
SDK, so ``freesearch.models.contracts`` can embed them without an import
cycle. All amounts are exact ``Decimal`` values, and every helper is pure: no
persistence, no vendor I/O, no routing input.
"""

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "TavilyDepth",
    "TavilyExtractParams",
    "TavilySearchParams",
    "tavily_extract_credits",
    "tavily_extract_depth",
    "tavily_search_depth",
]

TavilyDepth = Literal["basic", "advanced"]
TavilySearchDepth = Literal["basic", "advanced", "fast", "ultra-fast"]

# Tavily bills extract as one credit (basic) or two credits (advanced) per five
# successful URLs, so one good URL costs an exact fraction of a credit.
_CREDITS_PER_URL: dict[str, Decimal] = {
    "basic": Decimal("0.2"),
    "advanced": Decimal("0.4"),
}


class _TavilyParamsBase(BaseModel):
    """Strict, secret-safe base for caller-supplied Tavily parameters."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )


class TavilySearchParams(_TavilyParamsBase):
    """Optional caller parameters for one Tavily search call.

    The adapter owns auth, the endpoint, the timeout, ``max_results``, and
    ``include_usage``; callers cannot set those fields here.
    """

    search_depth: TavilySearchDepth | None = None
    chunks_per_source: int | None = Field(default=None, ge=1, le=3)
    topic: Literal["general", "news", "finance"] | None = None
    time_range: Literal["day", "week", "month", "year", "d", "w", "m", "y"] | None = None
    start_date: str | None = Field(default=None, min_length=8, max_length=10)
    end_date: str | None = Field(default=None, min_length=8, max_length=10)
    days: int | None = Field(default=None, ge=1)
    include_domains: tuple[str, ...] | None = None
    exclude_domains: tuple[str, ...] | None = None
    include_answer: bool | Literal["basic", "advanced"] | None = None
    include_raw_content: bool | Literal["markdown", "text"] | None = None
    include_images: bool | None = None
    include_image_descriptions: bool | None = None
    include_published_date: bool | None = None
    filter_by_published_date: bool | None = None
    include_domains_mode: Literal["restrict", "prefer"] | None = None
    language: str | None = Field(default=None, min_length=2, max_length=64)
    filter_by_language: bool | None = None
    safe_search: bool | None = None
    auto_parameters: bool | None = None
    include_favicon: bool | None = None
    exact_match: bool | None = None
    country: str | None = Field(default=None, min_length=3, max_length=40)

    @field_validator("include_domains", "exclude_domains", "country")
    @classmethod
    def _entries_must_be_named(cls, value: tuple[str, ...] | str | None) -> Any:
        if value is None:
            return None
        values = value if isinstance(value, tuple) else (value,)
        if any(not entry.strip() for entry in values):
            raise ValueError("entries must not be blank")
        return value


class TavilyExtractParams(_TavilyParamsBase):
    """Optional caller parameters for one Tavily extract call.

    The adapter owns auth, the endpoint, the timeout, ``urls``, and
    ``include_usage``; callers cannot set those fields here.
    """

    extract_depth: TavilyDepth | None = None
    format: Literal["markdown", "text"] | None = None
    query: str | None = Field(default=None, min_length=1)
    chunks_per_source: int | None = Field(default=None, ge=1)
    include_images: bool | None = None
    include_favicon: bool | None = None
    timeout: float | None = Field(default=None, ge=1, le=60)


def tavily_search_depth(mode: str | None, params: TavilySearchParams | None) -> TavilySearchDepth:
    """Resolve the search depth from the routing mode and explicit parameters.

    An explicit parameter depth wins. A conflict between an explicit depth and
    a caller ``basic``/``advanced`` mode is rejected before vendor I/O. An
    absent or other mode (``turbo``) keeps the basic depth.
    """

    explicit = params.search_depth if params is not None else None
    if explicit is not None:
        if mode in ("basic", "advanced") and mode != explicit:
            raise ValueError("search mode conflicts with the explicit Tavily search depth")
        return explicit
    return "advanced" if mode == "advanced" else "basic"


def tavily_extract_depth(params: TavilyExtractParams | None) -> TavilyDepth:
    """Return the extract depth; absent parameters keep the basic depth."""

    explicit = params.extract_depth if params is not None else None
    return explicit if explicit is not None else "basic"


def tavily_extract_credits(successful_urls: int, depth: TavilyDepth) -> Decimal:
    """Return the exact Credits one extract call costs for its successful URLs.

    Bad URLs cost zero Credits, so only the successful count enters the debit.
    Basic extract charges one Credit per five good URLs and advanced extract
    charges two, so one basic good URL costs ``0.2`` Credits and one advanced
    good URL costs ``0.4`` Credits.
    """

    if successful_urls < 0:
        raise ValueError("successful_urls must not be negative")
    return _CREDITS_PER_URL[depth] * Decimal(successful_urls)

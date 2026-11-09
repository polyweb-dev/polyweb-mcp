"""Typed provider-native search and fetch options accepted by the API.

The provider names in these models are the canonical Polyweb IDs.  The
models intentionally describe request fields that the adapters can forward;
they do not accept arbitrary vendor payloads.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from polyweb.models.tavily import TavilyExtractParams, TavilySearchParams


class ProviderOptionModel(BaseModel):
    """Strict base for provider options."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)


# Brave Search API ---------------------------------------------------------

BraveResultType = Literal[
    "discussions", "faq", "infobox", "news", "query", "summarizer", "videos", "web", "locations"
]


class BraveLocationHeaders(ProviderOptionModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    timezone: str | None = None
    city: str | None = None
    state: str | None = None
    state_name: str | None = None
    country: str | None = None
    postal_code: str | None = None

    @model_validator(mode="after")
    def validate_coordinate_pair(self) -> "BraveLocationHeaders":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class BraveSearchOptions(ProviderOptionModel):
    """Brave Web Search or query-driven LLM Context options."""

    search_type: Literal["web", "llm_context"] = "web"
    api_version: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    country: str | None = Field(default=None, min_length=2, max_length=2)
    search_lang: str | None = Field(default=None, min_length=2, max_length=16)
    ui_lang: str | None = Field(default=None, min_length=2, max_length=16)
    offset: int | None = Field(default=None, ge=0, le=9)
    freshness: str | None = Field(default=None, min_length=1, max_length=21)
    safesearch: Literal["off", "moderate", "strict"] | None = None
    spellcheck: bool | None = None
    text_decorations: bool | None = None
    result_filter: tuple[BraveResultType, ...] | None = Field(default=None, max_length=9)
    units: Literal["metric", "imperial"] | None = None
    goggles: str | tuple[str, ...] | None = None
    extra_snippets: bool | None = None
    summary: bool | None = None
    enable_rich_callback: bool | None = None
    include_fetch_metadata: bool | None = None
    operators: bool | None = None
    no_cache: bool | None = None
    location: BraveLocationHeaders | None = None
    maximum_number_of_urls: int | None = Field(default=None, ge=1, le=50)
    maximum_number_of_tokens: int | None = Field(default=None, ge=1024, le=32768)
    maximum_number_of_snippets: int | None = Field(default=None, ge=1, le=256)
    maximum_number_of_tokens_per_url: int | None = Field(default=None, ge=512, le=8192)
    maximum_number_of_snippets_per_url: int | None = Field(default=None, ge=1, le=100)
    context_threshold_mode: Literal["strict", "balanced", "lenient", "disabled"] | None = None
    enable_local: bool | None = None
    enable_source_metadata: bool | None = None

    @model_validator(mode="after")
    def validate_context_options(self) -> "BraveSearchOptions":
        if self.search_type == "llm_context" and self.summary:
            raise ValueError("summary is only supported by Brave Web Search")
        if self.goggles is not None and isinstance(self.goggles, tuple) and len(self.goggles) > 3:
            raise ValueError("Brave accepts at most three goggles")
        return self


# Exa Search and Contents APIs --------------------------------------------


class ExaUserLocation(ProviderOptionModel):
    country: str | None = Field(default=None, min_length=2, max_length=2)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def validate_coordinates(self) -> "ExaUserLocation":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class ExaTextOptions(ProviderOptionModel):
    max_characters: int | None = Field(default=None, ge=1)


class ExaHighlightsOptions(ProviderOptionModel):
    query: str | None = Field(default=None, min_length=1)
    highlights_per_url: int | None = Field(default=None, ge=1)
    num_sentences: int | None = Field(default=None, ge=1)
    highlights_text_length: int | None = Field(default=None, ge=1)


class ExaSummaryOptions(ProviderOptionModel):
    query: str | None = Field(default=None, min_length=1)
    max_characters: int | None = Field(default=None, ge=1)


class ExaExtrasOptions(ProviderOptionModel):
    links: int | None = Field(default=None, ge=1)
    image_links: int | None = Field(default=None, ge=1)
    rich_image_links: int | None = Field(default=None, ge=1)
    rich_links: int | None = Field(default=None, ge=1)
    code_blocks: int | None = Field(default=None, ge=1)


class ExaContentsOptions(ProviderOptionModel):
    text: bool | ExaTextOptions | None = None
    highlights: bool | ExaHighlightsOptions | None = None
    summary: bool | ExaSummaryOptions | None = None
    extras: ExaExtrasOptions | None = None
    livecrawl_timeout: int | None = Field(default=None, ge=1, le=90_000)
    max_age_hours: int | None = Field(default=None, ge=-1, le=720)
    snapshot_as_of: str | None = None
    subpages: int | None = Field(default=None, ge=0, le=100)
    subpage_target: str | tuple[str, ...] | None = None
    compliance: Literal["hipaa"] | None = None
    user_identifier: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"
    )


class ExaSearchOptions(ProviderOptionModel):
    type: Literal["instant", "fast", "auto", "deep-lite", "deep", "deep-reasoning"] | None = None
    category: (
        Literal["company", "publication", "news", "personal site", "financial report", "people"]
        | None
    ) = None
    include_domains: tuple[str, ...] | None = Field(default=None, max_length=1200)
    exclude_domains: tuple[str, ...] | None = Field(default=None, max_length=1200)
    start_published_date: str | None = None
    end_published_date: str | None = None
    moderation: bool | None = None
    additional_queries: tuple[str, ...] | None = Field(default=None, min_length=1, max_length=10)
    user_location: str | ExaUserLocation | None = None
    compliance: Literal["hipaa"] | None = None
    output_schema: dict[str, Any] | None = None
    objective: str | None = Field(default=None, max_length=4096)
    system_prompt: str | None = None
    user_identifier: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"
    )
    contents: ExaContentsOptions | None = None


class ExaFetchOptions(ExaContentsOptions):
    """Exa Contents options; common URL and result limits stay in the request."""


# Firecrawl Search and Scrape APIs ----------------------------------------

FirecrawlSourceType = Literal["web", "images", "news", "alexandria"]
FirecrawlCategory = Literal["developer", "gov", "research", "pdf"]


class FirecrawlCategoryOption(ProviderOptionModel):
    """Object form of the Firecrawl Search category filter."""

    type: FirecrawlCategory


class FirecrawlSource(ProviderOptionModel):
    type: FirecrawlSourceType
    tbs: str | None = None
    location: str | None = None


class FirecrawlThreatProtection(ProviderOptionModel):
    mode: Literal["off", "normal"] | None = None
    risk_score_threshold: int | None = Field(default=None, ge=0, le=100)
    blacklist: tuple[str, ...] | None = Field(default=None, max_length=1000)
    whitelist: tuple[str, ...] | None = Field(default=None, max_length=1000)
    blocked_tlds: tuple[str, ...] | None = Field(default=None, max_length=1000)
    failure_policy: Literal["open", "closed"] | None = None


class FirecrawlViewport(ProviderOptionModel):
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)


class FirecrawlFormatOptions(ProviderOptionModel):
    """Options for documented Firecrawl format objects."""

    type: Literal[
        "markdown",
        "summary",
        "html",
        "rawHtml",
        "rawBase64",
        "links",
        "images",
        "attributes",
        "screenshot",
        "json",
        "changeTracking",
        "branding",
        "product",
        "menu",
        "audio",
        "video",
        "question",
        "highlights",
    ]
    prompt: str | None = None
    json_schema: dict[str, Any] | None = Field(default=None, alias="schema")
    selector: str | None = None
    attributes: tuple[str, ...] | None = None
    full_page: bool | None = None
    quality: int | None = Field(default=None, ge=1, le=100)
    viewport: FirecrawlViewport | None = None
    mode: Literal["git-diff", "json"] | None = None
    question: str | None = Field(default=None, max_length=10_000)
    query: str | None = Field(default=None, max_length=10_000)


class FirecrawlParser(ProviderOptionModel):
    type: Literal["pdf", "image"]
    mode: Literal["fast", "auto", "ocr"] | None = None
    max_pages: int | None = Field(default=None, ge=1, le=10_000)
    pages: bool | None = None
    blocks: bool | None = None
    page_markers: bool | None = None


class FirecrawlAction(ProviderOptionModel):
    """One documented browser action in a Firecrawl Scrape request."""

    type: Literal[
        "wait",
        "screenshot",
        "click",
        "write",
        "press",
        "scroll",
        "scrape",
        "executeJavascript",
        "pdf",
    ]
    milliseconds: int | None = Field(default=None, ge=0)
    selector: str | None = None
    full_page: bool | None = None
    text: str | None = None
    key: str | None = None
    direction: Literal["up", "down"] | None = None
    script: str | None = None
    format: (
        Literal["A0", "A1", "A2", "A3", "A4", "A5", "A6", "Letter", "Legal", "Tabloid", "Ledger"]
        | None
    ) = None


class FirecrawlLocation(ProviderOptionModel):
    country: str | None = Field(default=None, min_length=2, max_length=2)
    languages: tuple[str, ...] | None = None


class FirecrawlRedactPII(ProviderOptionModel):
    mode: Literal["accurate", "aggressive", "fast"] | None = None
    entities: (
        tuple[Literal["PERSON", "EMAIL", "PHONE", "LOCATION", "FINANCIAL", "SECRET"], ...] | None
    ) = None
    replacement: Literal["tag", "mask", "remove"] | None = None


class FirecrawlProfile(ProviderOptionModel):
    name: str = Field(min_length=1, max_length=128)
    save_changes: bool | None = None


class FirecrawlScrapeOptions(ProviderOptionModel):
    formats: (
        tuple[
            Literal[
                "markdown",
                "summary",
                "html",
                "rawHtml",
                "rawBase64",
                "links",
                "images",
                "screenshot",
                "json",
                "changeTracking",
                "branding",
                "product",
                "menu",
                "audio",
                "video",
                "question",
                "highlights",
            ]
            | FirecrawlFormatOptions,
            ...,
        ]
        | None
    ) = None
    only_main_content: bool | None = None
    only_clean_content: bool | None = None
    include_tags: tuple[str, ...] | None = None
    exclude_tags: tuple[str, ...] | None = None
    max_age: int | None = Field(default=None, ge=0)
    min_age: int | None = Field(default=None, ge=0)
    headers: dict[str, str] | None = None
    wait_for: int | None = Field(default=None, ge=0, le=60_000)
    mobile: bool | None = None
    skip_tls_verification: bool | None = None
    timeout: int | None = Field(default=None, ge=1000, le=300_000)
    parsers: tuple[FirecrawlParser, ...] | None = None
    actions: tuple[FirecrawlAction, ...] | None = None
    location: FirecrawlLocation | None = None
    remove_base64_images: bool | None = None
    block_ads: bool | None = None
    proxy: Literal["basic", "enhanced", "auto"] | None = None
    store_in_cache: bool | None = None
    lockdown: bool | None = None
    check_prompt_injection: bool | None = None
    redact_pii: bool | FirecrawlRedactPII | None = None
    profile: FirecrawlProfile | None = None
    zero_data_retention: bool | None = None
    domain_tools: bool | None = None
    tool_detail: Literal["compact", "summary", "full"] | None = None


class FirecrawlSearchOptions(ProviderOptionModel):
    sources: tuple[FirecrawlSourceType | FirecrawlSource, ...] | None = None
    domain_tools: bool | None = None
    tool_detail: Literal["compact", "summary", "full"] | None = None
    categories: tuple[FirecrawlCategory | FirecrawlCategoryOption, ...] | None = None
    include_domains: tuple[str, ...] | None = None
    exclude_domains: tuple[str, ...] | None = None
    tbs: str | None = None
    location: str | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2)
    safe: bool | None = None
    timeout: int | None = Field(default=None, ge=1)
    ignore_invalid_urls: bool | None = None
    highlights: bool | None = None
    enterprise: tuple[Literal["anon", "zdr"], ...] | None = Field(
        default=None, min_length=1, max_length=1
    )
    scrape_options: FirecrawlScrapeOptions | None = None
    threat_protection: FirecrawlThreatProtection | None = None

    @model_validator(mode="after")
    def validate_filters(self) -> "FirecrawlSearchOptions":
        if self.include_domains and self.exclude_domains:
            raise ValueError("Firecrawl include_domains and exclude_domains are mutually exclusive")
        category_types = {
            category if isinstance(category, str) else category.type
            for category in self.categories or ()
        }
        if "gov" in category_types and len(category_types) > 1:
            raise ValueError("Firecrawl category 'gov' cannot be combined with other categories")
        return self


class FirecrawlFetchOptions(FirecrawlScrapeOptions):
    """Firecrawl Scrape options plus the endpoint's source URL-independent flags."""


# Keenable Search and Fetch APIs ------------------------------------------


class KeenableSearchOptions(ProviderOptionModel):
    mode: Literal["pro", "realtime"] | None = None
    site: str | None = None
    acquired_after: str | None = None
    acquired_before: str | None = None
    published_after: str | None = None
    published_before: str | None = None
    query_time: str | None = None
    snippet_max_length: int | None = Field(default=None, ge=180, le=10_000)


class KeenableFetchOptions(ProviderOptionModel):
    live: bool | None = None
    prompt: str | None = Field(default=None, max_length=2000)


# Parallel Search and Extract APIs ----------------------------------------


class ParallelSourcePolicy(ProviderOptionModel):
    include_domains: tuple[str, ...] | None = None
    exclude_domains: tuple[str, ...] | None = None
    after_date: str | None = None


class ParallelFetchPolicy(ProviderOptionModel):
    max_age_seconds: int | None = Field(default=None, ge=600)
    timeout_seconds: int | None = Field(default=None, ge=1)
    disable_cache_fallback: bool | None = None


class ParallelExcerptSettings(ProviderOptionModel):
    max_chars_per_result: int | None = Field(default=None, ge=1)


class ParallelSearchSettings(ProviderOptionModel):
    source_policy: ParallelSourcePolicy | None = None
    fetch_policy: ParallelFetchPolicy | None = None
    excerpt_settings: ParallelExcerptSettings | None = None
    location: str | None = None
    max_results: int | None = Field(default=None, ge=1)


class ParallelSearchOptions(ProviderOptionModel):
    search_queries: tuple[str, ...] | None = Field(default=None, min_length=1)
    objective: str | None = None
    mode: Literal["turbo", "fast", "basic", "advanced"] | None = None
    max_chars_total: int | None = Field(default=None, ge=1)
    session_id: str | None = Field(default=None, max_length=1000)
    client_model: str | None = None
    advanced_settings: ParallelSearchSettings | None = None


class ParallelFullContent(ProviderOptionModel):
    max_chars_per_result: int | None = Field(default=None, ge=1)


class ParallelExtractSettings(ProviderOptionModel):
    fetch_policy: ParallelFetchPolicy | None = None
    excerpt_settings: ParallelExcerptSettings | None = None
    full_content: bool | ParallelFullContent | None = None


class ParallelFetchOptions(ProviderOptionModel):
    objective: str | None = None
    search_queries: tuple[str, ...] | None = Field(default=None, min_length=1)
    max_chars_total: int | None = Field(default=None, ge=1)
    session_id: str | None = Field(default=None, max_length=1000)
    client_model: str | None = None
    advanced_settings: ParallelExtractSettings | None = None


# TinyFish Search and Fetch APIs -------------------------------------------


class TinyfishSearchOptions(ProviderOptionModel):
    purpose: str | None = Field(default=None, max_length=2000)
    location: str | None = None
    language: str | None = None
    include_domains: tuple[str, ...] | None = None
    exclude_domains: tuple[str, ...] | None = None
    recency_minutes: int | None = Field(default=None, ge=1, le=5_256_000)
    after_date: str | None = None
    before_date: str | None = None
    domain_type: Literal["web", "news", "research_paper"] | None = None
    pub_year_min: int | None = Field(default=None, ge=0, le=9999)
    pub_year_max: int | None = Field(default=None, ge=0, le=9999)
    page: int | None = Field(default=None, ge=0, le=10)

    @model_validator(mode="after")
    def validate_search_range(self) -> "TinyfishSearchOptions":
        if self.recency_minutes is not None and (
            self.after_date is not None or self.before_date is not None
        ):
            raise ValueError("TinyFish recency_minutes cannot be combined with date bounds")
        if (
            self.pub_year_min is not None
            and self.pub_year_max is not None
            and self.pub_year_min > self.pub_year_max
        ):
            raise ValueError("pub_year_min must not exceed pub_year_max")
        return self


class TinyfishHighlights(ProviderOptionModel):
    query: str = Field(min_length=1)
    max_snippets: int | None = Field(default=None, ge=1, le=20)
    max_characters: int | None = Field(default=None, ge=100, le=20_000)
    include_full_page_text: bool | None = None


class TinyfishFetchOptions(ProviderOptionModel):
    purpose: str | None = Field(default=None, max_length=2000)
    format: Literal["markdown", "html", "json"] | None = None
    links: bool | None = None
    image_links: bool | None = None
    iframe_links: bool | None = None
    ttl: int | None = Field(default=None, ge=0)
    per_url_timeout_ms: int | None = Field(default=None, ge=1, le=110_000)
    if_none_match: str | None = None
    if_modified_since: str | None = None
    include_etag_and_last_modified: bool | None = None
    include_selectors: tuple[str, ...] | None = Field(default=None, min_length=1, max_length=20)
    exclude_selectors: tuple[str, ...] | None = Field(default=None, min_length=1, max_length=20)
    highlights: TinyfishHighlights | None = None

    @model_validator(mode="after")
    def validate_selectors(self) -> "TinyfishFetchOptions":
        selectors = tuple(self.include_selectors or ()) + tuple(self.exclude_selectors or ())
        if any(not selector.strip() or len(selector) > 1000 for selector in selectors):
            raise ValueError("TinyFish selectors must be 1-1000 characters")
        return self


# You.com Web Search and Contents APIs ------------------------------------

YouExtractionMode = Literal["highlights", "full_page"]


class YouHighlightsOptions(ProviderOptionModel):
    total_max_tokens: int | None = Field(default=None, ge=1024, le=8192)


class YouFullPageOptions(ProviderOptionModel):
    extraction_formats: tuple[Literal["html", "markdown"], ...] | None = None


class YouExtractionOptions(ProviderOptionModel):
    mode: YouExtractionMode
    source: Literal["blend", "cache", "fetch"] | None = None
    highlights: YouHighlightsOptions | None = None
    full_page: YouFullPageOptions | None = None

    @model_validator(mode="after")
    def validate_mode_options(self) -> "YouExtractionOptions":
        if self.mode == "highlights" and self.full_page is not None:
            raise ValueError("full_page settings require extraction.mode='full_page'")
        if self.mode == "full_page" and self.highlights is not None:
            raise ValueError("highlights settings require extraction.mode='highlights'")
        return self


class YouSearchOptions(ProviderOptionModel):
    freshness: str | None = None
    offset: int | None = Field(default=None, ge=0, le=9)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    language: str | None = Field(default=None, min_length=2, max_length=16)
    safesearch: Literal["off", "moderate", "strict"] | None = None
    knowledge: Literal["core"] | None = None
    include_domains: tuple[str, ...] | None = Field(default=None, max_length=500)
    exclude_domains: tuple[str, ...] | None = Field(default=None, max_length=5000)
    boost_domains: tuple[str, ...] | None = Field(default=None, max_length=500)
    strict_operators: bool | None = None
    extraction: YouExtractionOptions | None = None
    crawl_timeout: int | None = Field(default=None, ge=1, le=60)
    livecrawl: Literal["web", "news", "all"] | None = None
    livecrawl_formats: tuple[Literal["html", "markdown"], ...] | None = None

    @model_validator(mode="after")
    def validate_search_options(self) -> "YouSearchOptions":
        if self.include_domains and self.exclude_domains:
            raise ValueError("You.com include_domains and exclude_domains are mutually exclusive")
        if self.include_domains and self.boost_domains:
            raise ValueError("You.com boost_domains cannot be combined with include_domains")
        return self


class YouFetchOptions(ProviderOptionModel):
    formats: tuple[Literal["markdown", "html", "metadata"], ...] | None = None
    crawl_timeout: int | None = Field(default=None, ge=1, le=60)
    max_age: int | None = Field(default=None, ge=0)


# Operation-specific outer objects.  Each field is optional by design so a
# request can specify options only for a provider selected by routing.
class SearchProviderOptions(ProviderOptionModel):
    brave: BraveSearchOptions | None = None
    exa: ExaSearchOptions | None = None
    firecrawl: FirecrawlSearchOptions | None = None
    keenable: KeenableSearchOptions | None = None
    parallel: ParallelSearchOptions | None = None
    tavily: TavilySearchParams | None = None
    tinyfish: TinyfishSearchOptions | None = None
    you: YouSearchOptions | None = None


class FetchProviderOptions(ProviderOptionModel):
    exa: ExaFetchOptions | None = None
    firecrawl: FirecrawlFetchOptions | None = None
    keenable: KeenableFetchOptions | None = None
    parallel: ParallelFetchOptions | None = None
    tavily: TavilyExtractParams | None = None
    tinyfish: TinyfishFetchOptions | None = None
    you: YouFetchOptions | None = None


__all__ = [
    "BraveSearchOptions",
    "ExaFetchOptions",
    "ExaSearchOptions",
    "FetchProviderOptions",
    "FirecrawlFetchOptions",
    "FirecrawlSearchOptions",
    "KeenableFetchOptions",
    "KeenableSearchOptions",
    "ParallelFetchOptions",
    "ParallelSearchOptions",
    "SearchProviderOptions",
    "TinyfishFetchOptions",
    "TinyfishSearchOptions",
    "YouFetchOptions",
    "YouSearchOptions",
]

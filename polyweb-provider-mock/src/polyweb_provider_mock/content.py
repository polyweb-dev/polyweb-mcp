"""Deterministic synthetic content: search hits, pages, answers, and identifiers.

Every value derives from a SHA-256 hash of its inputs, so the same query or
URL always produces the same titles, URLs, snippets, scores, and page bodies.
Plugins shape these values into their provider's response format.
"""

import hashlib
import random
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

__all__ = [
    "Page",
    "SearchHit",
    "answer",
    "hex_id",
    "image_urls",
    "normalize_query",
    "normalize_url",
    "page",
    "rng",
    "search_hits",
    "stable_uuid",
]

_EPOCH = datetime(2026, 11, 1, tzinfo=UTC)

_DOMAINS = (
    "en.wikipedia.org",
    "developer.mozilla.org",
    "docs.python.org",
    "github.com",
    "stackoverflow.com",
    "medium.com",
    "arxiv.org",
    "www.nature.com",
    "www.reuters.com",
    "www.bbc.com",
    "www.theverge.com",
    "arstechnica.com",
    "www.techradar.com",
    "blog.cloudflare.com",
    "realpython.com",
    "learn.microsoft.com",
    "www.investopedia.com",
    "www.healthline.com",
    "news.ycombinator.com",
    "www.nytimes.com",
)

_TITLES = (
    "{Topic}: A Practical Guide",
    "Understanding {Topic} in {year}",
    "What Is {Topic}? Everything You Need to Know",
    "{Topic} Explained",
    "The Complete Guide to {Topic}",
    "{Topic} - Wikipedia",
    "How {Topic} Works: An In-Depth Look",
    "10 Things to Know About {Topic}",
    "{Topic}: Best Practices and Common Pitfalls",
    "A Beginner's Introduction to {Topic}",
    "{Topic} in Production: Lessons Learned",
    "Comparing Approaches to {Topic}",
)

_SENTENCES = (
    "{Topic} has become a central concern for teams that ship software at scale.",
    "This article walks through the core ideas behind {topic} with worked examples.",
    "Experts note that {topic} trades simplicity for flexibility in several ways.",
    "Recent benchmarks show measurable gains when {topic} is configured carefully.",
    "The history of {topic} goes back more than a decade of incremental changes.",
    "Common mistakes with {topic} include missing timeouts and unbounded retries.",
    "A short checklist helps readers evaluate {topic} for their own projects.",
    "Critics argue that {topic} is often adopted before the requirements are clear.",
    "The reference documentation for {topic} lists every option and its default.",
    "Case studies from several companies describe how {topic} reduced their costs.",
    "Researchers published a survey that compares {topic} with older alternatives.",
    "In practice, {topic} works best together with good observability and tests.",
)

_HEADINGS = ("Overview", "Background", "How it works", "Key concepts", "Examples", "Summary")

_EXTENSIONS = frozenset({"html", "htm", "php", "aspx", "jsp", "shtml", "md", "pdf"})

_STOPWORDS = frozenset({"a", "an", "and", "the", "of", "for", "to", "in", "on", "is", "what"})


def rng(*parts: object) -> random.Random:
    """Return a random generator seeded by the hash of ``parts``."""

    digest = hashlib.sha256("\x1f".join(map(str, parts)).encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def stable_uuid(*parts: object) -> str:
    """Return a version-4-shaped UUID derived from ``parts``."""

    digest = hashlib.sha256("\x1f".join(map(str, parts)).encode("utf-8")).digest()
    return str(uuid.UUID(bytes=digest[:16], version=4))


def hex_id(length: int, *parts: object) -> str:
    """Return ``length`` lowercase hex characters derived from ``parts``."""

    return hashlib.sha256("\x1f".join(map(str, parts)).encode("utf-8")).hexdigest()[:length]


def normalize_query(query: str) -> str:
    """Return the fixture match key of a query: lowercase, single spaces."""

    return " ".join(query.lower().split())


def normalize_url(url: str) -> str:
    """Return the fixture match key of a URL: trimmed, lowercase scheme and host."""

    text = url.strip()
    parts = urlsplit(text)
    if not parts.scheme or not parts.netloc:
        return text
    return parts._replace(scheme=parts.scheme.lower(), netloc=parts.netloc.lower()).geturl()


def _topic(query: str) -> str:
    words = [word for word in re.findall(r"[\w'-]+", query) if word.lower() not in _STOPWORDS]
    return " ".join(words[:6]) or query.strip() or "web search"


def _title_case(text: str) -> str:
    return " ".join(word[:1].upper() + word[1:] for word in text.split())


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "page"


def _sentences(generator: random.Random, topic: str, count: int) -> list[str]:
    picks = generator.sample(_SENTENCES, k=min(count, len(_SENTENCES)))
    return [line.format(Topic=_title_case(topic), topic=topic) for line in picks]


@dataclass(frozen=True)
class SearchHit:
    """One synthetic search result."""

    url: str
    domain: str
    title: str
    snippet: str
    score: float
    published: datetime


def _domain_pool(include: list[str], exclude: list[str]) -> list[str]:
    blocked = {domain.lower().removeprefix("www.") for domain in exclude}
    pool = [domain.lower() for domain in include] if include else list(_DOMAINS)
    allowed = [domain for domain in pool if domain.removeprefix("www.") not in blocked]
    return allowed or list(_DOMAINS)


def search_hits(
    query: str,
    count: int,
    *,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> list[SearchHit]:
    """Return ``count`` hits for ``query``, best score first."""

    topic = _topic(query)
    generator = rng("search", normalize_query(query))
    pool = _domain_pool(include_domains or [], exclude_domains or [])
    hits: list[SearchHit] = []
    score = 0.72 + generator.random() * 0.25
    for index in range(max(count, 0)):
        domain = pool[(generator.randrange(len(pool)) + index) % len(pool)]
        title = generator.choice(_TITLES).format(
            Topic=_title_case(topic), year=2024 + generator.randrange(3)
        )
        path = f"/{_slug(topic)}-{int(hex_id(8, query, index), 16) % 1_000_000}"
        hits.append(
            SearchHit(
                url=f"https://{domain}{path}",
                domain=domain,
                title=title,
                snippet=" ".join(_sentences(generator, topic, 2)),
                score=round(score, 8),
                published=_EPOCH - timedelta(days=generator.randrange(1, 900)),
            )
        )
        score = max(0.05, score - 0.02 - generator.random() * 0.08)
    return hits


@dataclass(frozen=True)
class Page:
    """A synthetic page body in markdown and plain text."""

    url: str
    title: str
    markdown: str
    text: str
    published: datetime
    images: tuple[str, ...]
    favicon: str | None


def _reserved(host: str) -> bool:
    return host.removeprefix("www.").split(".")[0] in {"example", "localhost"}


def page(url: str, title: str | None = None) -> Page:
    """Return the synthetic page at ``url``, optionally with a known ``title``.

    The IANA example domains get a short page without images or favicon,
    like the real ``example.com``.
    """

    parts = urlsplit(url)
    host = (parts.hostname or "example.com").lower()
    generator = rng("page", normalize_url(url))
    words = [
        word
        for word in re.split(r"[/_.-]+", parts.path)
        if word.isalpha() and word.lower() not in _EXTENSIONS
    ]
    topic = " ".join(words[-3:]) or host.removeprefix("www.").split(".")[0]
    if title is None:
        title = _title_case(topic) if words else f"{_title_case(topic)} Domain"
    if _reserved(host):
        body = "This domain is for use in documentation examples without needing permission."
        return Page(url, title, f"# {title}\n\n{body}", f"{title}\n{body}", _EPOCH, (), None)
    sections_md: list[str] = [f"# {title}"]
    sections_text: list[str] = [title]
    for heading in generator.sample(_HEADINGS, k=3):
        paragraph = " ".join(_sentences(generator, topic, 3))
        sections_md.append(f"## {heading}\n\n{paragraph}")
        sections_text.append(f"{heading}\n{paragraph}")
    sections_md.append(f"- Source: [{host}]({parts.scheme or 'https'}://{host}/)")
    published = _EPOCH - timedelta(days=generator.randrange(1, 900))
    return Page(
        url=url,
        title=title,
        markdown="\n\n".join(sections_md),
        text="\n".join(sections_text),
        published=published,
        images=tuple(image_urls(host, 2, url)),
        favicon=f"https://{host}/favicon.ico",
    )


def image_urls(host: str, count: int, *seed: object) -> list[str]:
    """Return ``count`` image URLs on ``host``."""

    return [f"https://{host}/images/{hex_id(12, *seed, index)}.jpg" for index in range(count)]


def answer(query: str) -> str:
    """Return a short synthetic answer paragraph for ``query``."""

    topic = _topic(query)
    return " ".join(_sentences(rng("answer", normalize_query(query)), topic, 3))

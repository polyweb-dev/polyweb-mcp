import type { Capability } from "./types";

export interface StaticProviderMeta {
  id: string;
  backendId: string;
  name: string;
  description: string;
  baseUrl: string;
  authHeaderName: string;
  capabilities: Capability[];
}

export const PROVIDER_CATALOG: StaticProviderMeta[] = [
  {
    id: "brave",
    backendId: "brave",
    name: "Brave Search",
    description: "Fast privacy-first independent web index with low latency.",
    baseUrl: "https://api.search.brave.com/res/v1/web/search",
    authHeaderName: "X-Subscription-Token",
    capabilities: ["search"],
  },
  {
    id: "keenable",
    backendId: "keenable",
    name: "Keenable",
    description: "Native search & clean markdown extraction with keyless public free tier.",
    baseUrl: "https://api.keenable.ai/v1",
    authHeaderName: "X-API-Key",
    capabilities: ["search", "fetch", "keyless_tier"],
  },
  {
    id: "tavily",
    backendId: "tavily",
    name: "Tavily",
    description: "AI-native search engine tailored for LLMs and deep content extraction.",
    baseUrl: "https://api.tavily.com",
    authHeaderName: "Authorization",
    capabilities: ["search", "fetch", "extract"],
  },
  {
    id: "exa",
    backendId: "exa",
    name: "Exa",
    description: "Neural & semantic search built on embeddings for meaning-based retrieval.",
    baseUrl: "https://api.exa.ai",
    authHeaderName: "x-api-key",
    capabilities: ["search", "fetch", "neural_search"],
  },
  {
    id: "firecrawl",
    backendId: "firecrawl",
    name: "Firecrawl",
    description: "Clean web scraping and crawling converting dynamic sites into markdown.",
    baseUrl: "https://api.firecrawl.dev/v1",
    authHeaderName: "Authorization",
    capabilities: ["search", "fetch", "live_crawl"],
  },
  {
    id: "youcom",
    backendId: "you",
    name: "You.com",
    description: "Web search and live crawl engine with high freshness and snippet parsing.",
    baseUrl: "https://api.ydc-index.io",
    authHeaderName: "X-API-Key",
    capabilities: ["search", "fetch", "live_crawl"],
  },
  {
    id: "parallel",
    backendId: "parallel",
    name: "Parallel",
    description: "High-throughput parallelized search and link discovery aggregator.",
    baseUrl: "https://api.parallel.ai/v1",
    authHeaderName: "Authorization",
    capabilities: ["search", "extract", "fetch"],
  },
];

export function catalogEntryForId(id: string): StaticProviderMeta | undefined {
  return PROVIDER_CATALOG.find((entry) => entry.id === id || entry.backendId === id);
}

export function catalogNameOf(id: string): string | undefined {
  if (id === "aggregated") return "All Providers";
  return catalogEntryForId(id)?.name;
}

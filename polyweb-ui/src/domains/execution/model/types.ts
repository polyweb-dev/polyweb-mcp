import type { UnitKind } from "@/shared/api/units";

export interface SearchRequest {
  query: string;
  providerIds?: string[];
  maxResults: number;
  timeoutMs: number;
  fanout?: boolean;
}

export interface SearchResult {
  id: string;
  providerId: string;
  providerName: string;
  title: string;
  url: string;
  snippet: string;
  relevanceScore: number;
  publishedDate?: string;
  rawMetadata?: Record<string, unknown>;
  sources?: string[];
}

export interface ProviderWaterfallItem {
  providerId: string;
  providerName: string;
  latencyMs: number;
  status: "success" | "failed" | "rate_limited" | "skipped";
  resultsCount: number;
  costCredits: number;
  error?: string;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  totalResults: number;
  selectedProviderId: string;
  fallbackChain: string[];
  waterfall: ProviderWaterfallItem[];
  executionTimeMs: number;
  costEstimateCredits: number;
  /** Unit kind of `costEstimateCredits`; absent when the response did not say. */
  costUnitKind?: UnitKind | null;
  /** Backend display unit of `costEstimateCredits`, e.g. `requests`. */
  costDisplayUnit?: string | null;
  timestamp: string;
  participatingProviders?: string[];
}

export interface FetchRequest {
  url: string;
  providerId?: string;
  format: "markdown" | "text" | "html";
  includeRawHtml?: boolean;
  timeoutMs: number;
}

export interface FetchedDocument {
  url: string;
  title: string;
  content: string;
  markdown: string;
  providerId: string;
  providerName: string;
  statusCode: number | null;
  contentLength: number;
  executionTimeMs: number;
}

export interface FetchResponse {
  document: FetchedDocument;
  providerId: string;
  fallbackChain: string[];
  costEstimateCredits: number;
  executionTimeMs: number;
  timestamp: string;
}

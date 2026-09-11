import { createContext } from "react";
import type { FetchRequest, FetchResponse, SearchRequest, SearchResponse } from "@/domains/execution";

export interface ExecutionValue {
  activeSearch: SearchResponse | null;
  activeFetch: FetchResponse | null;
  isSearching: boolean;
  isFetching: boolean;
  searchError: string | null;
  fetchError: string | null;
  runSearch: (request: SearchRequest) => Promise<SearchResponse | null>;
  runFetch: (request: FetchRequest) => Promise<FetchResponse | null>;
  clearActiveResults: () => void;
}

export const ExecutionContext = createContext<ExecutionValue | undefined>(undefined);

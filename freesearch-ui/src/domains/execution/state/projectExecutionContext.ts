import { createContext } from "react";
import type { ToastNotification } from "@/shared/notifications/context";
import type {
  FetchRequest,
  FetchResponse,
  SearchRequest,
  SearchResponse,
} from "@/domains/execution/model/types";

export type ShowToast = (message: string, type?: ToastNotification["type"]) => void;

/** Search and fetch commands of one project playground scope. */
export interface ProjectExecutionValue {
  projectId: string;
  runSearch: (request: SearchRequest) => Promise<SearchResponse | null>;
  runFetch: (request: FetchRequest) => Promise<FetchResponse | null>;
}

export const ProjectExecutionContext = createContext<ProjectExecutionValue | undefined>(
  undefined,
);

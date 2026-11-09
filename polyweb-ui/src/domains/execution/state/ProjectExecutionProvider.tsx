import { useMemo } from "react";
import type { ReactNode } from "react";
import { ProjectExecutionContext } from "./projectExecutionContext";
import type { ShowToast } from "./projectExecutionContext";
import { useFetchRunner } from "./useFetchRunner";
import { useSearchRunner } from "./useSearchRunner";

/**
 * Execution scope of one project playground.
 *
 * It sits inside the project's playground store and is remounted with it on
 * a project switch, so each runner's abort-on-unmount cancels the previous
 * project's in-flight request. No API key is read or stored: the runners use
 * the shared transport and its in-memory human session.
 */
export function ProjectExecutionProvider({
  projectId,
  showToast,
  catalogNameOf,
  children,
}: {
  projectId: string;
  showToast: ShowToast;
  catalogNameOf: (id: string) => string | undefined;
  children: ReactNode;
}) {
  const runSearch = useSearchRunner({ projectId, showToast, catalogNameOf });
  const runFetch = useFetchRunner({ projectId, showToast });
  const value = useMemo(
    () => ({ projectId, runSearch, runFetch }),
    [projectId, runSearch, runFetch],
  );
  return (
    <ProjectExecutionContext.Provider value={value}>{children}</ProjectExecutionContext.Provider>
  );
}

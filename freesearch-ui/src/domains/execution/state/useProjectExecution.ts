import { useContext } from "react";
import { ProjectExecutionContext } from "./projectExecutionContext";
import type { ProjectExecutionValue } from "./projectExecutionContext";

/** Return the project execution commands, or reject a caller outside the scope. */
export function useProjectExecution(): ProjectExecutionValue {
  const value = useContext(ProjectExecutionContext);
  if (!value) throw new Error("useProjectExecution must be used within a ProjectExecutionProvider");
  return value;
}

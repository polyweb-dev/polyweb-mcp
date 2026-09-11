import { useContext } from "react";
import { ExecutionContext, type ExecutionValue } from "./context";

export type { ExecutionValue };

export function useExecution(): ExecutionValue {
  const value = useContext(ExecutionContext);
  if (!value) throw new Error("useExecution must be used within an ExecutionProvider");
  return value;
}

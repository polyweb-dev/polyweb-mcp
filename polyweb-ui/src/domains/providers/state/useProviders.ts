import { useContext } from "react";
import { ProvidersContext, type ProvidersValue } from "./context";

export type { ProvidersValue };

export function useProviders(): ProvidersValue {
  const value = useContext(ProvidersContext);
  if (!value) throw new Error("useProviders must be used within a ProvidersProvider");
  return value;
}

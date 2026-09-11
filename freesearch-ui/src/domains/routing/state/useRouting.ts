import { useContext } from "react";
import { RoutingContext, type RoutingValue } from "./context";

export type { RoutingValue };

export function useRouting(): RoutingValue {
  const value = useContext(RoutingContext);
  if (!value) throw new Error("useRouting must be used within a RoutingProvider");
  return value;
}

import { useContext } from "react";
import { DashboardContext, type DashboardValue } from "./context";

export type { DashboardValue };

export function useDashboard(): DashboardValue {
  const value = useContext(DashboardContext);
  if (!value) throw new Error("useDashboard must be used within a DashboardProvider");
  return value;
}

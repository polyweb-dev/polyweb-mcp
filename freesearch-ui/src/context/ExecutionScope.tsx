import React from "react";
import { useRouting } from "@/domains/routing/state/useRouting";
import { useDashboard } from "@/domains/dashboard/state/useDashboard";
import { ExecutionProvider } from "@/domains/execution/state/ExecutionContext";
import { catalogNameOf } from "@/domains/providers";

/** Wires execution's narrow composition inputs from sibling domains. */
export const ExecutionScope: React.FC<{
  showToast: (message: string) => void;
  children: React.ReactNode;
}> = ({ showToast, children }) => {
  const { fallbackConfig } = useRouting();
  const { refreshDashboard, prependUsageEvent } = useDashboard();
  return (
    <ExecutionProvider
      showToast={showToast}
      fallbackEnabled={fallbackConfig.enabled}
      catalogNameOf={catalogNameOf}
      refreshDashboard={refreshDashboard}
      prependUsageEvent={prependUsageEvent}
    >
      {children}
    </ExecutionProvider>
  );
};

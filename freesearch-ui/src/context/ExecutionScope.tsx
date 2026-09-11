import React from "react";
import { useRouting } from "@/domains/routing/state/useRouting";
import { useDashboard } from "@/domains/dashboard/state/useDashboard";
import { useProviders } from "@/domains/providers/state/useProviders";
import { ExecutionProvider } from "@/domains/execution/state/ExecutionContext";
import { catalogNameOf } from "@/domains/providers";

/** Wires execution's narrow composition inputs from sibling domains. */
export const ExecutionScope: React.FC<{
  showToast: (message: string) => void;
  children: React.ReactNode;
}> = ({ showToast, children }) => {
  const { fallbackConfig, routingPreset } = useRouting();
  const { providers } = useProviders();
  const { refreshDashboard, prependUsageEvent } = useDashboard();
  return (
    <ExecutionProvider
      showToast={showToast}
      fallbackEnabled={fallbackConfig.enabled}
      catalogNameOf={catalogNameOf}
      refreshDashboard={refreshDashboard}
      prependUsageEvent={prependUsageEvent}
      providers={providers}
      routingPreset={routingPreset}
    >
      {children}
    </ExecutionProvider>
  );
};

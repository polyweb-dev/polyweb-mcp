import React from "react";
import { useNotifications } from "@/shared/notifications/useNotifications";
import { ProvidersProvider } from "@/domains/providers/state/ProvidersContext";
import { RoutingProvider } from "@/domains/routing/state/RoutingContext";
import { DashboardProvider } from "@/domains/dashboard/state/DashboardContext";
import { catalogNameOf } from "@/domains/providers";
import { ExecutionScope } from "./ExecutionScope";
import { FreeSearchAdapter } from "./FreeSearchAdapter";

/**
 * Domain composition of the workspace. Each control-read provider receives the
 * role capability flags, so a role without control access makes no control
 * request and keeps an empty safe state.
 */
export const FreeSearchInner: React.FC<{
  canReadControls: boolean;
  canEditControls: boolean;
  children: React.ReactNode;
}> = ({ canReadControls, canEditControls, children }) => {
  const { showToast } = useNotifications();
  return (
    <ProvidersProvider
      showToast={showToast}
      canReadControls={canReadControls}
      canEditControls={canEditControls}
    >
      <RoutingProvider
        showToast={showToast}
        canReadControls={canReadControls}
        canEditControls={canEditControls}
      >
        <DashboardProvider
          showToast={showToast}
          catalogNameOf={catalogNameOf}
          canReadControls={canReadControls}
          canEditControls={canEditControls}
        >
          <ExecutionScope showToast={showToast}>
            <FreeSearchAdapter>{children}</FreeSearchAdapter>
          </ExecutionScope>
        </DashboardProvider>
      </RoutingProvider>
    </ProvidersProvider>
  );
};

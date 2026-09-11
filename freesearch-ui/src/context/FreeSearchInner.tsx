import React from "react";
import { useNotifications } from "@/shared/notifications/useNotifications";
import { ProvidersProvider } from "@/domains/providers/state/ProvidersContext";
import { RoutingProvider } from "@/domains/routing/state/RoutingContext";
import { DashboardProvider } from "@/domains/dashboard/state/DashboardContext";
import { catalogNameOf } from "@/domains/providers";
import { ExecutionScope } from "./ExecutionScope";
import { FreeSearchAdapter } from "./FreeSearchAdapter";

export const FreeSearchInner: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { showToast } = useNotifications();
  return (
    <ProvidersProvider showToast={showToast}>
      <RoutingProvider showToast={showToast}>
        <DashboardProvider showToast={showToast} catalogNameOf={catalogNameOf}>
          <ExecutionScope showToast={showToast}>
            <FreeSearchAdapter>{children}</FreeSearchAdapter>
          </ExecutionScope>
        </DashboardProvider>
      </RoutingProvider>
    </ProvidersProvider>
  );
};

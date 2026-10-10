import React, { useState } from "react";
import type { ProviderConfig } from "@/domains/providers/model/types";
import { ProvidersContext, type ShowToast } from "./context";
import { useProviderStatus } from "./useProviderStatus";
import { useProviderPriority } from "./useProviderPriority";
import { useProviderHealth } from "./useProviderHealth";
import { useProviderKeys } from "./useProviderKeys";

export type { ShowToast } from "./context";

export const ProvidersProvider: React.FC<{
  showToast: ShowToast;
  canReadControls: boolean;
  canEditControls: boolean;
  children: React.ReactNode;
}> = ({ showToast, canReadControls, canEditControls, children }) => {
  const [providers, setProviders] = useState<ProviderConfig[]>([]);
  const [providersLoading, setProvidersLoading] = useState(true);
  const [providersError, setProvidersError] = useState<string | null>(null);

  const { refreshProviders, toggleProvider, toggleProviderSearch, toggleProviderFetch } =
    useProviderStatus({
      setProviders,
      setProvidersLoading,
      setProvidersError,
      showToast,
      canReadControls,
    });
  const { updateProviderPriority, moveProviderPriority } = useProviderPriority({
    providers,
    setProviders,
    refreshProviders,
    showToast,
  });
  const { setCircuitBreaker, testProviderConnection } = useProviderHealth({
    providers,
    setProviders,
    showToast,
  });
  const { saveProviderKey, deleteProviderKey } = useProviderKeys({ setProviders, showToast });

  const value = React.useMemo(
    () => ({
      providers,
      providersLoading,
      providersError,
      canReadControls,
      canEditControls,
      refreshProviders,
      toggleProvider,
      toggleProviderSearch,
      toggleProviderFetch,
      updateProviderPriority,
      moveProviderPriority,
      setCircuitBreaker,
      testProviderConnection,
      saveProviderKey,
      deleteProviderKey,
    }),
    [
      providers,
      providersLoading,
      providersError,
      canReadControls,
      canEditControls,
      refreshProviders,
      toggleProvider,
      toggleProviderSearch,
      toggleProviderFetch,
      updateProviderPriority,
      moveProviderPriority,
      setCircuitBreaker,
      testProviderConnection,
      saveProviderKey,
      deleteProviderKey,
    ],
  );

  return <ProvidersContext.Provider value={value}>{children}</ProvidersContext.Provider>;
};

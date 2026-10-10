import React from "react";
import { NotificationsProvider } from "@/shared/notifications/NotificationsContext";
import { AppStoreProvider } from "@/store/AppStoreProvider";
import { FreeSearchInner } from "./FreeSearchInner";

/**
 * Public provider contract of the workspace. The confirmed account UUID selects
 * the persisted playground key before rehydration. The role capability flags
 * travel with the same composition, so a domain never imports the auth domain.
 */
export const FreeSearchProvider: React.FC<{
  accountId: string;
  canReadControls: boolean;
  canEditControls: boolean;
  children: React.ReactNode;
}> = ({ accountId, canReadControls, canEditControls, children }) => (
  <AppStoreProvider accountId={accountId}>
    <NotificationsProvider>
      <FreeSearchInner canReadControls={canReadControls} canEditControls={canEditControls}>
        {children}
      </FreeSearchInner>
    </NotificationsProvider>
  </AppStoreProvider>
);

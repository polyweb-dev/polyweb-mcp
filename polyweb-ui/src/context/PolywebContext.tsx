import React from "react";
import { NotificationsProvider } from "@/shared/notifications/NotificationsContext";
import { PolywebInner } from "./PolywebInner";

/**
 * Public provider contract of the account workspace: the global control plane
 * (providers, routing, installation usage) and the notifications. The
 * confirmed account UUID keys the composition, so another account never sees
 * this account's control state. The role capability flags travel with the
 * same composition, so a domain never imports the auth domain. Search and
 * fetch execution is project-scoped and lives in the project playground.
 */
export const PolywebProvider: React.FC<{
  accountId: string;
  canReadControls: boolean;
  canEditControls: boolean;
  children: React.ReactNode;
}> = ({ accountId, canReadControls, canEditControls, children }) => (
  <NotificationsProvider key={accountId}>
    <PolywebInner canReadControls={canReadControls} canEditControls={canEditControls}>
      {children}
    </PolywebInner>
  </NotificationsProvider>
);

import React from "react";
import { NotificationsProvider } from "@/shared/notifications/NotificationsContext";
import { AppStoreProvider } from "@/store/AppStoreProvider";
import { FreeSearchInner } from "./FreeSearchInner";

/**
 * Public provider contract is unchanged; the Redux store now sits above the
 * notification and domain providers so every domain runner shares one store.
 */
export const FreeSearchProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <AppStoreProvider>
    <NotificationsProvider>
      <FreeSearchInner>{children}</FreeSearchInner>
    </NotificationsProvider>
  </AppStoreProvider>
);

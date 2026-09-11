import React from "react";
import { NotificationsProvider } from "@/shared/notifications/NotificationsContext";
import { FreeSearchInner } from "./FreeSearchInner";

export const FreeSearchProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <NotificationsProvider>
    <FreeSearchInner>{children}</FreeSearchInner>
  </NotificationsProvider>
);

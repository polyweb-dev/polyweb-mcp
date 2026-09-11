import { useContext } from "react";
import { NotificationsContext } from "./context";

export function useNotifications() {
  const value = useContext(NotificationsContext);
  if (!value) throw new Error("useNotifications must be used within a NotificationsProvider");
  return value;
}

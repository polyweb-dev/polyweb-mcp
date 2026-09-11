import { createContext } from "react";

export interface ToastNotification {
  id: string;
  message: string;
  type: "success" | "info" | "warning" | "error";
}

interface NotificationsValue {
  toasts: ToastNotification[];
  showToast: (message: string, type?: ToastNotification["type"]) => void;
  dismissToast: (id: string) => void;
}

export const NotificationsContext = createContext<NotificationsValue | undefined>(undefined);

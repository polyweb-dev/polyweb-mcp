import React, { useCallback, useState } from "react";
import { NotificationsContext, type ToastNotification } from "./context";

let toastSequence = 0;

function scheduleDismiss(id: string, dismiss: (id: string) => void) {
  setTimeout(() => {
    if (typeof window !== "undefined") dismiss(id);
  }, 4500);
}

export const NotificationsProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastNotification[]>([]);

  const dismissToast = useCallback((id: string) => {
    setToasts((previous) => previous.filter((toast) => toast.id !== id));
  }, []);

  const showToast = useCallback(
    (message: string, type: ToastNotification["type"] = "info") => {
      toastSequence += 1;
      const id = `toast-${toastSequence}`;
      setToasts((previous) => [...previous, { id, message, type }]);
      scheduleDismiss(id, dismissToast);
    },
    [dismissToast],
  );

  const value = React.useMemo(
    () => ({ toasts, showToast, dismissToast }),
    [toasts, showToast, dismissToast],
  );

  return <NotificationsContext.Provider value={value}>{children}</NotificationsContext.Provider>;
};

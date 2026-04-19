import { createContext, useCallback, useContext, useEffect, useState } from "react";

export interface AppNotification {
  id: string;
  type: "awaiting_review" | "run_failed" | "run_complete";
  title: string;
  body: string;
  contractId: number | null;
  runId: string | null;
  read: boolean;
  createdAt: string;
}

interface NotificationContextValue {
  notifications: AppNotification[];
  unreadCount: number;
  add: (n: Omit<AppNotification, "id" | "read" | "createdAt">) => void;
  markAllRead: () => void;
  remove: (id: string) => void;
  clearAll: () => void;
}

const STORAGE_KEY = "veridict_notifications";

const NotificationContext = createContext<NotificationContextValue | null>(null);

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const [notifications, setNotifications] = useState<AppNotification[]>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(notifications));
  }, [notifications]);

  const add = useCallback((n: Omit<AppNotification, "id" | "read" | "createdAt">) => {
    setNotifications(prev => [
      {
        ...n,
        id: crypto.randomUUID(),
        read: false,
        createdAt: new Date().toISOString(),
      },
      ...prev,
    ].slice(0, 50));
  }, []);

  const markAllRead = useCallback(() => {
    setNotifications(prev => prev.map(n => ({ ...n, read: true })));
  }, []);

  const remove = useCallback((id: string) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
  }, []);

  const clearAll = useCallback(() => setNotifications([]), []);

  return (
    <NotificationContext.Provider value={{
      notifications,
      unreadCount: notifications.filter(n => !n.read).length,
      add,
      markAllRead,
      remove,
      clearAll,
    }}>
      {children}
    </NotificationContext.Provider>
  );
}

export function useNotifications() {
  const ctx = useContext(NotificationContext);
  if (!ctx) throw new Error("useNotifications must be used within NotificationProvider");
  return ctx;
}

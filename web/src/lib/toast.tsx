// Dependency-free toasts, themed with the token system. Wrap the app in
// <ToastProvider>; call const toast = useToast(); toast("Export queued").
import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from "react";

type ToastKind = "success" | "error";

interface Toast {
  id: number;
  text: string;
  kind: ToastKind;
}

const ToastContext = createContext<(text: string, kind?: ToastKind) => void>(
  () => undefined,
);

export const useToast = () => useContext(ToastContext);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const push = useCallback((text: string, kind: ToastKind = "success") => {
    const id = nextId.current++;
    setToasts((current) => [...current, { id, text, kind }]);
    setTimeout(
      () => setToasts((current) => current.filter((t) => t.id !== id)),
      4000,
    );
  }, []);

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col items-end gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={`rounded-xl border px-4 py-2 text-sm shadow-lg backdrop-blur ${
              t.kind === "error"
                ? "chip-red border-red-500/40"
                : "border-edge-strong bg-surface text-ink"
            }`}
          >
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

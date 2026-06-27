import { useEffect, useState, useCallback, createContext, useContext } from 'react';
import { CheckCircle, XCircle, AlertTriangle, Info, X } from 'lucide-react';

type ToastType = 'success' | 'error' | 'warning' | 'info';

interface Toast {
  id: number;
  type: ToastType;
  message: string;
}

interface ToastCtx {
  toast: (type: ToastType, message: string) => void;
}

const Ctx = createContext<ToastCtx>({ toast: () => {} });

export const useToast = () => useContext(Ctx);

let nextId = 0;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((type: ToastType, message: string) => {
    const id = ++nextId;
    setToasts(prev => [...prev, { id, type, message }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000);
  }, []);

  const remove = (id: number) => setToasts(prev => prev.filter(t => t.id !== id));

  return (
    <Ctx.Provider value={{ toast: addToast }}>
      {children}
      <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 pointer-events-none">
        {toasts.map(t => (
          <ToastItem key={t.id} toast={t} onClose={() => remove(t.id)} />
        ))}
      </div>
    </Ctx.Provider>
  );
}

function ToastItem({ toast, onClose }: { toast: Toast; onClose: () => void }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    requestAnimationFrame(() => setVisible(true));
    const timer = setTimeout(() => setVisible(false), 3600);
    return () => clearTimeout(timer);
  }, []);

  const icons = {
    success: <CheckCircle size={18} className="text-green-400 shrink-0" />,
    error: <XCircle size={18} className="text-red-400 shrink-0" />,
    warning: <AlertTriangle size={18} className="text-yellow-400 shrink-0" />,
    info: <Info size={18} className="text-blue-400 shrink-0" />,
  };

  const borders = {
    success: 'border-green-500/30',
    error: 'border-red-500/30',
    warning: 'border-yellow-500/30',
    info: 'border-blue-500/30',
  };

  return (
    <div
      className={`pointer-events-auto flex items-center gap-3 px-4 py-3 bg-gray-900 border ${borders[toast.type]} rounded-xl shadow-2xl shadow-black/40 min-w-[280px] max-w-sm transition-all duration-300 ${
        visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2'
      }`}
    >
      {icons[toast.type]}
      <span className="text-sm text-gray-200 flex-1">{toast.message}</span>
      <button onClick={onClose} className="text-gray-500 hover:text-gray-300 shrink-0">
        <X size={14} />
      </button>
    </div>
  );
}

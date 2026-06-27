import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

export interface SuiteSettings {
  assistantRuntimeEnabled: boolean;
  assistantRuntimeUrl: string;
}

interface SettingsCtx {
  settings: SuiteSettings;
  updateSettings: (patch: Partial<SuiteSettings>) => void;
  resetSettings: () => void;
}

const STORAGE_KEY = 'p2k-suite-settings';

const DEFAULT_SETTINGS: SuiteSettings = {
  assistantRuntimeEnabled: false,
  assistantRuntimeUrl: '/api/assistant-runtime',
};

const SettingsContext = createContext<SettingsCtx>({
  settings: DEFAULT_SETTINGS,
  updateSettings: () => {},
  resetSettings: () => {},
});

function loadSettings(): SuiteSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = JSON.parse(raw) as Partial<SuiteSettings>;
    return { ...DEFAULT_SETTINGS, ...parsed };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<SuiteSettings>(loadSettings);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch {
      /* ignore quota/serialization errors */
    }
  }, [settings]);

  const updateSettings = useCallback((patch: Partial<SuiteSettings>) => {
    setSettings((prev) => ({ ...prev, ...patch }));
  }, []);

  const resetSettings = useCallback(() => {
    setSettings(DEFAULT_SETTINGS);
  }, []);

  const value = useMemo(
    () => ({ settings, updateSettings, resetSettings }),
    [settings, updateSettings, resetSettings],
  );

  return (
    <SettingsContext.Provider value={value}>
      {children}
    </SettingsContext.Provider>
  );
}

export function useSettings() {
  return useContext(SettingsContext);
}

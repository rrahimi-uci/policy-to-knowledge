import { describe, it, expect, beforeEach } from 'vitest';
import type { ReactNode } from 'react';
import { renderHook, act } from '@testing-library/react';
import { SettingsProvider, useSettings } from './useSettings';

const wrapper = ({ children }: { children: ReactNode }) => (
  <SettingsProvider>{children}</SettingsProvider>
);

describe('useSettings', () => {
  beforeEach(() => localStorage.clear());

  it('starts from defaults', () => {
    const { result } = renderHook(() => useSettings(), { wrapper });
    expect(result.current.settings.assistantRuntimeEnabled).toBe(false);
    expect(result.current.settings.assistantRuntimeUrl).toBe('/api/assistant-runtime');
  });

  it('updateSettings merges a partial patch', () => {
    const { result } = renderHook(() => useSettings(), { wrapper });
    act(() => result.current.updateSettings({ assistantRuntimeEnabled: true }));
    expect(result.current.settings.assistantRuntimeEnabled).toBe(true);
    // unrelated field preserved
    expect(result.current.settings.assistantRuntimeUrl).toBe('/api/assistant-runtime');
  });

  it('persists settings to localStorage', () => {
    const { result } = renderHook(() => useSettings(), { wrapper });
    act(() => result.current.updateSettings({ assistantRuntimeUrl: '/custom' }));
    expect(localStorage.getItem('p2k-suite-settings')).toContain('/custom');
  });

  it('resetSettings restores defaults', () => {
    const { result } = renderHook(() => useSettings(), { wrapper });
    act(() => result.current.updateSettings({ assistantRuntimeEnabled: true }));
    act(() => result.current.resetSettings());
    expect(result.current.settings.assistantRuntimeEnabled).toBe(false);
  });

  it('loads persisted settings on mount', () => {
    localStorage.setItem('p2k-suite-settings', JSON.stringify({ assistantRuntimeEnabled: true }));
    const { result } = renderHook(() => useSettings(), { wrapper });
    expect(result.current.settings.assistantRuntimeEnabled).toBe(true);
  });
});

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { ThemeProvider, useTheme } from './useTheme';

function ThemeProbe() {
  const { theme } = useTheme();
  return <span data-testid="theme">{theme}</span>;
}

describe('useTheme message origin guard', () => {
  beforeEach(() => localStorage.clear());

  it('ignores theme-change messages not from the embedding parent', () => {
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId('theme').textContent).toBe('dark');

    // In jsdom the page is top-level (window.parent === window), so the guard
    // must reject the message rather than flipping the theme.
    act(() => {
      window.dispatchEvent(
        new MessageEvent('message', {
          source: window,
          data: { source: 'p2k-suite', type: 'theme-change', payload: { theme: 'light' } },
        }),
      );
    });
    expect(screen.getByTestId('theme').textContent).toBe('dark');
  });
});

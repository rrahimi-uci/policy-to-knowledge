import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import MicroFrame from './MicroFrame';
import { ThemeProvider } from '@/hooks/useTheme';

function renderFrame(props: { src: string; title: string }) {
  return render(
    <ThemeProvider>
      <MicroFrame {...props} />
    </ThemeProvider>,
  );
}

describe('MicroFrame', () => {
  afterEach(cleanup);

  it('renders an iframe with the given title and src', () => {
    renderFrame({ src: 'http://localhost:9999/app/', title: 'Explorer' });
    const iframe = screen.getByTitle('Explorer') as HTMLIFrameElement;
    expect(iframe).toBeInTheDocument();
    expect(iframe.getAttribute('src')).toBe('http://localhost:9999/app/');
  });

  it('hides the loading overlay and reveals content after onLoad fires', () => {
    renderFrame({ src: 'http://localhost:9999/app/', title: 'Explorer' });
    const iframe = screen.getByTitle('Explorer');
    // Simulate the iframe finishing load — clears the watchdog + loading state.
    fireEvent.load(iframe);
    // No error alert should be shown on a successful load.
    expect(screen.queryByText(/Failed to load/i)).toBeNull();
  });

  it('shows an actionable error state when the load watchdog times out', () => {
    vi.useFakeTimers();
    try {
      const { container } = renderFrame({ src: 'http://localhost:9999/app/', title: 'Explorer' });
      // Never fire onLoad; advance past the watchdog timeout (12s).
      act(() => {
        vi.advanceTimersByTime(13000);
      });
      expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
      expect(container.textContent).toContain('Failed to load');
    } finally {
      vi.useRealTimers();
    }
  });

  it('Retry reloads via the src attribute (never touches cross-origin contentWindow) and re-arms loading', () => {
    vi.useFakeTimers();
    try {
      const src = 'http://localhost:9999/app/';
      renderFrame({ src, title: 'Explorer' });
      const iframe = screen.getByTitle('Explorer') as HTMLIFrameElement;

      // Trip the watchdog into the error state so Retry is shown.
      act(() => {
        vi.advanceTimersByTime(13000);
      });
      const retry = screen.getByRole('button', { name: /retry/i });

      // The fix reloads by reassigning the iframe `src` and must never reach for
      // contentWindow.location, which throws SecurityError on a cross-origin
      // frame. Spy to assert it's left untouched.
      const contentWindowSpy = vi.spyOn(iframe, 'contentWindow', 'get');

      // Clicking Retry must not throw, must re-arm the loading overlay, and must
      // clear the error state by reassigning src.
      expect(() => fireEvent.click(retry)).not.toThrow();
      expect(screen.queryByText(/Failed to load/i)).toBeNull();
      expect(iframe.getAttribute('src')).toBe(src);
      expect(contentWindowSpy).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });
});

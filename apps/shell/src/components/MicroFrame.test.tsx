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
});

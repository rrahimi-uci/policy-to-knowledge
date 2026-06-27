import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Sidebar from './Sidebar';
import { isLinkActive } from './Sidebar';
import { ThemeProvider } from '@/hooks/useTheme';

describe('isLinkActive', () => {
  it('matches the home route only on exact "/"', () => {
    expect(isLinkActive('/', '/')).toBe(true);
    expect(isLinkActive('/analytics', '/')).toBe(false);
  });

  it('matches exact paths', () => {
    expect(isLinkActive('/obligations', '/obligations')).toBe(true);
  });

  it('matches nested paths on a segment boundary', () => {
    expect(isLinkActive('/extraction/runs', '/extraction')).toBe(true);
  });

  it('does NOT match a path that merely shares a prefix (regression)', () => {
    expect(isLinkActive('/obligations-archive', '/obligations')).toBe(false);
    expect(isLinkActive('/extraction-foo', '/extraction')).toBe(false);
  });
});

function renderSidebar(initialPath = '/') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <ThemeProvider>
        <Sidebar />
      </ThemeProvider>
    </MemoryRouter>
  );
}

describe('Sidebar render', () => {
  it('renders the brand, section headings and all nav links', () => {
    renderSidebar();
    expect(screen.getByText('Policy to Knowledge')).toBeTruthy();
    expect(screen.getByText('KNOWLEDGE GRAPHS')).toBeTruthy();
    expect(screen.getByText('COMPLIANCE INSIGHTS')).toBeTruthy();
    expect(screen.getByText('Dashboard')).toBeTruthy();
    expect(screen.getByText('Knowledge Graph Explorer')).toBeTruthy();
    expect(screen.getByText('Settings')).toBeTruthy();
  });

  it('marks the active route via aria-current', () => {
    renderSidebar('/obligations');
    const link = screen.getByText('Obligations').closest('a')!;
    expect(link.getAttribute('aria-current')).toBe('page');
  });

  it('theme toggle switches the label between Light/Dark Mode', () => {
    renderSidebar();
    const nav = screen.getByRole('navigation');
    // Button lives outside <nav>; query the whole sidebar via document.
    const before = screen.getByRole('button');
    const label = before.textContent ?? '';
    fireEvent.click(before);
    const after = screen.getByRole('button').textContent ?? '';
    expect(after).not.toBe(label);
    expect(within(nav).queryByRole('button')).toBeNull();
  });
});

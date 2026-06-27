import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import AssistantRuntimeProvider from './AssistantRuntimeProvider';

describe('AssistantRuntimeProvider', () => {
  it('renders its children (passthrough)', () => {
    render(
      <AssistantRuntimeProvider>
        <div>child-content</div>
      </AssistantRuntimeProvider>,
    );
    expect(screen.getByText('child-content')).toBeInTheDocument();
  });
});

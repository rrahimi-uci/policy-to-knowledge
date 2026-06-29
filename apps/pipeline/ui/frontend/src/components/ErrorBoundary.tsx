import { Component, Fragment, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
  /** Bumped on reset to force the subtree to remount and re-attempt rendering. */
  resetKey: number;
}

/**
 * Catches render-time errors so a single bad component (e.g. KnowledgeGraph on
 * a malformed payload) shows a recoverable message instead of white-screening
 * the whole app.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, resetKey: 0 };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error('Unhandled UI error:', error, info.componentStack);
  }

  // Clear the error AND bump the key so the subtree remounts fresh — otherwise
  // a child that throws on mount would immediately re-throw and "Try again"
  // would be a no-op.
  reset = () => this.setState((s) => ({ error: null, resetKey: s.resetKey + 1 }));

  render() {
    const { error, resetKey } = this.state;
    if (!error) return <Fragment key={resetKey}>{this.props.children}</Fragment>;
    return (
      <div
        role="alert"
        className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-8 text-center"
      >
        <h2 className="text-xl font-semibold text-red-400">Something went wrong</h2>
        <pre className="max-w-xl overflow-auto rounded bg-gray-900 p-3 text-left text-xs text-gray-500">
          {error.message}
        </pre>
        <button
          onClick={this.reset}
          className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500"
        >
          Try again
        </button>
      </div>
    );
  }
}

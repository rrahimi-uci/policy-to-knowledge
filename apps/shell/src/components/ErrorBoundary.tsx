import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  /** Optional custom fallback. Receives the error and a reset callback. */
  fallback?: (error: Error, reset: () => void) => ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Catches render-time errors in the subtree so a single bad component (e.g. a
 * page choking on a malformed API payload) shows a recoverable message instead
 * of white-screening the whole suite.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error('Unhandled UI error:', error, info.componentStack);
  }

  reset = () => this.setState({ error: null });

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    if (this.props.fallback) return this.props.fallback(error, this.reset);

    return (
      <div
        role="alert"
        className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-8 text-center"
      >
        <h2 className="text-xl font-semibold text-red-400">Something went wrong</h2>
        <p className="max-w-md text-sm text-gray-400">
          This view hit an unexpected error. You can try again, or use the
          navigation to go elsewhere.
        </p>
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

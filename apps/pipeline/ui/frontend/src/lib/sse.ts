/**
 * Pure reducer for the chat Server-Sent-Events stream.
 *
 * Each call folds one raw line into the running state so the component can stay
 * a thin shell around testable logic. Handles:
 *  - CRLF line endings (trailing \r)
 *  - non-`data:` lines (event:/comments/blank) — ignored
 *  - token events ({ content })
 *  - step events ({ label, status }) including a terminal { status: "done" }
 *    with no label (clears the step indicator)
 *  - error events ({ message })
 */
export interface SSEState {
  content: string;
  currentStep: string | null;
}

export const initialSSEState: SSEState = { content: '', currentStep: null };

export function applySSELine(rawLine: string, state: SSEState): SSEState {
  const line = rawLine.replace(/\r$/, '');
  if (!line.startsWith('data:')) return state;

  const payload = line.slice(line.indexOf(':') + 1).trim();
  if (!payload) return state;

  let data: any;
  try {
    data = JSON.parse(payload);
  } catch {
    return state; // non-JSON data line — skip
  }

  let { content, currentStep } = state;

  if (typeof data.content === 'string' && data.content.length > 0) {
    content += data.content;
  }
  // Step indicator: a "done" status always clears it, even without a label.
  if (data.status === 'done') {
    currentStep = null;
  } else if (data.label !== undefined) {
    currentStep = data.label;
  }
  // Error event: surface the message when there's no token content on the line.
  if (data.message !== undefined && !data.content) {
    content += String(data.message);
  }

  return { content, currentStep };
}

/**
 * Fold a list of raw lines into a running state. Convenience wrapper around
 * {@link applySSELine} used when flushing a buffered chunk.
 */
export function applySSELines(lines: string[], state: SSEState): SSEState {
  return lines.reduce((acc, line) => applySSELine(line, acc), state);
}

export interface SSEChunkResult {
  state: SSEState;
  /** Remaining partial line (no trailing newline yet) to carry into the next chunk. */
  buffer: string;
}

/**
 * Feed a decoded text chunk into the line buffer, applying every COMPLETE line
 * (terminated by '\n') and returning the leftover partial line in `buffer`.
 *
 * Pass `final: true` for the terminal call (stream done) so any trailing line
 * that was NOT newline-terminated is still applied instead of being dropped.
 */
export function feedSSEChunk(
  chunk: string,
  state: SSEState,
  buffer: string,
  final = false,
): SSEChunkResult {
  const combined = buffer + chunk;
  const lines = combined.split('\n');
  const remainder = lines.pop() ?? '';
  let next = applySSELines(lines, state);
  if (final && remainder) {
    next = applySSELine(remainder, next);
    return { state: next, buffer: '' };
  }
  return { state: next, buffer: remainder };
}

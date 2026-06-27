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

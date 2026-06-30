import { describe, it, expect } from 'vitest';
import { applySSELine, feedSSEChunk, initialSSEState, type SSEState } from './sse';

describe('applySSELine', () => {
  it('ignores non-data lines (event:, comments, blanks)', () => {
    let s = initialSSEState;
    s = applySSELine('event: token', s);
    s = applySSELine(': comment', s);
    s = applySSELine('', s);
    expect(s).toEqual(initialSSEState);
  });

  it('accumulates token content across lines', () => {
    let s = initialSSEState;
    s = applySSELine('data: {"content":"Hello "}', s);
    s = applySSELine('data: {"content":"world"}', s);
    expect(s.content).toBe('Hello world');
  });

  it('strips trailing \\r from CRLF streams', () => {
    let s = initialSSEState;
    s = applySSELine('data: {"content":"x"}\r', s);
    expect(s.content).toBe('x');
  });

  it('sets the current step from a label event', () => {
    let s = initialSSEState;
    s = applySSELine('data: {"label":"extracting"}', s);
    expect(s.currentStep).toBe('extracting');
  });

  it('clears the step on a terminal {"status":"done"} WITHOUT a label (regression)', () => {
    let s: SSEState = { content: '', currentStep: 'extracting' };
    s = applySSELine('data: {"status":"done"}', s);
    expect(s.currentStep).toBeNull();
  });

  it('appends an error message when there is no token content', () => {
    let s = initialSSEState;
    s = applySSELine('data: {"message":"boom"}', s);
    expect(s.content).toBe('boom');
  });

  it('ignores malformed JSON data lines', () => {
    let s = initialSSEState;
    s = applySSELine('data: {not json', s);
    expect(s).toEqual(initialSSEState);
  });

  it('does not mutate the input state object', () => {
    const start = { content: 'a', currentStep: null };
    const next = applySSELine('data: {"content":"b"}', start);
    expect(start.content).toBe('a');
    expect(next.content).toBe('ab');
  });
});

describe('feedSSEChunk', () => {
  it('applies only complete lines and carries the partial line in the buffer', () => {
    const r = feedSSEChunk('data: {"content":"Hel', initialSSEState, '');
    // No newline yet — nothing applied, whole chunk buffered.
    expect(r.state.content).toBe('');
    expect(r.buffer).toBe('data: {"content":"Hel');
  });

  it('joins a buffered partial line with the next chunk', () => {
    const r1 = feedSSEChunk('data: {"content":"Hel', initialSSEState, '');
    const r2 = feedSSEChunk('lo"}\n', r1.state, r1.buffer);
    expect(r2.state.content).toBe('Hello');
    expect(r2.buffer).toBe('');
  });

  it('keeps a trailing unterminated line buffered on a non-final chunk', () => {
    const r = feedSSEChunk('data: {"content":"a"}\ndata: {"content":"b"}', initialSSEState, '');
    // Only the first (newline-terminated) line is applied.
    expect(r.state.content).toBe('a');
    expect(r.buffer).toBe('data: {"content":"b"}');
  });

  it('flushes a trailing line with no newline on the FINAL chunk (regression)', () => {
    // A stream that ends without a final '\n' must NOT drop its last token.
    const mid = feedSSEChunk('data: {"content":"a"}\ndata: {"content":"b"}', initialSSEState, '');
    expect(mid.state.content).toBe('a'); // "b" still buffered, not yet applied
    const end = feedSSEChunk('', mid.state, mid.buffer, true);
    expect(end.state.content).toBe('ab');
    expect(end.buffer).toBe('');
  });

  it('does not apply a buffered partial line when final is false', () => {
    const end = feedSSEChunk('', initialSSEState, 'data: {"content":"x"}', false);
    expect(end.state.content).toBe('');
    expect(end.buffer).toBe('data: {"content":"x"}');
  });
});

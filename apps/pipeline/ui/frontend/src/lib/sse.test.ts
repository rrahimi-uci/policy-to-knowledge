import { describe, it, expect } from 'vitest';
import { applySSELine, initialSSEState, type SSEState } from './sse';

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

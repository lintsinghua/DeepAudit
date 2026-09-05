import { describe, expect, it, vi } from 'vitest';
import { parseSSE } from '../sse';
import { AgentStreamHandler } from '../agentStream';

describe('event stream recovery', () => {
  it('preserves events at every possible network split', () => {
    const input = 'id: 7\r\nevent: thinking_token\r\ndata: {"sequence":7,"metadata":{"token":"中文"}}\r\n\r\n';
    for (let i = 0; i <= input.length; i++) {
      const first = parseSSE(input.slice(0, i));
      const second = parseSSE(first.remaining + input.slice(i));
      expect([...first.parsed, ...second.parsed]).toEqual([{type: 'thinking_token', sequence: 7, metadata: {token: '中文'}}]);
      expect(second.remaining).toBe('');
    }
  });
  it('ignores malformed complete records and keeps subsequent records', () => {
    expect(parseSSE('data: broken\n\nevent: heartbeat\ndata: {}\n\n').parsed).toEqual([{type: 'heartbeat'}]);
  });
  it('advances reconnect cursor and suppresses duplicate replay, preserving task_end', () => {
    const onEvent = vi.fn();
    const handler = new AgentStreamHandler('task', {onEvent});
    const internal = handler as unknown as {handleEvent: (event: unknown) => void; options: {afterSequence: number}};
    internal.handleEvent({type: 'info', sequence: 8});
    internal.handleEvent({type: 'info', sequence: 8});
    internal.handleEvent({type: 'task_end', sequence: 8, status: 'completed'});
    expect(onEvent).toHaveBeenCalledTimes(2);
    expect(internal.options.afterSequence).toBe(8);
  });
});

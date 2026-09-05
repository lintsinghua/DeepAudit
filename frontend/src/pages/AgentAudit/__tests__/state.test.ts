import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useAgentAuditState } from '../hooks/useAgentAuditState';

describe('streamed findings', () => {
  it('normalizes a partial event before it reaches the findings UI', () => {
    const { result } = renderHook(() => useAgentAuditState());
    act(() => result.current.dispatch({
      type: 'ADD_FINDING',
      payload: { id: 'finding-1', task_id: 'task-1', title: 'SQL injection' },
    }));
    expect(result.current.findings[0]).toMatchObject({
      id: 'finding-1', task_id: 'task-1', title: 'SQL injection',
      status: 'new', is_verified: false, has_poc: false,
      description: null, file_path: null, line_start: null,
    });
    expect(Object.values(result.current.findings[0])).not.toContain(undefined);
  });

  it('preserves supplied values and deduplicates repeated events', () => {
    const { result } = renderHook(() => useAgentAuditState());
    act(() => {
      const payload = {
        id: 'finding-1', ai_confidence: 0, is_verified: true,
        has_poc: true, poc_code: 'proof', severity: 'critical',
      };
      result.current.dispatch({ type: 'ADD_FINDING', payload });
      result.current.dispatch({ type: 'ADD_FINDING', payload });
    });
    expect(result.current.findings).toHaveLength(1);
    expect(result.current.findings[0]).toMatchObject({
      ai_confidence: 0, is_verified: true, has_poc: true,
      poc_code: 'proof', severity: 'critical',
    });
  });
});

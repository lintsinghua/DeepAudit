import { parseSSE as parseEventStream } from "@/shared/api/sse";
/**
 * Resilient Stream Hook
 * Enhanced stream connection with automatic reconnection, heartbeat monitoring,
 * and exponential backoff
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { StreamOptions, StreamEventData } from '@/shared/api/agentStream';

// ============ Types ============

export type ConnectionState =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'failed';

export interface ResilientStreamConfig {
  maxReconnectAttempts?: number;
  initialReconnectDelay?: number;
  maxReconnectDelay?: number;
  heartbeatTimeout?: number;
  jitterFactor?: number;
}

export interface ResilientStreamState {
  connectionState: ConnectionState;
  reconnectAttempts: number;
  lastHeartbeat: Date | null;
  error: string | null;
}

interface UseResilientStreamOptions extends StreamOptions {
  autoConnect?: boolean;
  config?: ResilientStreamConfig;
  onConnectionStateChange?: (state: ConnectionState) => void;
  onReconnect?: (attempt: number) => void;
  onMaxRetriesReached?: () => void;
}

// ============ Default Configuration ============

const DEFAULT_CONFIG: Required<ResilientStreamConfig> = {
  maxReconnectAttempts: 5,
  initialReconnectDelay: 1000,
  maxReconnectDelay: 30000,
  heartbeatTimeout: 45000, // 45 seconds
  jitterFactor: 0.3,
};

// ============ Hook ============

export function useResilientStream(
  taskId: string | null,
  options: UseResilientStreamOptions = {}
) {
  const {
    autoConnect = false,
    config: userConfig,
    onConnectionStateChange,
    onReconnect,
    onMaxRetriesReached,
    ...streamOptions
  } = options;

  const config = { ...DEFAULT_CONFIG, ...userConfig };

  // State
  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected');
  const [reconnectAttempts, setReconnectAttempts] = useState(0);
  const [lastHeartbeat, setLastHeartbeat] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);

  // Refs
  const abortControllerRef = useRef<AbortController | null>(null);
  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const streamOptionsRef = useRef(streamOptions);
  const isDisconnectingRef = useRef(false);
  const cursorRef = useRef({ taskId, sequence: streamOptions.afterSequence ?? 0 });
  if (cursorRef.current.taskId !== taskId) {
    cursorRef.current = { taskId, sequence: streamOptions.afterSequence ?? 0 };
  }

  // Update refs when options change
  streamOptionsRef.current = streamOptions;

  // ============ Connection State Management ============

  const updateConnectionState = useCallback((newState: ConnectionState) => {
    setConnectionState(newState);
    setIsConnected(newState === 'connected');
    onConnectionStateChange?.(newState);
  }, [onConnectionStateChange]);

  // ============ Heartbeat Monitoring ============

  const resetHeartbeatTimer = useCallback(() => {
    if (heartbeatTimeoutRef.current) {
      clearTimeout(heartbeatTimeoutRef.current);
    }

    heartbeatTimeoutRef.current = setTimeout(() => {
      console.warn('[ResilientStream] Heartbeat timeout - connection may be stale');
      // Trigger reconnection
      if (!isDisconnectingRef.current && connectionState === 'connected') {
        handleReconnect();
      }
    }, config.heartbeatTimeout);
  }, [config.heartbeatTimeout, connectionState]);

  const handleHeartbeat = useCallback(() => {
    setLastHeartbeat(new Date());
    resetHeartbeatTimer();
  }, [resetHeartbeatTimer]);

  // ============ Reconnection Logic ============

  const calculateReconnectDelay = useCallback((attempt: number): number => {
    // Exponential backoff with jitter
    const baseDelay = config.initialReconnectDelay * Math.pow(2, attempt);
    const cappedDelay = Math.min(baseDelay, config.maxReconnectDelay);
    const jitter = cappedDelay * config.jitterFactor * (Math.random() - 0.5) * 2;
    return Math.round(cappedDelay + jitter);
  }, [config.initialReconnectDelay, config.maxReconnectDelay, config.jitterFactor]);

  const handleReconnect = useCallback(() => {
    if (isDisconnectingRef.current) return;

    const newAttempt = reconnectAttempts + 1;

    if (newAttempt > config.maxReconnectAttempts) {
      console.error('[ResilientStream] Max reconnect attempts reached');
      updateConnectionState('failed');
      setError('Maximum reconnection attempts reached');
      onMaxRetriesReached?.();
      return;
    }

    updateConnectionState('reconnecting');
    setReconnectAttempts(newAttempt);
    onReconnect?.(newAttempt);

    const delay = calculateReconnectDelay(newAttempt - 1);
    console.log(`[ResilientStream] Reconnecting in ${delay}ms (attempt ${newAttempt}/${config.maxReconnectAttempts})`);

    reconnectTimeoutRef.current = setTimeout(() => {
      if (!isDisconnectingRef.current) {
        connectInternal();
      }
    }, delay);
  }, [reconnectAttempts, config.maxReconnectAttempts, calculateReconnectDelay, onReconnect, onMaxRetriesReached, updateConnectionState]);

  // ============ SSE Parsing ============

  const parseSSE = useCallback((buffer: string): { parsed: StreamEventData[]; remaining: string } => {
    return parseEventStream(buffer);
  }, []);

  // ============ Event Handling ============

  const handleEvent = useCallback((event: StreamEventData) => {
    if (typeof event.sequence === 'number' && event.type !== 'task_end') {
      if (event.sequence <= cursorRef.current.sequence) return;
      cursorRef.current.sequence = event.sequence;
    }
    const opts = streamOptionsRef.current;

    // Extract agent_name from metadata
    if (event.metadata?.agent_name && !event.agent_name) {
      event.agent_name = event.metadata.agent_name as string;
    }

    // General callback
    opts.onEvent?.(event);

    switch (event.type) {
      case 'thinking_start':
        opts.onThinkingStart?.();
        break;

      case 'thinking_token': {
        const token = event.token || (event.metadata?.token as string);
        const accumulated = event.accumulated || (event.metadata?.accumulated as string) || '';
        if (token) {
          opts.onThinkingToken?.(token, accumulated);
        }
        break;
      }

      case 'thinking_end': {
        const fullResponse = event.accumulated || (event.metadata?.accumulated as string) || '';
        opts.onThinkingEnd?.(fullResponse);
        break;
      }

      case 'tool_call_start':
        if (event.tool) {
          opts.onToolStart?.(event.tool.name, event.tool.input || {});
        }
        break;

      case 'tool_call_end':
        if (event.tool) {
          opts.onToolEnd?.(event.tool.name, event.tool.output, event.tool.duration_ms || 0);
        }
        break;

      case 'tool_call':
        opts.onToolStart?.(event.tool_name || 'unknown', event.tool_input || {});
        break;

      case 'tool_result':
        opts.onToolEnd?.(event.tool_name || 'unknown', event.tool_output, event.tool_duration_ms || 0);
        break;

      case 'node_start':
        opts.onNodeStart?.(
          event.metadata?.node as string || 'unknown',
          event.phase || ''
        );
        break;

      case 'node_end':
        opts.onNodeEnd?.(
          event.metadata?.node as string || 'unknown',
          event.metadata?.summary as Record<string, unknown> || {}
        );
        break;

      case 'finding_new':
      case 'finding_verified':
        opts.onFinding?.(event.metadata || {}, event.type === 'finding_verified');
        break;

      case 'progress':
        opts.onProgress?.(
          event.metadata?.current as number || 0,
          event.metadata?.total as number || 100,
          event.message || ''
        );
        break;

      case 'task_complete':
      case 'task_end':
        if (event.status !== 'cancelled' && event.status !== 'failed') {
          opts.onComplete?.({
            findingsCount: event.findings_count || event.metadata?.findings_count as number || 0,
            securityScore: event.security_score || event.metadata?.security_score as number || 100,
          });
        }
        disconnectInternal();
        break;

      case 'task_error':
      case 'error':
        opts.onError?.(event.error || event.message || 'Unknown error');
        disconnectInternal();
        break;

      case 'heartbeat':
        handleHeartbeat();
        opts.onHeartbeat?.();
        break;
    }
  }, [handleHeartbeat]);

  // ============ Connection ============

  const connectInternal = useCallback(async () => {
    if (!taskId || isDisconnectingRef.current) return;

    const token = localStorage.getItem('access_token') || sessionStorage.getItem('access_token');
    if (!token) {
      setError('Not authenticated');
      updateConnectionState('failed');
      return;
    }

    updateConnectionState('connecting');

    const params = new URLSearchParams({
      include_thinking: String(streamOptionsRef.current.includeThinking ?? true),
      include_tool_calls: String(streamOptionsRef.current.includeToolCalls ?? true),
      after_sequence: String(Math.max(cursorRef.current.sequence, streamOptionsRef.current.afterSequence ?? 0)),
    });

    const url = `/api/v1/agent-tasks/${taskId}/stream?${params}`;
    abortControllerRef.current = new AbortController();

    try {
      const response = await fetch(url, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Accept': 'text/event-stream',
        },
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      updateConnectionState('connected');
      setReconnectAttempts(0);
      setError(null);
      resetHeartbeatTimer();

      readerRef.current = response.body?.getReader() || null;
      if (!readerRef.current) {
        throw new Error('Unable to get response stream');
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        if (isDisconnectingRef.current) break;

        const { done, value } = await readerRef.current.read();
        if (done) {
          if (!isDisconnectingRef.current) throw new Error('事件连接已中断');
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const events = parseSSE(buffer);
        buffer = events.remaining;

        for (const event of events.parsed) {
          handleEvent(event);
          // Small delay for thinking tokens to allow smooth rendering
          if (event.type === 'thinking_token') {
            await new Promise(resolve => setTimeout(resolve, 5));
          }
        }
      }

      if (readerRef.current) {
        readerRef.current.releaseLock();
        readerRef.current = null;
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        return;
      }

      console.error('[ResilientStream] Connection error:', err);
      updateConnectionState('disconnected');

      if (!isDisconnectingRef.current) {
        handleReconnect();
      }
    } finally {
      if (heartbeatTimeoutRef.current) {
        clearTimeout(heartbeatTimeoutRef.current);
      }
      if (readerRef.current) {
        try {
          readerRef.current.releaseLock();
        } catch {
          // Ignore
        }
        readerRef.current = null;
      }
    }
  }, [taskId, updateConnectionState, resetHeartbeatTimer, parseSSE, handleEvent, handleReconnect]);

  const disconnectInternal = useCallback(() => {
    isDisconnectingRef.current = true;
    updateConnectionState('disconnected');

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    if (readerRef.current) {
      try {
        readerRef.current.cancel();
        readerRef.current.releaseLock();
      } catch {
        // Ignore
      }
      readerRef.current = null;
    }

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (heartbeatTimeoutRef.current) {
      clearTimeout(heartbeatTimeoutRef.current);
      heartbeatTimeoutRef.current = null;
    }

    setReconnectAttempts(0);
  }, [updateConnectionState]);

  // ============ Public API ============

  const connect = useCallback(() => {
    isDisconnectingRef.current = false;
    setError(null);
    connectInternal();
  }, [connectInternal]);

  const disconnect = useCallback(() => {
    disconnectInternal();
  }, [disconnectInternal]);

  const resetConnection = useCallback(() => {
    disconnectInternal();
    setReconnectAttempts(0);
    setError(null);
    isDisconnectingRef.current = false;
  }, [disconnectInternal]);

  // ============ Effects ============

  // Auto-connect
  useEffect(() => {
    if (autoConnect && taskId) {
      connect();
    }
    return () => {
      disconnectInternal();
    };
  }, [taskId, autoConnect]);

  // Cleanup
  useEffect(() => {
    return () => {
      isDisconnectingRef.current = true;
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (heartbeatTimeoutRef.current) {
        clearTimeout(heartbeatTimeoutRef.current);
      }
    };
  }, []);

  return {
    // Connection control
    connect,
    disconnect,
    resetConnection,

    // State
    connectionState,
    isConnected,
    reconnectAttempts,
    maxReconnectAttempts: config.maxReconnectAttempts,
    lastHeartbeat,
    error,

    // Computed
    isReconnecting: connectionState === 'reconnecting',
    isFailed: connectionState === 'failed',
  };
}

export default useResilientStream;

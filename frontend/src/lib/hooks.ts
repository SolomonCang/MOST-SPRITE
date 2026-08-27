import { useEffect, useRef, useState } from "react";
import { WS_URL } from "./api";
import type { StateEvent } from "./types";

export function useUtcClock(): string {
  const [value, setValue] = useState(() => new Date().toISOString());
  useEffect(() => {
    const timer = window.setInterval(() => setValue(new Date().toISOString()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return value;
}

export function useStateStream(sequenceId?: string): {
  events: StateEvent[];
  connected: boolean;
} {
  const [events, setEvents] = useState<StateEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const cursor = useRef(0);

  useEffect(() => {
    let socket: WebSocket | undefined;
    let retryTimer: number | undefined;
    let stopped = false;

    const connect = () => {
      socket = new WebSocket(`${WS_URL}/ws/v1/state?cursor=${cursor.current}`);
      socket.onopen = () => setConnected(true);
      socket.onmessage = (message) => {
        const event = JSON.parse(message.data as string) as StateEvent;
        cursor.current = Math.max(cursor.current, event.cursor ?? 0);
        if (event.event_type === "heartbeat.v1") return;
        if (sequenceId && event.sequence_id && event.sequence_id !== sequenceId) return;
        setEvents((current) => [...current.slice(-99), event]);
      };
      socket.onclose = () => {
        setConnected(false);
        if (!stopped) retryTimer = window.setTimeout(connect, 1500);
      };
      socket.onerror = () => socket?.close();
    };

    connect();
    return () => {
      stopped = true;
      if (retryTimer) window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, [sequenceId]);

  return { events, connected };
}

"use client";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { API, type FactoryEvent } from "./api";
import { useFactory } from "./store";

/** One SSE connection for the whole app; events fan into the Zustand store, and queries are
 *  invalidated (throttled) so every screen stays live without polling storms. */
export function useEventStream() {
  const qc = useQueryClient();
  const push = useFactory((s) => s.push);
  const setConnected = useFactory((s) => s.setConnected);
  const buf = useRef<FactoryEvent[]>([]);
  const dirty = useRef(false);

  useEffect(() => {
    let es: EventSource | null = null;
    let retry: any;
    const connect = () => {
      es = new EventSource(`${API}/api/events?replay=200`);
      es.onopen = () => setConnected(true);
      es.onerror = () => {
        setConnected(false);
        es?.close();
        retry = setTimeout(connect, 2000);
      };
      es.onmessage = (m) => {
        try {
          buf.current.push(JSON.parse(m.data));
          dirty.current = true;
        } catch {}
      };
    };
    connect();
    // throttle UI updates to ~10/s for smooth animation
    const flush = setInterval(() => {
      if (buf.current.length) {
        push(buf.current);
        buf.current = [];
      }
    }, 100);
    const inval = setInterval(() => {
      if (dirty.current) {
        dirty.current = false;
        qc.invalidateQueries();
      }
    }, 1200);
    return () => {
      es?.close();
      clearTimeout(retry);
      clearInterval(flush);
      clearInterval(inval);
    };
  }, [push, qc, setConnected]);
}

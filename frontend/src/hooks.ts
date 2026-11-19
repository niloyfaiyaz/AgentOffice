import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, type AgentEvent, type Bootstrap, type ProjectState } from "./api";

export function useBootstrap() {
  return useQuery({ queryKey: ["bootstrap"], queryFn: () => api.get<Bootstrap>("/bootstrap"), staleTime: 30_000 });
}

export function useProjectState(pid: string | undefined) {
  return useQuery({
    queryKey: ["state", pid],
    queryFn: () => api.get<ProjectState>(`/projects/${pid}/state`),
    enabled: !!pid,
  });
}

/**
 * Live activity: loads the authoritative snapshot, then follows the SSE stream from the
 * snapshot's last event sequence. On reconnect the browser resends Last-Event-ID, so no
 * event is lost or applied twice. Execution never depends on this connection.
 */
export function useProjectStream(pid: string | undefined, onEvent?: (e: AgentEvent) => void) {
  const qc = useQueryClient();
  const state = useProjectState(pid);
  const [connected, setConnected] = useState(false);
  const [live, setLive] = useState<AgentEvent[]>([]);
  const cb = useRef(onEvent);
  cb.current = onEvent;
  const startSeq = state.data?.last_event_seq;
  const started = startSeq !== undefined;

  useEffect(() => {
    if (!pid || !started) return;
    setLive([]);
    const es = new EventSource(`/api/projects/${pid}/stream?after=${startSeq}`);
    let timer: ReturnType<typeof setTimeout> | null = null;
    const refresh = () => {
      if (timer) return;
      timer = setTimeout(() => {
        timer = null;
        for (const k of ["state", "artifacts", "approvals", "costs", "messages", "findings", "agentDetail", "dashboard", "handoffs"])
          qc.invalidateQueries({ queryKey: [k] });
      }, 400);
    };
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.addEventListener("agent_event", (m) => {
      const ev = JSON.parse((m as MessageEvent).data) as AgentEvent;
      setLive((l) => [...l.slice(-499), ev]);
      cb.current?.(ev);
      refresh();
    });
    return () => {
      es.close();
      if (timer) clearTimeout(timer);
      setConnected(false);
    };
    // Re-subscribe only when the project changes (the snapshot seq is the starting cursor).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid, started]);

  return { state, connected, live };
}

export function useReducedMotion(): [boolean, (v: boolean) => void] {
  const sys = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const [v, setV] = useState<boolean>(() => {
    try {
      const s = localStorage.getItem("ao.reducedMotion");
      return s === null ? !!sys : s === "1";
    } catch {
      return !!sys;
    }
  });
  return [v, (nv: boolean) => {
    setV(nv);
    try {
      localStorage.setItem("ao.reducedMotion", nv ? "1" : "0");
    } catch {
      /* storage unavailable */
    }
  }];
}

/** Remembers the last opened project (a per-browser convenience only). */
export function rememberProject(id: string) {
  try {
    localStorage.setItem("ao.lastProject", id);
  } catch {
    /* ignore */
  }
}
export function lastProject(): string | null {
  try {
    return localStorage.getItem("ao.lastProject");
  } catch {
    return null;
  }
}

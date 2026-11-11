"use client";
import { create } from "zustand";
import type { FactoryEvent } from "./api";

type Toast = { id: string; kind: "alert" | "security" | "gate" | "info"; text: string; href?: string };

type State = {
  connected: boolean;
  events: FactoryEvent[];
  activeAgents: Record<string, { agent: string; stage: string; ts: number; summary: string }>;
  toasts: Toast[];
  evidenceToken: string | null;
  setConnected: (v: boolean) => void;
  push: (evts: FactoryEvent[]) => void;
  clear: () => void;
  dismiss: (id: string) => void;
  openEvidence: (t: string | null) => void;
};

export const useFactory = create<State>((set) => ({
  connected: false,
  events: [],
  activeAgents: {},
  toasts: [],
  evidenceToken: null,
  setConnected: (v) => set({ connected: v }),
  clear: () => set({ events: [], activeAgents: {}, toasts: [] }),
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  openEvidence: (t) => set({ evidenceToken: t }),
  push: (evts) =>
    set((s) => {
      const seen = new Set(s.events.slice(-400).map((e) => e.id));
      const fresh = evts.filter((e) => !seen.has(e.id));
      if (!fresh.length) return s;
      const events = [...s.events, ...fresh].slice(-600);
      const activeAgents = { ...s.activeAgents };
      let toasts = s.toasts;
      for (const e of fresh) {
        if (e.model_id && (e.type === "tool_call" || e.type === "stage_started")) {
          activeAgents[e.model_id] = { agent: e.agent, stage: e.stage, ts: Date.now(), summary: e.summary };
        }
        if (e.model_id && (e.type === "run_completed" || e.type === "gate_requested")) delete activeAgents[e.model_id];
        const live = Date.now() - new Date(e.ts).getTime() < 8000;
        if (live && (e.type === "alert" || e.type === "security" || e.type === "gate_requested")) {
          const kind = e.type === "gate_requested" ? "gate" : (e.type as Toast["kind"]);
          const href = e.type === "gate_requested" ? "/approvals" : e.type === "security" ? "/responsible-ai" : e.stage === "monitor" ? "/monitoring" : undefined;
          toasts = [...toasts, { id: e.id, kind, text: e.summary, href }].slice(-4);
        }
      }
      return { events, activeAgents, toasts };
    }),
}));

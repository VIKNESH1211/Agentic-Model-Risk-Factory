"use client";
import { create } from "zustand";
import type { FactoryEvent } from "./api";

export type Toast = { id: string; kind: "alert" | "security" | "gate" | "info" | "success" | "error"; text: string; href?: string };

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
  toast: (t: Omit<Toast, "id">) => void;
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
  toast: (t) => set((s) => ({ toasts: [...s.toasts, { ...t, id: `t${Date.now()}${Math.random()}` }].slice(-5) })),
  openEvidence: (t) => set({ evidenceToken: t }),
  push: (evts) =>
    set((s) => {
      const seen = new Set(s.events.slice(-500).map((e) => e.id));
      const fresh = evts.filter((e) => !seen.has(e.id));
      if (!fresh.length) return s;
      const events = [...s.events, ...fresh].slice(-800);
      const activeAgents = { ...s.activeAgents };
      let toasts = s.toasts;
      for (const e of fresh) {
        if (e.model_id && ["tool_call", "stage_started", "agent_step"].includes(e.type)) {
          activeAgents[e.model_id] = { agent: e.agent, stage: e.stage, ts: Date.now(), summary: e.summary };
        }
        if (e.model_id && (e.type === "run_completed" || e.type === "gate_requested" || e.type === "stage_completed")) delete activeAgents[e.model_id];
        const live = Date.now() - new Date(e.ts).getTime() < 8000;
        if (live && (e.type === "alert" || e.type === "security" || e.type === "gate_requested")) {
          const kind = e.type === "gate_requested" ? "gate" : (e.type as Toast["kind"]);
          const href = e.type === "gate_requested" ? "/approvals" : e.type === "security" ? "/governance"
            : e.stage === "monitor" ? `/monitoring?model=${e.model_id}` : e.run_id ? `/agents?run=${e.run_id}` : undefined;
          toasts = [...toasts, { id: e.id, kind, text: e.summary, href }].slice(-5);
        }
      }
      return { events, activeAgents, toasts };
    }),
}));

export const toast = (t: Omit<Toast, "id">) => useFactory.getState().toast(t);

export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8100";

export async function get<T = any>(path: string): Promise<T> {
  const r = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export async function post<T = any>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export type FactoryEvent = {
  id: string;
  ts: string;
  run_id: string;
  model_id: string;
  stage: string;
  agent: string;
  type: string;
  summary: string;
  payload: Record<string, any>;
};

export type TokenInfo = { value: number | null; display: string; ok: boolean; definition?: string };

export const STATIONS = ["discover", "document", "redevelop", "validate", "monitor"] as const;
export const STATION_LABEL: Record<string, string> = {
  discover: "Discover",
  document: "Document",
  redevelop: "Redevelop",
  validate: "Validate",
  monitor: "Monitor",
};

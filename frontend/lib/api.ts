export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8100";

export class ApiError extends Error {
  status: number;
  detail: any;
  constructor(status: number, detail: any) {
    super(typeof detail === "string" ? detail : detail?.lint ? detail.lint.join("\n") : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

async function handle<T>(r: Response): Promise<T> {
  if (r.ok) return r.json();
  let detail: any = await r.text();
  try {
    detail = JSON.parse(detail).detail ?? JSON.parse(detail);
  } catch {}
  throw new ApiError(r.status, detail);
}

const json = (method: string) => async <T = any>(path: string, body?: unknown): Promise<T> =>
  handle<T>(await fetch(`${API}${path}`, {
    method, headers: { "content-type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body),
  }));

export async function get<T = any>(path: string): Promise<T> {
  return handle<T>(await fetch(`${API}${path}`, { cache: "no-store" }));
}
export const post = json("POST");
export const put = json("PUT");
export const patch = json("PATCH");
export const del = json("DELETE");

/** multipart upload: files under `field`, plus plain form fields */
export async function upload<T = any>(path: string, files: File[], fields: Record<string, string | boolean> = {}, field = "files"): Promise<T> {
  const fd = new FormData();
  files.forEach((f) => fd.append(field, f));
  Object.entries(fields).forEach(([k, v]) => fd.append(k, String(v)));
  return handle<T>(await fetch(`${API}${path}`, { method: "POST", body: fd }));
}

export type FactoryEvent = {
  id: string; ts: string; run_id: string; model_id: string; stage: string; agent: string; type: string; summary: string;
  payload: Record<string, any>;
};

export type TokenInfo = { value: number | null; display: string; ok: boolean; definition?: string };

export const STATIONS = ["discover", "document", "redevelop", "validate", "monitor"] as const;
export const STATION_LABEL: Record<string, string> = {
  discover: "Intake", document: "Document & plan", redevelop: "Redevelop", validate: "Validate", monitor: "Monitor",
};
export const STAGE_LABEL: Record<string, string> = {
  onboarded: "Onboarded", queued: "Queued", discover: "Intake", gate_document: "Spec approval", document: "Documentation & planning",
  gate_redevelop: "Plan approval", redevelop: "Redevelopment", gate_validate: "Certificate approval", validate: "Validation",
  report: "Report", gate_deploy: "Deploy approval", monitor_setup: "Deployment", monitor: "Monitoring", diagnose: "Alert diagnosis",
  gate_accept: "Re-validation acceptance",
};

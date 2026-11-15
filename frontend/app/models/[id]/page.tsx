"use client";
import { useQuery } from "@tanstack/react-query";
import { Activity, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { DocView, FilesView, FindingsView, Overview, ParityView, RunsView } from "@/components/workspace/Tabs";
import { MonitoringPlanEditor, ValidationPlanEditor } from "@/components/workspace/PlanEditor";
import { SpecEditor } from "@/components/workspace/SpecEditor";
import { Badge, CodeBlock, Dot, Empty, PageHeader, Panel, Tabs, Tag } from "@/components/ui";
import { del, get } from "@/lib/api";
import { toast } from "@/lib/store";

type Tab = "overview" | "spec" | "contract" | "docs" | "validation" | "monitoring" | "parity" | "findings" | "runs" | "files";

function Contract({ modelId }: { modelId: string }) {
  const q = useQuery({ queryKey: ["contract", modelId], queryFn: () => get(`/api/models/${modelId}/contract`), retry: false });
  if (q.isError) return <Panel><Empty title="No contract yet">Rendered from the specification once intake has drafted it.</Empty></Panel>;
  if (!q.data) return <div className="text-muted">Loading…</div>;
  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
      <Panel title={`Interface contract · spec v${q.data.version} (${q.data.status})`}>
        <p className="text-sm text-muted mb-3">Generated from the specification (a prompt template in the Library) — the contract every agent and the parity check work to.</p>
        <CodeBlock code={q.data.contract} lineNo={false} maxH={640} />
      </Panel>
      <Panel title="Certified R export epilogue">
        <p className="text-sm text-muted mb-3">Agent-written R that runs after the unmodified legacy script and exports the standard bundle (frame · scores · coef · train rows).</p>
        {q.data.epilogue ? <CodeBlock code={q.data.epilogue} lang="r" /> : <div className="text-sm text-muted">Not certified yet.</div>}
      </Panel>
    </div>
  );
}

function Workspace() {
  const { id } = useParams<{ id: string }>();
  const sp = useSearchParams();
  const router = useRouter();
  const [tab, setTabState] = useState<Tab>((sp.get("tab") as Tab) || "overview");
  const setTab = (t: Tab) => { setTabState(t); router.replace(`/models/${id}?tab=${t}`, { scroll: false }); };
  const q = useQuery({ queryKey: ["model", id], queryFn: () => get(`/api/models/${id}`), refetchInterval: 4000, retry: false });
  const [armed, setArmed] = useState(false);
  if (q.isError) return <Panel><Empty title={`Model ${id} not found`} action={<Link className="btn btn-primary" href="/models">All models</Link>} /></Panel>;
  const d = q.data;
  if (!d) return <div className="text-muted">Loading…</div>;
  const m = d.model;
  const meta = m.meta || {};
  const highs = d.findings.filter((f: any) => f.severity === "high").length;
  const remove = async () => {
    if (!armed) return setArmed(true);
    await del(`/api/models/${id}`);
    toast({ kind: "success", text: `${id} deleted` });
    router.push("/models");
  };
  const tabs = [
    { id: "overview", label: "Overview" }, { id: "spec", label: "Spec", badge: d.spec ? <Tag tone={d.spec.status === "approved" ? "teal" : "warn"}>v{d.spec.version}</Tag> : undefined },
    { id: "contract", label: "Contract" }, { id: "docs", label: "Documentation" }, { id: "validation", label: "Validation plan" },
    { id: "monitoring", label: "Monitoring plan" }, { id: "parity", label: "Parity" },
    { id: "findings", label: "Findings", badge: d.findings.length ? <span className={highs ? "text-fail text-xs" : "text-muted text-xs"}>{d.findings.length}</span> : undefined },
    { id: "runs", label: "Runs & agent log" }, { id: "files", label: "Files" },
  ] as { id: Tab; label: string; badge?: React.ReactNode }[];
  return (
    <div className="space-y-5 max-w-[1700px] mx-auto">
      <PageHeader crumbs={[{ href: "/models", label: "Models" }, { label: m.id }]}
        title={<span className="flex items-center gap-3 flex-wrap"><span className="mono">{m.id}</span><span className="text-muted font-semibold text-xl">{m.name !== m.id ? m.name : ""}</span>
          {m.tier && <Tag tone={m.tier === "A" ? "warn" : "muted"}>Tier {m.tier}</Tag>}
          {meta.parity_verdict && <Badge kind={meta.parity_verdict === "PASS" ? "PASS" : "warn"} label={meta.parity_verdict} />}
          {meta.deployed && <span className="flex items-center gap-1.5 text-sm text-pass"><Dot tone="pass" pulse /> live</span>}</span>}
        sub={m.type ? `${m.type}${m.owner ? ` · ${m.owner}` : ""}` : m.description}
        actions={<>
          {meta.deployed && <Link className="btn" href={`/monitoring?model=${m.id}`}><Activity size={15} /> Live dashboard</Link>}
          <button className={armed ? "btn btn-danger" : "btn"} onClick={remove} onBlur={() => setArmed(false)}><Trash2 size={15} /> {armed ? "Click again to delete" : "Delete"}</button>
        </>} />
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {tab === "overview" && <Overview d={d} setTab={setTab} />}
      {tab === "spec" && <SpecEditor modelId={id} />}
      {tab === "contract" && <Contract modelId={id} />}
      {tab === "docs" && <DocView d={d} />}
      {tab === "validation" && <ValidationPlanEditor modelId={id} />}
      {tab === "monitoring" && <MonitoringPlanEditor modelId={id} />}
      {tab === "parity" && <ParityView modelId={id} />}
      {tab === "findings" && <FindingsView modelId={id} />}
      {tab === "runs" && <RunsView d={d} initial={sp.get("run") || undefined} />}
      {tab === "files" && <FilesView modelId={id} files={d.files} />}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<div className="text-muted">Loading…</div>}><Workspace /></Suspense>;
}

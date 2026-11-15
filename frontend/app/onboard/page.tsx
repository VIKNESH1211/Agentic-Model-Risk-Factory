"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight, CheckCircle2, Database, FileCode2, FileText, Loader2, PackagePlus, Upload, X } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";
import { AgentTrace } from "@/components/AgentTrace";
import { Field, PageHeader, Panel, Tag, inputCls } from "@/components/ui";
import { get, upload } from "@/lib/api";
import { toast } from "@/lib/store";

function Drop({ onFiles, accept, children, multiple = true }: { onFiles: (f: File[]) => void; accept?: string; children: React.ReactNode; multiple?: boolean }) {
  const [over, setOver] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); onFiles(Array.from(e.dataTransfer.files)); }}
      onClick={() => ref.current?.click()}
      className={clsx("cursor-pointer rounded-xl border-2 border-dashed p-6 text-center transition", over ? "border-teal bg-teal/[.06]" : "border-line hover:border-line-strong hover:bg-slate-900/[.02]")}>
      <input ref={ref} type="file" multiple={multiple} accept={accept} className="hidden" onChange={(e) => onFiles(Array.from(e.target.files || []))} />
      {children}
    </div>
  );
}

const kind = (f: File) => (f.name.toLowerCase().endsWith(".r") ? "script" : f.name.endsWith(".py") ? "reference" : f.name.endsWith(".csv") ? "data" : "doc");
const ICON: Record<string, any> = { script: FileCode2, reference: FileCode2, data: Database, doc: FileText };

export default function Onboard() {
  const qc = useQueryClient();
  const [files, setFiles] = useState<File[]>([]);
  const [form, setForm] = useState({ model_id: "", owner: "", description: "" });
  const [result, setResult] = useState<any>(null);
  const room = useQuery({ queryKey: ["data-room"], queryFn: () => get<any[]>("/api/data-room") });
  const add = (fs: File[]) => setFiles((cur) => [...cur.filter((c) => !fs.some((f) => f.name === c.name)), ...fs]);
  const scripts = files.filter((f) => kind(f) === "script");
  const data = files.filter((f) => kind(f) === "data");
  const modelFiles = files.filter((f) => kind(f) !== "data");
  const submit = useMutation({
    mutationFn: async (start: boolean) => {
      for (const d of data) await upload("/api/data-room", [d], {}, "file");
      return upload("/api/models", modelFiles, { ...form, start });
    },
    onSuccess: (r: any) => { setResult(r); qc.invalidateQueries(); toast({ kind: "success", text: `${r.model.id} onboarded${r.run ? " — intake agent started" : ""}` }); },
    onError: (e: any) => toast({ kind: "error", text: e.message }),
  });
  const gate = useQuery({ queryKey: ["onboard-gate", result?.model?.id], enabled: !!result?.run, refetchInterval: 2500,
    queryFn: () => get<any[]>(`/api/gates?model_id=${result.model.id}&status=pending`) });
  const specReady = (gate.data || []).some((g) => g.stage === "gate_document");

  if (result) {
    const mid = result.model.id;
    return (
      <div className="space-y-5 max-w-[1400px] mx-auto">
        <PageHeader crumbs={[{ href: "/models", label: "Models" }, { label: mid }]} title={<>Onboarded <span className="mono text-teal">{mid}</span></>}
          sub={result.run ? "The intake agent is running the script in the sandbox, probing what it creates, and drafting the specification." : "Uploaded. Start the factory when you're ready."}
          actions={<>
            <Link className="btn" href={`/models/${mid}`}>Open workspace</Link>
            {specReady && <Link className="btn btn-primary" href={`/models/${mid}?tab=spec`}>Review the drafted spec <ArrowRight size={15} /></Link>}
          </>} />
        {specReady && (
          <div className="panel glow-teal px-5 py-4 flex items-center gap-3">
            <CheckCircle2 className="text-pass" /> <div className="flex-1"><b>Spec drafted.</b> Review it, edit anything that's wrong, then approve it to promote the model to documentation.</div>
            <Link className="btn btn-primary" href={`/models/${mid}?tab=spec`}>Review spec</Link>
          </div>
        )}
        {result.run && <AgentTrace runId={result.run.id} live={!specReady} height={620} />}
        <button className="btn" onClick={() => { setResult(null); setFiles([]); setForm({ model_id: "", owner: "", description: "" }); }}>Onboard another model</button>
      </div>
    );
  }

  return (
    <div className="space-y-5 max-w-[1200px] mx-auto">
      <PageHeader title="Onboard a legacy model" crumbs={[{ href: "/models", label: "Models" }, { label: "Onboard" }]}
        sub="Upload any R model as it exists today — unmodified. Nothing about it needs to be configured: the intake agent runs it, works out what it is and drafts a specification you approve." />
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_380px] gap-5">
        <div className="space-y-5">
          <Panel title="1 · Files">
            <Drop onFiles={add}>
              <Upload className="mx-auto text-teal" />
              <div className="mt-2 font-semibold">Drop the R script(s) here, or click to browse</div>
              <div className="text-sm text-muted mt-1">Also accepted: a reference Python translation (<code>.py</code>, optional fallback), documents, and data files (<code>.csv</code> → data room)</div>
            </Drop>
            {files.length > 0 && (
              <ul className="mt-3 divide-y divide-line rounded-lg border border-line">
                {files.map((f) => {
                  const k = kind(f);
                  const I = ICON[k];
                  return (
                    <li key={f.name} className="flex items-center gap-3 px-3 py-2 text-sm">
                      <I size={16} className={k === "data" ? "text-info" : "text-teal"} /> <span className="mono flex-1 truncate">{f.name}</span>
                      <Tag tone={k === "script" ? "teal" : k === "data" ? "muted" : "agent"}>{k === "data" ? "→ data room" : k}</Tag>
                      <span className="text-xs text-faint w-20 text-right">{(f.size / 1024).toFixed(1)} KB</span>
                      <button onClick={() => setFiles(files.filter((x) => x !== f))} aria-label={`remove ${f.name}`}><X size={15} className="text-muted" /></button>
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>
          <Panel title="2 · What you know (all optional)">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Field label="Model id" hint="Leave blank: taken from the script header (e.g. CR-001) or the file name">
                <input className={inputCls} value={form.model_id} onChange={(e) => setForm({ ...form, model_id: e.target.value })} placeholder="auto" />
              </Field>
              <Field label="Owner"><input className={inputCls} value={form.owner} onChange={(e) => setForm({ ...form, owner: e.target.value })} placeholder="e.g. Retail Credit Risk Analytics" /></Field>
              <Field className="md:col-span-2" label="How is it run · what is it for" hint="Anything the batch job passes on the command line helps the agent run it first time.">
                <textarea className={clsx(inputCls, "min-h-[90px]")} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
                  placeholder="e.g. Nightly job: Rscript scorecard.R --train train.csv --score today.csv --outdir out. Retail PD scorecard for unsecured loans." />
              </Field>
            </div>
          </Panel>
          <div className="flex items-center gap-2 justify-end">
            <button className="btn" disabled={!scripts.length || submit.isPending} onClick={() => submit.mutate(false)}>Onboard only</button>
            <button className="btn btn-primary" disabled={!scripts.length || submit.isPending} onClick={() => submit.mutate(true)}>
              {submit.isPending ? <Loader2 size={16} className="animate-spin" /> : <PackagePlus size={16} />} Onboard & start intake
            </button>
          </div>
        </div>
        <div className="space-y-5">
          <Panel title="Data room (shared drive)" right={<Link href="/data-room" className="text-xs text-teal hover:underline">manage</Link>}>
            <p className="text-sm text-muted mb-3">Files legacy scripts read — e.g. <code className="mono">//shared/riskdata/x.csv</code> or a relative path. The agent maps each read to one of these.</p>
            <ul className="space-y-1.5 text-sm">
              {(room.data || []).map((a) => (
                <li key={a.name} className="flex items-center gap-2"><Database size={14} className="text-info shrink-0" /><span className="mono truncate flex-1">{a.name}</span><span className="text-xs text-faint">{a.rows?.toLocaleString()} rows</span></li>
              ))}
              {room.data && !room.data.length && <li className="text-muted">Empty — drop CSVs in the file box to add them.</li>}
            </ul>
          </Panel>
          <Panel title="What happens next">
            <ol className="text-sm space-y-2.5 text-slate-700 list-decimal ml-4">
              <li><b>Intake agent</b> parses the script, runs it unmodified in the no-network sandbox, probes every object it creates, and drafts the <b>spec</b>.</li>
              <li><b>You approve</b> the spec (or edit it, or send it back with a comment).</li>
              <li><b>Documentation agent</b> writes the docs, reviews the code, and proposes a <b>validation plan</b> and a <b>monitoring plan</b> for this model.</li>
              <li><b>Redevelopment agent</b> exports the model's behaviour, rebuilds it in Python and proves parity — or rehosts it.</li>
              <li><b>Validator</b> executes your approved plan, investigates, and writes a report where every number is evidence.</li>
              <li>Deploy: live traffic, dashboards and alerts from the monitoring plan.</li>
            </ol>
          </Panel>
        </div>
      </div>
    </div>
  );
}

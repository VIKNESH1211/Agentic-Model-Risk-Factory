"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Badge, Empty, PageHeader, Panel, Tag, ago } from "@/components/ui";
import { get } from "@/lib/api";

export default function Reports() {
  const q = useQuery({ queryKey: ["reports"], queryFn: () => get<any[]>("/api/reports"), refetchInterval: 5000 });
  return (
    <div className="space-y-5 max-w-[1400px] mx-auto">
      <PageHeader title="Validation reports" sub="Written by the report agent from each validation run. Every number is a token that resolves to a stored, reproducible metric; the unsourced-number checker rejects anything else." />
      <Panel pad={false}>
        {q.isSuccess && !q.data.length ? <Empty title="No reports yet">Reports are drafted at the end of the validation stage.</Empty> : (
          <table className="w-full text-[14.5px]">
            <thead><tr className="text-left text-xs uppercase tracking-wider text-muted border-b border-line"><th className="px-5 py-3">Report</th><th>Model</th><th>Version</th><th>Run</th><th>Traceable numbers</th><th>Checker</th><th className="pr-5">Drafted</th></tr></thead>
            <tbody>{(q.data || []).map((r) => (
              <tr key={r.id} className="border-b border-line/60 hover:bg-slate-900/[.02]">
                <td className="px-5 py-3"><Link href={`/reports/${r.id}`} className="hover:text-teal font-medium">{r.title}</Link></td>
                <td><Link href={`/models/${r.model_id}`} className="mono text-teal">{r.model_id}</Link></td>
                <td><Tag>v{r.version}</Tag></td><td className="mono text-xs text-muted">{r.run_id}</td>
                <td className="num">{r.tokens}</td><td>{r.checker_ok ? <Badge kind="pass" label="clean" /> : <Badge kind="fail" label="unsourced" />}</td>
                <td className="pr-5 text-muted text-sm">{ago(r.created_at)}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}

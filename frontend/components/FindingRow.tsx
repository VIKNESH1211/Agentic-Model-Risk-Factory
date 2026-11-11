"use client";
import { Ev } from "./Evidence";
import { Badge, Tag } from "./ui";

export function FindingRow({ f }: { f: any }) {
  return (
    <div className="border-b border-line/60 py-3.5">
      <div className="flex items-start gap-3">
        <span className="mono text-muted pt-0.5 w-12 shrink-0">{f.code}</span>
        <Badge kind={f.severity} />
        <div className="flex-1 min-w-0">
          <div className="font-semibold">{f.title}</div>
          <div className="text-muted text-[15px] mt-0.5">{f.detail}</div>
          <div className="flex flex-wrap items-center gap-2 mt-2 text-sm">
            <Tag tone="agent">{f.detector}</Tag>
            <Tag>{f.category}</Tag>
            {(f.evidence?.tokens || []).map((t: string) => <Ev key={t} token={t} />)}
            {f.evidence?.line && <span className="mono text-xs text-muted">{f.evidence.file}:{f.evidence.line}</span>}
          </div>
          {f.evidence?.code && <pre className="mono text-[12.5px] mt-2 bg-black/30 border border-line rounded-md px-3 py-2 overflow-x-auto scroll-thin text-warn/90">{f.evidence.code}</pre>}
        </div>
      </div>
    </div>
  );
}


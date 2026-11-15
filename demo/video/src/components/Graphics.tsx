import React from "react";
import { AbsoluteFill, OffthreadVideo, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { IMPACT, INNOVATION } from "../../vo/script";
const STANDS_OUT: Record<string, { title: string; points: string[] }> = {};
import type { Timed } from "../timeline";
import { T, glass } from "../theme";
import { Backdrop } from "./Frame";

const useIn = (delay = 0, damping = 18) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: f - delay, fps, config: { damping, mass: 0.7 } });
};
const Fade: React.FC<{ d?: number; y?: number; children: React.ReactNode; style?: React.CSSProperties }> = ({ d = 0, y = 24, children, style }) => {
  const s = useIn(d);
  return <div style={{ opacity: s, transform: `translateY(${(1 - s) * y}px)`, ...style }}>{children}</div>;
};

export const Logo: React.FC<{ size?: number }> = ({ size = 96 }) => (
  <div style={{ width: size, height: size, borderRadius: size * 0.26, background: T.grad, display: "grid", placeItems: "center",
    boxShadow: "0 20px 60px rgba(20,184,166,.35), inset 0 1px 0 rgba(255,255,255,.3)" }}>
    <div style={{ width: size * 0.42, height: size * 0.42, borderRadius: "50%", border: `${size * 0.07}px solid #fff`, boxShadow: `0 0 0 ${size * 0.07}px rgba(255,255,255,.25)` }} />
  </div>
);

// ---------------------------------------------------------------- cold open: R morphs into Python, certificate stamps
const R_CODE = ["dat <- read.csv(train_file, stringsAsFactors = FALSE)", "b <- make_bins(dat)", "w  <- log(((nb + 0.5) / B) / ((ng + 0.5) / G))", "fit <- glm(bad ~ ., data = X, family = binomial())"];
const PY_CODE = ["d = frame[frame[\".row\"].isin(train_rows)]", "b = make_bins(d)", "mp[lv] = np.log(((nb + 0.5) / B) / ((ng + 0.5) / G))", "res = sm.GLM(y, X, family=sm.families.Binomial()).fit(tol=1e-12)"];

export const Open: React.FC<{ shot: Timed }> = ({ shot }) => {
  const f = useCurrentFrame();
  const morph = interpolate(f, [24, 70], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const stamp = useIn(78, 12);
  const title = useIn(Math.max(100, shot.frames - 120));
  return (
    <AbsoluteFill>
      <Backdrop />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ ...glass, width: 1060, padding: "34px 40px", fontFamily: T.mono, fontSize: 25, lineHeight: 1.75, position: "relative",
          opacity: 1 - title, filter: `blur(${title * 8}px)`, transform: `scale(${1 - title * 0.08}) translateY(${-title * 60}px)` }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontFamily: T.font, fontSize: 18, color: T.muted, marginBottom: 14 }}>
            <span>{morph < 0.5 ? "cr001_pd_scorecard.R · legacy" : "model.py · certified translation"}</span>
            <span style={{ color: morph < 0.5 ? T.amber : T.tealSoft }}>{morph < 0.5 ? "R 4.4 · sandbox" : "Python"}</span>
          </div>
          {R_CODE.map((line, i) => {
            const k = Math.min(1, Math.max(0, morph * 1.6 - i * 0.18));
            const txt = k < 0.5 ? line : PY_CODE[i];
            return <div key={i} style={{ color: k < 0.5 ? "#fcd34d" : T.tealSoft, filter: `blur(${Math.sin(k * Math.PI) * 3}px)`, opacity: 1 - Math.sin(k * Math.PI) * 0.5, whiteSpace: "pre" }}>{txt}</div>;
          })}
          <div style={{ position: "absolute", right: -30, bottom: -46, transform: `rotate(-8deg) scale(${0.6 + stamp * 0.4})`, opacity: stamp,
            border: `4px solid ${T.green}`, color: T.green, borderRadius: 14, padding: "10px 22px", fontFamily: T.font, fontWeight: 900, fontSize: 34,
            letterSpacing: 2, background: "rgba(7,11,22,.85)" }}>PARITY · PASS<div style={{ fontSize: 15, letterSpacing: 1, fontWeight: 600 }}>every row within 1e-6</div></div>
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", opacity: title }}>
        <div style={{ display: "flex", alignItems: "center", gap: 34, transform: `translateY(${(1 - title) * 30}px)` }}>
          <Logo size={128} />
          <div>
            <div style={{ fontFamily: T.font, fontSize: 92, fontWeight: 800, color: T.ink, letterSpacing: -2, lineHeight: 1 }}>Model Risk Factory</div>
            <div style={{ fontFamily: T.font, fontSize: 30, fontWeight: 600, marginTop: 14, letterSpacing: 6, background: T.grad, WebkitBackgroundClip: "text", color: "transparent" }}>BY ZERO GRADIENT</div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- the problem
export const Problem: React.FC = () => {
  const cards = [
    { k: "Legacy R estates", v: "Scripts on shared drives. Owners gone. No documentation.", c: T.amber },
    { k: "Manual validation", v: "Weeks per model: re-run, re-derive, re-document.", c: T.red },
    { k: "SR 11-7 · SS1/23", v: "Supervisors expect inventory, lineage, validation and monitoring for every model.", c: T.violet },
  ];
  return (
    <AbsoluteFill>
      <Backdrop hue={200} />
      <AbsoluteFill style={{ padding: "150px 170px", gap: 50 }}>
        <Fade><div style={{ fontFamily: T.font, fontSize: 64, fontWeight: 800, color: T.ink, letterSpacing: -1.5 }}>The model risk bottleneck</div></Fade>
        <div style={{ display: "flex", gap: 34 }}>
          {cards.map((c, i) => (
            <Fade key={c.k} d={14 + i * 16} y={50} style={{ flex: 1 }}>
              <div style={{ ...glass, padding: "40px 36px", height: 330, borderTop: `4px solid ${c.c}` }}>
                <div style={{ fontFamily: T.font, fontSize: 38, fontWeight: 700, color: c.c }}>{c.k}</div>
                <div style={{ fontFamily: T.font, fontSize: 28, color: T.muted, marginTop: 22, lineHeight: 1.4 }}>{c.v}</div>
              </div>
            </Fade>
          ))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- lifecycle map: agents, gates, ledger
const STATIONS = [
  { k: "Discover", a: "Intake agent" }, { k: "Document", a: "Documentation agent" }, { k: "Redevelop", a: "Redevelopment agent" },
  { k: "Validate", a: "Validator · Report writer" }, { k: "Monitor", a: "Monitor agent" },
];
export const LifecycleMap: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill>
      <Backdrop hue={90} />
      <AbsoluteFill style={{ padding: "130px 120px" }}>
        <Fade><div style={{ fontFamily: T.font, fontSize: 58, fontWeight: 800, color: T.ink, letterSpacing: -1.2 }}>One governed lifecycle</div></Fade>
        <Fade d={6}><div style={{ fontFamily: T.font, fontSize: 28, color: T.muted, marginTop: 10 }}>Agents draft · deterministic tools compute · people decide</div></Fade>
        <div style={{ display: "flex", alignItems: "center", marginTop: 90 }}>
          {STATIONS.map((s, i) => (
            <React.Fragment key={s.k}>
              <Fade d={18 + i * 12} y={40}>
                <div style={{ ...glass, width: 250, padding: "28px 22px", textAlign: "center" }}>
                  <div style={{ width: 54, height: 54, margin: "0 auto", borderRadius: 16, background: T.grad, display: "grid", placeItems: "center", fontFamily: T.font, fontWeight: 800, fontSize: 24, color: "#fff" }}>{i + 1}</div>
                  <div style={{ fontFamily: T.font, fontSize: 32, fontWeight: 700, color: T.ink, marginTop: 16 }}>{s.k}</div>
                  <div style={{ fontFamily: T.font, fontSize: 19, color: T.violetSoft, marginTop: 8 }}>{s.a}</div>
                </div>
              </Fade>
              {i < STATIONS.length - 1 && (
                <Fade d={26 + i * 12} y={0} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center" }}>
                  <div style={{ width: "100%", height: 3, background: `linear-gradient(90deg, ${T.teal}, ${T.violet})`, opacity: 0.6 }} />
                  <div style={{ marginTop: -26, width: 48, height: 48, borderRadius: 24, background: T.bg1, border: `3px solid ${T.amber}`, display: "flex", alignItems: "center", justifyContent: "center", gap: 5 }}>
                    <span style={{ width: 5, height: 18, borderRadius: 2, background: T.amber }} /><span style={{ width: 5, height: 18, borderRadius: 2, background: T.amber }} /></div>
                  <div style={{ fontFamily: T.font, fontSize: 16, color: T.amber, marginTop: 8, fontWeight: 600 }}>human gate</div>
                </Fade>
              )}
            </React.Fragment>
          ))}
        </div>
        <Fade d={90} y={30}>
          <div style={{ ...glass, marginTop: 70, padding: "20px 30px", display: "flex", alignItems: "center", gap: 18, overflow: "hidden" }}>
            <span style={{ fontFamily: T.font, fontSize: 24, fontWeight: 700, color: T.tealSoft, whiteSpace: "nowrap", flexShrink: 0 }}>Hash-chained ledger</span>
            <div style={{ flex: 1, overflow: "hidden", maskImage: "linear-gradient(90deg, transparent, black 6%, black 94%, transparent)" }}>
            <div style={{ display: "flex", gap: 10, transform: `translateX(${-(f % 200)}px)` }}>
              {Array.from({ length: 18 }).map((_, i) => (
                <span key={i} style={{ fontFamily: T.mono, fontSize: 16, color: T.muted, border: `1px solid ${T.line}`, borderRadius: 8, padding: "6px 10px", whiteSpace: "nowrap" }}>
                  #{1200 + i} {["agent_step", "tool_call", "gate_decided", "finding", "parity_certificate_issued", "dependency_added"][i % 6]}
                </span>
              ))}
            </div>
            </div>
          </div>
        </Fade>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- "Why it stands out"
export const StandsOut: React.FC<{ id: string }> = ({ id }) => {
  const d = STANDS_OUT[id];
  const bar = useIn(0, 30);
  if (!d) return null;
  return (
    <AbsoluteFill>
      <Backdrop hue={id.length * 40} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ width: 1280 }}>
          <Fade><div style={{ fontFamily: T.font, fontSize: 24, fontWeight: 700, letterSpacing: 5, color: T.tealSoft }}>WHY IT STANDS OUT</div></Fade>
          <div style={{ height: 5, width: 160 * bar, background: T.grad, borderRadius: 3, margin: "18px 0 26px" }} />
          <Fade d={5}><div style={{ fontFamily: T.font, fontSize: 76, fontWeight: 800, color: T.ink, letterSpacing: -1.8, lineHeight: 1.05 }}>{d.title}</div></Fade>
          <div style={{ marginTop: 40, display: "flex", flexDirection: "column", gap: 18 }}>
            {d.points.map((p, i) => (
              <Fade key={p} d={14 + i * 9} y={18}>
                <div style={{ display: "flex", alignItems: "center", gap: 20, fontFamily: T.font, fontSize: 34, color: "#cbd5e1" }}>
                  <span style={{ width: 34, height: 34, borderRadius: 17, background: "rgba(20,184,166,.15)", border: `2px solid ${T.teal}`, display: "grid", placeItems: "center", color: T.tealSoft, fontSize: 20, fontWeight: 800 }}>✓</span>{p}
                </div>
              </Fade>
            ))}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- recap: two lanes over the final floor
export const Recap: React.FC<{ shot: Timed }> = ({ shot }) => {
  const lanes = [
    { id: "CR-001", kind: "Scorecard GLM", steps: ["Discover", "Document", "Translate → parity PASS", "Validate", "Deploy", "Monitor · re-validated"], c: T.teal },
    { id: "CR-002", kind: "Random forest", steps: ["Discover", "Document", "Rehost (validated in R)", "Validate", "Closed · not deployed"], c: T.violet },
  ];
  return (
    <AbsoluteFill>
      <Backdrop hue={10} />
      {shot.src && (
        <AbsoluteFill style={{ opacity: 0.16, filter: "blur(3px)" }}>
          <OffthreadVideo src={staticFile(shot.src.file)} startFrom={Math.round(shot.src.fromSec * 30)} muted style={{ width: 1920, height: 1080, objectFit: "cover" }} />
        </AbsoluteFill>
      )}
      <AbsoluteFill style={{ padding: "150px 150px", gap: 46 }}>
        <Fade><div style={{ fontFamily: T.font, fontSize: 58, fontWeight: 800, color: T.ink, letterSpacing: -1.2 }}>Two models. Two governed outcomes.</div></Fade>
        {lanes.map((l, li) => (
          <div key={l.id} style={{ display: "flex", alignItems: "center", gap: 18 }}>
            <Fade d={10 + li * 10} style={{ width: 230 }}>
              <div style={{ fontFamily: T.mono, fontSize: 36, fontWeight: 800, color: l.c }}>{l.id}</div>
              <div style={{ fontFamily: T.font, fontSize: 21, color: T.muted }}>{l.kind}</div>
            </Fade>
            {l.steps.map((s, i) => (
              <Fade key={s} d={18 + li * 10 + i * 8} y={20}>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <div style={{ ...glass, borderRadius: 12, padding: "16px 20px", fontFamily: T.font, fontSize: 21, color: T.ink, borderColor: i === l.steps.length - 1 ? l.c : undefined }}>{s}</div>
                  {i < l.steps.length - 1 && <span style={{ color: T.faint, fontSize: 24 }}>→</span>}
                </div>
              </Fade>
            ))}
          </div>
        ))}
        <Fade d={80}><div style={{ fontFamily: T.font, fontSize: 28, color: T.muted }}>5 human gates · every agent step and decision on the ledger</div></Fade>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

export const Outro: React.FC = () => {
  const s = useIn(0, 20);
  return (
    <AbsoluteFill>
      <Backdrop hue={300} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", gap: 30, opacity: s, transform: `scale(${0.94 + s * 0.06})` }}>
        <Logo size={140} />
        <div style={{ fontFamily: T.font, fontSize: 96, fontWeight: 800, color: T.ink, letterSpacing: -2 }}>Model Risk Factory</div>
        <div style={{ fontFamily: T.font, fontSize: 32, color: T.muted }}>Agents draft. Tools compute. People decide. Everything is evidence.</div>
        <div style={{ fontFamily: T.font, fontSize: 28, fontWeight: 700, letterSpacing: 7, background: T.grad, WebkitBackgroundClip: "text", color: "transparent", marginTop: 10 }}>BY ZERO GRADIENT</div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- v3 title card: logo + wordmark, quick and clean
export const Title: React.FC<{ shot: Timed }> = ({ shot }) => {
  const f = useCurrentFrame();
  const logo = useIn(2, 12);
  const word = useIn(10);
  const tag = useIn(22);
  const out = interpolate(f, [shot.frames - 14, shot.frames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const sweep = interpolate(f, [14, 60], [-30, 130], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill>
      <Backdrop hue={40} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", opacity: out, transform: `scale(${1 + (1 - out) * 0.04})` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 38 }}>
          <div style={{ transform: `scale(${0.5 + logo * 0.5}) rotate(${(1 - logo) * -40}deg)`, opacity: logo }}><Logo size={140} /></div>
          <div>
            <div style={{ position: "relative", fontFamily: T.font, fontSize: 104, fontWeight: 800, color: T.ink, letterSpacing: -2.5, lineHeight: 1,
              opacity: word, transform: `translateX(${(1 - word) * -40}px)`, overflow: "hidden" }}>
              Model Risk Factory
              <div style={{ position: "absolute", top: 0, bottom: 0, left: `${sweep}%`, width: "18%", background: "linear-gradient(90deg, transparent, rgba(255,255,255,.35), transparent)", transform: "skewX(-20deg)" }} />
            </div>
            <div style={{ fontFamily: T.font, fontSize: 32, fontWeight: 700, marginTop: 18, letterSpacing: 8 * tag, background: T.grad, WebkitBackgroundClip: "text", color: "transparent", opacity: tag }}>BY ZERO GRADIENT</div>
          </div>
        </div>
        <div style={{ fontFamily: T.font, fontSize: 28, color: T.muted, marginTop: 46, opacity: tag }}>Legacy models, rebuilt and governed by AI agents. People stay in control.</div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- what's new
export const Innovation: React.FC = () => (
  <AbsoluteFill>
    <Backdrop hue={160} />
    <AbsoluteFill style={{ padding: "120px 170px" }}>
      <Fade><div style={{ fontFamily: T.font, fontSize: 24, fontWeight: 700, letterSpacing: 5, color: T.tealSoft }}>OUR INNOVATION</div></Fade>
      <Fade d={4}><div style={{ fontFamily: T.font, fontSize: 64, fontWeight: 800, color: T.ink, letterSpacing: -1.5, marginTop: 10 }}>Agents that have to show their work</div></Fade>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 22, marginTop: 50 }}>
        {INNOVATION.map((x, i) => (
          <Fade key={x.k} d={14 + i * 9} y={30} style={i === INNOVATION.length - 1 ? { gridColumn: "1 / span 2" } : undefined}>
            <div style={{ ...glass, padding: "24px 30px", display: "flex", gap: 22, alignItems: "flex-start", borderLeft: `4px solid ${[T.teal, T.green, T.blue, T.violet, T.amber][i]}` }}>
              <div style={{ fontFamily: T.mono, fontSize: 26, fontWeight: 800, color: [T.tealSoft, T.green, T.blue, T.violetSoft, T.amber][i], width: 42 }}>0{i + 1}</div>
              <div>
                <div style={{ fontFamily: T.font, fontSize: 32, fontWeight: 700, color: T.ink }}>{x.k}</div>
                <div style={{ fontFamily: T.font, fontSize: 23, color: T.muted, marginTop: 6, lineHeight: 1.35 }}>{x.v}</div>
              </div>
            </div>
          </Fade>
        ))}
      </div>
    </AbsoluteFill>
  </AbsoluteFill>
);

// ---------------------------------------------------------------- business impact (measured numbers from this run)
const Count: React.FC<{ to: number; d: number; fmt: (n: number) => string }> = ({ to, d, fmt }) => {
  const f = useCurrentFrame();
  const k = interpolate(f, [d, d + 36], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: (t) => 1 - Math.pow(1 - t, 3) });
  return <>{fmt(to * k)}</>;
};
export const Impact: React.FC = () => {
  const stats: { v: number | null; fmt: (n: number) => string; k: string; c: string }[] = [
    { v: IMPACT.minutes, fmt: (n) => `${Math.round(n)} min`, k: "legacy R → certified Python (CR-001)", c: T.tealSoft },
    { v: IMPACT.models, fmt: (n) => `${Math.round(n)}`, k: "models worked in parallel", c: T.violetSoft },
    { v: IMPACT.cost, fmt: (n) => `$${n.toFixed(2)}`, k: "LLM cost for the whole run", c: T.green },
    { v: IMPACT.steps, fmt: (n) => `${Math.round(n).toLocaleString("en-US")}`, k: "agent steps, every one on the ledger", c: T.blue },
  ];
  const rows = [
    ["Validation capacity", "weeks of manual re-work per model → hours of agent work, reviewed by people"],
    ["Regulatory readiness", "SR 11-7 · SS1/23 evidence, lineage and monitoring for every model, by default"],
    ["Lower model risk", "proven translations, live drift alerts, automatic re-validation"],
  ];
  return (
    <AbsoluteFill>
      <Backdrop hue={260} />
      <AbsoluteFill style={{ padding: "110px 160px" }}>
        <Fade><div style={{ fontFamily: T.font, fontSize: 24, fontWeight: 700, letterSpacing: 5, color: T.amber }}>BUSINESS IMPACT</div></Fade>
        <Fade d={4}><div style={{ fontFamily: T.font, fontSize: 60, fontWeight: 800, color: T.ink, letterSpacing: -1.4, marginTop: 10 }}>Measured in this run</div></Fade>
        <div style={{ display: "flex", gap: 22, marginTop: 44 }}>
          {stats.filter((s) => s.v != null).map((s, i) => (
            <Fade key={s.k} d={12 + i * 8} y={30} style={{ flex: 1 }}>
              <div style={{ ...glass, padding: "28px 26px", height: 190 }}>
                <div style={{ fontFamily: T.font, fontSize: 64, fontWeight: 800, color: s.c, letterSpacing: -1 }}><Count to={s.v as number} d={16 + i * 8} fmt={s.fmt} /></div>
                <div style={{ fontFamily: T.font, fontSize: 22, color: T.muted, marginTop: 10, lineHeight: 1.3 }}>{s.k}</div>
              </div>
            </Fade>
          ))}
        </div>
        <div style={{ marginTop: 40, display: "flex", flexDirection: "column", gap: 16 }}>
          {rows.map(([k, v], i) => (
            <Fade key={k} d={50 + i * 10} y={16}>
              <div style={{ display: "flex", gap: 22, alignItems: "baseline", fontFamily: T.font }}>
                <span style={{ fontSize: 28, fontWeight: 700, color: T.ink, width: 330, flexShrink: 0 }}>{k}</span>
                <span style={{ fontSize: 26, color: "#cbd5e1" }}>{v}</span>
              </div>
            </Fade>
          ))}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

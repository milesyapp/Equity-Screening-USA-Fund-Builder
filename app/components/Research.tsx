"use client";

// app/components/Research.tsx
// The construction experiment: classical vs quantum portfolio selection.
// Renders whatever arms exist — 2 today (greedy + QUBO/classical), 3 once the
// D-Wave hardware arm activates. The forward NAV chart uses REALIZED forward
// returns only (research_log), never in-sample reconstruction.

import React from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { Atom, Cpu, GitCompareArrows } from "lucide-react";
import type { ResearchBlock, FundArm, ForwardArmStat } from "../../lib/types";

/* ── formatting ─────────────────────────────────────────────────────────── */
const pct = (x: number | null | undefined, d = 1) =>
  x == null || Number.isNaN(x) ? "—" : `${(x * 100).toFixed(d)}%`;
const signedPct = (x: number | null | undefined, d = 1) =>
  x == null || Number.isNaN(x) ? "—" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(d)}%`;
const num = (x: number | null | undefined, d = 2) =>
  x == null || Number.isNaN(x) ? "—" : x.toFixed(d);
const fmtDate = (s?: string) => {
  if (!s) return "—";
  try {
    return new Date(s + "T00:00:00").toLocaleDateString("en-US", {
      year: "numeric", month: "short", day: "numeric",
    });
  } catch { return s; }
};

const ARM_COLORS: Record<string, string> = {
  greedy: "#e8b34e",          // gold — the house classical fund
  qubo_classical: "#6f8f7a",  // sage — same objective, classical solver
  qubo_quantum: "#8f7fd4",    // violet — real hardware
};
const ARM_SHORT: Record<string, string> = {
  greedy: "Greedy",
  qubo_classical: "QUBO · classical",
  qubo_quantum: "QUBO · quantum",
};

export default function Research({ research }: { research: ResearchBlock }) {
  const arms = research.arms ?? [];
  if (arms.length < 2) return null; // nothing to compare yet

  const nav = research.forwardNav ?? [];
  const fs = research.forwardStats;
  const quantumLive = arms.some((a) => a.key === "qubo_quantum");

  return (
    <section style={{ ...R.wrap, marginTop: 30 }} className="rise d5">
      {/* head — mirrors PanelHead */}
      <div style={R.panelHead}>
        <span style={R.panelNum}>02</span>
        <div>
          <h2 style={R.panelTitle}>Construction experiment</h2>
          <div style={R.panelSub}>
            classical vs quantum-annealed selection · same scored universe ·
            forward record since {fmtDate(research.inceptionDate)}
          </div>
        </div>
        {!quantumLive && (
          <span style={R.pendingChip}>
            <Atom size={11} style={{ marginRight: 5, verticalAlign: -1.5 }} />
            hardware arm pending D-Wave access
          </span>
        )}
      </div>

      {/* arm cards */}
      <div style={R.armRow}>
        {arms.map((a) => (
          <ArmCard key={a.key} arm={a} baseline={research.baselineArm} />
        ))}
        {!quantumLive && <GhostQuantumCard />}
      </div>

      {/* forward NAV + forward stats */}
      <div style={R.grid2}>
        <div style={R.panel}>
          <div style={R.chartHead}>
            <span style={R.chartTitle}>Growth of $1 — realized forward returns</span>
            <span style={R.chartTag}>live record, not reconstruction</span>
          </div>
          {nav.length >= 2 ? (
            <>
              <div style={{ width: "100%", height: 230 }}>
                <ResponsiveContainer>
                  <LineChart data={nav} margin={{ top: 8, right: 10, bottom: 4, left: -8 }}>
                    <CartesianGrid stroke="#23272d" strokeDasharray="2 4" />
                    <XAxis dataKey="date" tick={{ fill: "#8b867a", fontSize: 10, fontFamily: "IBM Plex Mono" }}
                      tickLine={false} axisLine={{ stroke: "#2a2f36" }} minTickGap={60}
                      tickFormatter={(d) => String(d).slice(5)} />
                    <YAxis tick={{ fill: "#8b867a", fontSize: 10, fontFamily: "IBM Plex Mono" }}
                      tickLine={false} axisLine={{ stroke: "#2a2f36" }} width={46}
                      tickFormatter={(v) => `$${Number(v).toFixed(2)}`} domain={["auto", "auto"]} />
                    <Tooltip content={<NavTip />} />
                    {arms.map((a) => (
                      <Line key={a.key} type="monotone" dataKey={a.key} connectNulls
                        stroke={ARM_COLORS[a.key] ?? "#cfc8b8"}
                        strokeWidth={a.key === "qubo_quantum" ? 2 : 1.6} dot={false} />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div style={R.chartKey}>
                {arms.map((a) => (
                  <span key={a.key}>
                    <i style={{ ...R.keyDot, background: ARM_COLORS[a.key] ?? "#cfc8b8" }} />
                    {ARM_SHORT[a.key] ?? a.key}
                  </span>
                ))}
              </div>
            </>
          ) : (
            <div style={R.navEmpty}>
              The forward record began {fmtDate(research.inceptionDate)}. The comparison
              chart appears once a few trading days have accrued — this panel shows only
              realized returns of the live baskets, never an in-sample backcast.
            </div>
          )}
        </div>

        <div style={R.panel}>
          <div style={R.chartHead}>
            <span style={R.chartTitle}>Forward comparison vs {ARM_SHORT[research.baselineArm] ?? research.baselineArm}</span>
            <span style={R.chartTag}>{fs?.nDays ?? 0} trading days</span>
          </div>
          {fs?.available && fs.perArm && fs.perArm.length > 0 ? (
            <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
              {fs.perArm.map((p) => <StatRow key={p.arm} p={p} />)}
            </div>
          ) : (
            <div style={R.navEmpty}>
              Statistics activate as the forward record accumulates. With two highly
              correlated long-equity baskets, differences take a long time to separate
              from noise — wide intervals early on are the honest answer.
            </div>
          )}
          {fs?.caveat && <div style={R.caveat}>{fs.caveat}</div>}
        </div>
      </div>

      {/* selection overlap */}
      {research.selectionComparison?.length > 0 && (
        <div style={{ ...R.panel, marginTop: 16 }}>
          <span style={R.chartTitle}>
            <GitCompareArrows size={13} style={{ marginRight: 6, verticalAlign: -2 }} />
            Do the methods even pick different stocks?
          </span>
          <div style={R.cmpRow}>
            {research.selectionComparison.map((c) => (
              <div key={c.pair} style={R.cmpCard}>
                <div style={R.cmpPair}>
                  {c.pair.split("_vs_").map((k) => ARM_SHORT[k] ?? k).join("  vs  ")}
                </div>
                <div style={R.cmpBig}>{c.overlapCount}<span style={R.cmpBigSub}> shared</span></div>
                <div style={R.cmpSub}>
                  Jaccard {num(c.jaccard, 2)} · {c.onlyA.length} only in first · {c.onlyB.length} only in second
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* methodology */}
      <div style={{ ...R.panel, marginTop: 16 }}>
        <span style={R.chartTitle}>Method, in one paragraph</span>
        <p style={R.method}>
          Selection is posed as a QUBO over the top-150 candidates: a quality term rewards
          high composite scores, a quadratic term built from the return covariance matrix
          penalises holding correlated pairs, and penalty terms hold portfolio size and
          sector concentration. The identical problem is solved twice — once with classical
          simulated annealing, once on D-Wave hardware — so the gap between those two arms
          isolates the <em>solver</em>, while their gap to the greedy fund isolates the{" "}
          <em>objective</em>. Selected names are then score-weighted exactly like the
          classical fund. Selections freeze for the week; both are re-priced daily.
        </p>
        <p style={R.disclaimer}>{research.disclaimer}</p>
      </div>
    </section>
  );
}

/* ── sub-components ─────────────────────────────────────────────────────── */
function ArmCard({ arm, baseline }: { arm: FundArm; baseline: string }) {
  const c = ARM_COLORS[arm.key] ?? "#cfc8b8";
  const m = arm.fund?.metrics3Y;
  const d = arm.diagnostics;
  return (
    <div style={{ ...R.armCard, borderTop: `2px solid ${c}` }}>
      <div style={R.armHead}>
        <span style={{ ...R.armName, color: c }}>
          {arm.isQuantum
            ? <Atom size={13} style={{ marginRight: 6, verticalAlign: -2 }} />
            : <Cpu size={13} style={{ marginRight: 6, verticalAlign: -2 }} />}
          {ARM_SHORT[arm.key] ?? arm.label}
        </span>
        {arm.key === baseline && <span style={R.baseTag}>BASELINE</span>}
      </div>
      <div style={R.armLabel}>{arm.label}</div>
      <div style={R.armMetrics}>
        <Mini label="Holdings" v={String(arm.selection.length)} />
        <Mini label="3Y return" v={signedPct(m?.annualReturn)} />
        <Mini label="3Y Sharpe" v={num(m?.sharpeRatio)} />
        <Mini label="Max wt" v={pct(maxWeight(arm.weights), 1)} />
      </div>
      {d && (
        <div style={R.diagRow}>
          {d.solver} · E {num(d.bestEnergy, 0)} · {num(d.wallSeconds, 1)}s
          {d.chainBreakFraction != null && ` · chains ${pct(d.chainBreakFraction, 1)}`}
        </div>
      )}
      <div style={R.armNote}>3Y figures are in-sample for the current basket.</div>
    </div>
  );
}

function GhostQuantumCard() {
  return (
    <div style={{ ...R.armCard, borderTop: "2px dashed #3a3f49", opacity: 0.65 }}>
      <div style={R.armHead}>
        <span style={{ ...R.armName, color: "#8f7fd4" }}>
          <Atom size={13} style={{ marginRight: 6, verticalAlign: -2 }} />
          QUBO · quantum
        </span>
      </div>
      <div style={R.armLabel}>Same QUBO, solved on a D-Wave annealer</div>
      <div style={{ ...R.armNote, marginTop: 14 }}>
        Activates on the first weekly run after hardware access is granted. The
        identical problem will be submitted to both solvers from that day forward.
      </div>
    </div>
  );
}

function StatRow({ p }: { p: ForwardArmStat }) {
  const sd = p.sharpeDifference;
  return (
    <div style={R.statRow}>
      <div style={{ ...R.statArm, color: ARM_COLORS[p.arm] ?? "#cfc8b8" }}>
        {ARM_SHORT[p.arm] ?? p.arm}
      </div>
      <div style={R.statGrid}>
        <Mini label="Active (cumul.)" v={signedPct(p.activeReturnCumulative)} />
        <Mini label="Active (ann.)" v={signedPct(p.activeReturnAnnualised)} />
        <Mini label="Tracking err" v={pct(p.trackingError)} />
        <Mini label="Info ratio" v={num(p.informationRatio)} />
        <Mini label="Max DD (fwd)" v={pct(p.maxDrawdown?.arm)} />
        <Mini label="Sortino" v={num(p.sortino?.arm)} />
        <Mini label="Calmar" v={num(p.calmar?.arm)} />
        <Mini label="PSR > 0" v={num(p.probSharpePositive?.arm)} />
        <Mini label="Sharpe Δ" v={sd?.difference == null ? "—" : `${sd.difference >= 0 ? "+" : ""}${num(sd.difference)}`} />
        <Mini label="95% CI" v={sd?.ci95 ? `[${num(sd.ci95[0], 2)}, ${num(sd.ci95[1], 2)}]` : "—"} />
        <Mini label="p-value" v={num(sd?.pValue, 2)} />
      </div>
    </div>
  );
}

function Mini({ label, v }: { label: string; v: string }) {
  return (
    <div>
      <div style={R.miniLabel}>{label}</div>
      <div style={R.miniVal}>{v}</div>
    </div>
  );
}

function NavTip({ active, payload, label }: {
  active?: boolean;
  payload?: Array<{ dataKey: string; value: number; stroke: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div style={R.tip}>
      <div style={R.tipDate}>{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} style={{ color: p.stroke, fontFamily: "IBM Plex Mono", fontSize: 11.5 }}>
          {(ARM_SHORT[p.dataKey] ?? p.dataKey)}: ${Number(p.value).toFixed(4)}
        </div>
      ))}
    </div>
  );
}

function maxWeight(w: Record<string, number>): number | null {
  const vals = Object.values(w ?? {});
  return vals.length ? Math.max(...vals) : null;
}

/* ── styles (mirrors Screener's S) ──────────────────────────────────────── */
const R: Record<string, React.CSSProperties> = {
  wrap: { maxWidth: 1320, margin: "0 auto", padding: "0 28px" },
  panelHead: { display: "flex", alignItems: "baseline", gap: 18, marginBottom: 18, flexWrap: "wrap" },
  panelNum: { fontFamily: "IBM Plex Mono", fontSize: 12, color: "#7a7566", letterSpacing: 2 },
  panelTitle: { fontFamily: "'Fraunces', serif", fontWeight: 500, fontSize: 28, margin: 0, color: "#f4efe3", letterSpacing: -0.3 },
  panelSub: { fontSize: 12, color: "#8a8576", fontFamily: "IBM Plex Mono", marginTop: 4 },
  pendingChip: { marginLeft: "auto", fontSize: 11, color: "#a99fce", border: "1px solid #2e2a40", background: "rgba(143,127,212,.06)", borderRadius: 20, padding: "5px 12px", fontFamily: "IBM Plex Mono" },

  armRow: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 14 },
  armCard: { background: "#0e1113", border: "1px solid #1d2127", borderRadius: 6, padding: "16px 18px" },
  armHead: { display: "flex", alignItems: "center", justifyContent: "space-between" },
  armName: { fontFamily: "IBM Plex Mono", fontSize: 13.5, fontWeight: 600, letterSpacing: 0.4 },
  baseTag: { fontSize: 9.5, color: "#8a8576", border: "1px solid #2a2f36", borderRadius: 3, padding: "2px 6px", fontFamily: "IBM Plex Mono", letterSpacing: 1 },
  armLabel: { fontFamily: "'Fraunces', serif", fontSize: 13.5, color: "#bdb5a1", marginTop: 6 },
  armMetrics: { display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginTop: 14 },
  diagRow: { marginTop: 12, fontSize: 10.5, color: "#7a7566", fontFamily: "IBM Plex Mono", borderTop: "1px solid #1a1e23", paddingTop: 9 },
  armNote: { marginTop: 8, fontSize: 10.5, color: "#6f6a5f", lineHeight: 1.6, fontFamily: "IBM Plex Sans" },

  grid2: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(380px, 1fr))", gap: 16, marginTop: 16 },
  panel: { background: "#0e1113", border: "1px solid #1d2127", borderRadius: 6, padding: "16px 18px" },
  chartHead: { display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12, flexWrap: "wrap" },
  chartTitle: { fontFamily: "'Fraunces', serif", fontSize: 15.5, color: "#e6dfce" },
  chartTag: { fontSize: 10.5, color: "#7a7566", fontFamily: "IBM Plex Mono" },
  chartKey: { display: "flex", gap: 18, marginTop: 8, fontSize: 11, color: "#a39a82", fontFamily: "IBM Plex Mono", flexWrap: "wrap" },
  keyDot: { display: "inline-block", width: 8, height: 8, borderRadius: 2, marginRight: 6, verticalAlign: -0.5 },
  navEmpty: { marginTop: 14, fontSize: 12.5, color: "#8a8576", lineHeight: 1.8, fontFamily: "IBM Plex Sans" },

  statRow: { borderTop: "1px solid #1a1e23", paddingTop: 10 },
  statArm: { fontFamily: "IBM Plex Mono", fontSize: 12.5, fontWeight: 600, marginBottom: 8 },
  statGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(86px, 1fr))", gap: 8 },
  caveat: { marginTop: 14, fontSize: 10.5, color: "#6f6a5f", lineHeight: 1.7, fontFamily: "IBM Plex Sans", borderTop: "1px solid #1a1e23", paddingTop: 10 },

  cmpRow: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 12, marginTop: 12 },
  cmpCard: { border: "1px solid #1a1e23", borderRadius: 5, padding: "12px 14px", background: "#0c0f11" },
  cmpPair: { fontSize: 11, color: "#a39a82", fontFamily: "IBM Plex Mono" },
  cmpBig: { fontFamily: "IBM Plex Mono", fontSize: 26, color: "#f0ead8", marginTop: 6, fontWeight: 500, letterSpacing: -0.5 },
  cmpBigSub: { fontSize: 12, color: "#8a8576", fontWeight: 400 },
  cmpSub: { fontSize: 10.5, color: "#7a7566", fontFamily: "IBM Plex Mono", marginTop: 4 },

  method: { fontSize: 12.5, color: "#a8a08c", lineHeight: 1.85, marginTop: 10, fontFamily: "IBM Plex Sans", maxWidth: 920 },
  disclaimer: { fontSize: 10.5, color: "#6f6a5f", lineHeight: 1.7, marginTop: 10, fontFamily: "IBM Plex Sans", maxWidth: 920 },

  miniLabel: { fontSize: 9.5, color: "#7a7566", letterSpacing: 0.8, textTransform: "uppercase", fontFamily: "IBM Plex Mono" },
  miniVal: { fontFamily: "IBM Plex Mono", fontSize: 13.5, color: "#e6dfce", marginTop: 3 },

  tip: { background: "#13161a", border: "1px solid #262b33", borderRadius: 5, padding: "8px 11px" },
  tipDate: { fontSize: 10.5, color: "#8a8576", fontFamily: "IBM Plex Mono", marginBottom: 4 },
};

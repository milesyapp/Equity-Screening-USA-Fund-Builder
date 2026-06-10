"use client";

// app/components/Landing.tsx
// The new front page: a research-publication view over the classical-vs-quantum
// construction experiment. Reads the full screen from /api/portfolio (the
// existing route) and renders fund cards, a comparison table, the forward
// experiment stats, and the selection-overlap section.

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  LineChart, Line, ResponsiveContainer,
} from "recharts";
import { ArrowRight, FlaskConical } from "lucide-react";
import type {
  Screen, FundArm, FundWindow, SelectionComparison,
} from "../../lib/types";

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
// Calmar is a standard ratio (annual return / |max drawdown|); the data
// contract carries no Sortino field, so that cell renders "—".
const calmar = (m: FundWindow | null) =>
  m && m.maximumDrawdown ? m.annualReturn / Math.abs(m.maximumDrawdown) : null;

/* ── palette (per design system) ────────────────────────────────────────── */
const ARM_COLORS: Record<string, string> = {
  greedy: "#e8b34e",
  qubo_classical: "#6f8f7a",
  qubo_quantum: "#8f7fd4",
};
const ARM_TITLE: Record<string, string> = {
  greedy: "Greedy",
  qubo_classical: "QUBO Classical",
  qubo_quantum: "QUBO Quantum",
};
const ARM_ORDER = ["greedy", "qubo_classical", "qubo_quantum"] as const;
const GREEN = "#5a9e6f";
const RED = "#c46a5a";
const retColor = (x: number | null | undefined) =>
  x == null ? "#7a7566" : x >= 0 ? GREEN : RED;

/* ── forward-NAV sparkline series for one arm ───────────────────────────── */
function armForwardSeries(
  forwardNav: Array<{ date: string } & Record<string, number | string>> | undefined,
  armKey: string
): { i: number; v: number }[] {
  if (!forwardNav) return [];
  const out: { i: number; v: number }[] = [];
  forwardNav.forEach((row, i) => {
    const raw = row[armKey];
    if (typeof raw === "number" && !Number.isNaN(raw)) out.push({ i, v: raw });
  });
  return out;
}

/* ── component ──────────────────────────────────────────────────────────── */
export default function Landing() {
  const [data, setData] = useState<Screen | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/portfolio")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((j: Screen) => { if (alive) setData(j); })
      .catch((e) => { if (alive) setError(String(e.message || e)); });
    return () => { alive = false; };
  }, []);

  const research = data?.research ?? null;
  const arms = research?.arms ?? [];
  const armByKey = useMemo(() => {
    const m: Record<string, FundArm> = {};
    arms.forEach((a) => { m[a.key] = a; });
    return m;
  }, [arms]);

  if (error) {
    return (
      <div style={S.root}>
        <style>{CSS}</style>
        <div style={S.centered}>
          <p style={{ fontSize: 16, marginBottom: 8 }}>Couldn&apos;t load the screen.</p>
          <p style={{ fontSize: 13, color: "#7a7566", fontFamily: "IBM Plex Mono" }}>
            /api/portfolio returned: {error}. Run the weekly screen and copy its output to
            data/latest.json, then refresh.
          </p>
        </div>
      </div>
    );
  }

  if (!data || !research) {
    return (
      <div style={S.root}>
        <style>{CSS}</style>
        <div style={S.centered}>
          <p style={{ fontSize: 14, color: "#7a7566", fontFamily: "IBM Plex Mono" }}>
            Loading research…
          </p>
        </div>
      </div>
    );
  }

  const fs = research.forwardStats;

  return (
    <div style={S.root}>
      <style>{CSS}</style>

      {/* ── masthead ──────────────────────────────────────────────────── */}
      <header style={S.wrap}>
        <div style={S.topbar} className="rise">
          <span style={S.kicker}>EQUITYLENS · RESEARCH</span>
          <Link href="/screener" style={S.navLink}>The 100-stock screener →</Link>
        </div>
        <div style={S.rule} />
        <div style={S.mastRow} className="rise d1">
          <div>
            <h1 style={S.h1}>EquityLens</h1>
            <p style={S.tagline}>
              Quantitative equity research · classical vs quantum construction experiment
            </p>
          </div>
          <div style={S.statusBar}>
            <span style={S.statusItem}>
              <span style={S.statusLabel}>LAST RUN</span>
              <span style={S.statusVal}>{fmtDate(data.asOf)}</span>
            </span>
            <span style={S.statusDivider} />
            <span style={S.statusItem}>
              <span style={S.statusLabel}>UNIVERSE</span>
              <span style={S.statusVal}>{data.universeSize.toLocaleString()} names</span>
            </span>
          </div>
        </div>
      </header>

      {/* ── 01 · fund comparison strip ────────────────────────────────── */}
      <section style={{ ...S.wrap, marginTop: 34 }} className="rise d2">
        <PanelHead n="01" title="The three arms" sub="IDENTICAL UNIVERSE · DIFFERENT CONSTRUCTION" />
        <div style={S.cardStrip}>
          {ARM_ORDER.map((key) => {
            const arm = armByKey[key];
            const color = ARM_COLORS[key];
            if (!arm) {
              return (
                <div key={key} style={{ ...S.fundCard, ...S.ghostCard, borderColor: color }}>
                  <div style={{ ...S.cardArm, color }}>{ARM_TITLE[key]}</div>
                  <div style={S.ghostBody}>
                    <FlaskConical size={20} color={color} style={{ opacity: 0.7 }} />
                    <p style={S.ghostText}>
                      Hardware arm activates on next weekly run after D-Wave access is granted
                    </p>
                  </div>
                </div>
              );
            }
            const m = arm.fund.metrics3Y;
            const top3 = arm.fund.sectorBreakdown.slice(0, 3);
            const series = armForwardSeries(research.forwardNav, key);
            return (
              <div key={key} style={{ ...S.fundCard, borderTop: `2px solid ${color}` }}>
                <div style={{ ...S.cardArm, color }}>{ARM_TITLE[key]}</div>
                <div style={S.cardHoldings}>{arm.fund.constituents} holdings</div>

                <div style={S.cardMetricGrid}>
                  <CardMetric label="3Y RETURN" value={pct(m?.annualReturn)} color={GREEN} />
                  <CardMetric label="3Y SHARPE" value={num(m?.sharpeRatio)} />
                  <CardMetric label="3Y MAX DD" value={pct(m?.maximumDrawdown)} color={RED} />
                </div>

                <div style={S.sparkWrap}>
                  {series.length >= 2 ? (
                    <ResponsiveContainer width="100%" height={42}>
                      <LineChart data={series} margin={{ top: 4, bottom: 4, left: 0, right: 0 }}>
                        <Line type="monotone" dataKey="v" stroke={color} strokeWidth={1.5}
                          dot={false} isAnimationActive={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  ) : (
                    <span style={S.sparkEmpty}>
                      forward record begins {fmtDate(research.inceptionDate)}
                    </span>
                  )}
                  <span style={S.sparkTag}>forward NAV · realized only</span>
                </div>

                <div style={S.cardSectors}>
                  <span style={S.cardSectorsLabel}>TOP SECTORS</span>
                  {top3.map((s) => (
                    <span key={s.sector} style={S.sectorChip}>
                      {s.sector} <b style={{ color: "#cfc8b8" }}>{pct(s.weight, 0)}</b>
                    </span>
                  ))}
                </div>

                <Link href={`/fund/${key}`} style={{ ...S.viewBtn, color, borderColor: color }}>
                  View fund <ArrowRight size={13} />
                </Link>
              </div>
            );
          })}
        </div>
      </section>

      {/* ── 02 · comparison table ─────────────────────────────────────── */}
      <section style={{ ...S.wrap, marginTop: 38 }} className="rise d3">
        <PanelHead n="02" title="Side by side" sub="3-YEAR IN-SAMPLE CHARACTERISATION OF CURRENT BASKETS" />
        <div style={S.tableScroll}>
          <table style={S.cmpTable}>
            <thead>
              <tr>
                <th style={{ ...S.cmpTh, textAlign: "left" }}>METRIC (3Y)</th>
                {ARM_ORDER.map((k) => (
                  <th key={k} style={{ ...S.cmpTh, color: ARM_COLORS[k] }}>{ARM_TITLE[k]}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {([
                ["Annualised return", (m: FundWindow | null) => pct(m?.annualReturn)],
                ["Volatility", (m: FundWindow | null) => pct(m?.annualVolatility)],
                ["Sharpe", (m: FundWindow | null) => num(m?.sharpeRatio)],
                ["Sortino", () => "—"],
                ["Max drawdown", (m: FundWindow | null) => pct(m?.maximumDrawdown)],
                ["Calmar", (m: FundWindow | null) => num(calmar(m))],
                ["Alpha", (m: FundWindow | null) => pct(m?.alpha)],
                ["Beta", (m: FundWindow | null) => num(m?.beta)],
              ] as [string, (m: FundWindow | null) => string][]).map(([label, fn]) => (
                <tr key={label} style={S.cmpTr}>
                  <td style={{ ...S.cmpTd, ...S.cmpRowLabel }}>{label}</td>
                  {ARM_ORDER.map((k) => {
                    const arm = armByKey[k];
                    return (
                      <td key={k} style={{ ...S.cmpTd, ...S.cmpNum }}>
                        {arm ? fn(arm.fund.metrics3Y) : "—"}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── 03 · forward experiment stats ─────────────────────────────── */}
      <section style={{ ...S.wrap, marginTop: 38 }} className="rise d4">
        <PanelHead n="03" title="Forward experiment" sub="REALIZED OUT-OF-SAMPLE RECORD" />
        {!fs.available ? (
          <div style={S.holding}>
            The forward record began {fmtDate(research.inceptionDate)}. Comparison statistics
            activate as the record accumulates — currently {fs.nDays} trading{" "}
            {fs.nDays === 1 ? "day" : "days"}.
          </div>
        ) : (
          <>
            <div style={S.fwdMeta}>
              {fs.nDays} trading days on record · baseline {ARM_TITLE[fs.baseline ?? "greedy"]}
            </div>
            <div style={S.fwdGrid}>
              {(fs.perArm ?? []).map((p) => {
                const color = ARM_COLORS[p.arm] ?? "#e8b34e";
                const sd = p.sharpeDifference;
                return (
                  <div key={p.arm} style={{ ...S.fwdCard, borderLeft: `2px solid ${color}` }}>
                    <div style={{ ...S.fwdArm, color }}>
                      {ARM_TITLE[p.arm] ?? p.arm} <span style={S.fwdVs}>vs {ARM_TITLE[p.vsBaseline] ?? p.vsBaseline}</span>
                    </div>
                    <div style={S.fwdStatRow}>
                      <FwdStat label="ACTIVE RETURN" value={signedPct(p.activeReturnAnnualised)} />
                      <FwdStat label="TRACKING ERR" value={pct(p.trackingError)} />
                      <FwdStat label="INFO RATIO" value={num(p.informationRatio)} />
                    </div>
                    <div style={S.fwdSharpe}>
                      <span style={S.fwdSharpeLabel}>SHARPE Δ</span>
                      <span style={S.fwdSharpeVal}>{num(sd.difference)}</span>
                      <span style={S.fwdSharpeCi}>
                        {sd.ci95 ? `95% CI [${num(sd.ci95[0])}, ${num(sd.ci95[1])}]` : "CI —"}
                        {" · "}p {sd.pValue == null ? "—" : sd.pValue.toFixed(3)}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
        {fs.caveat && <p style={S.caveat}>{fs.caveat}</p>}
      </section>

      {/* ── 04 · selection overlap ────────────────────────────────────── */}
      <section style={{ ...S.wrap, marginTop: 38 }} className="rise d4">
        <PanelHead n="04" title="Selection overlap" sub="WHERE THE ARMS AGREE — AND WHERE THEY DON'T" />
        {research.selectionComparison.length === 0 ? (
          <div style={S.holding}>No pairwise comparison yet — a second arm is required.</div>
        ) : (
          <div style={S.overlapStack}>
            {research.selectionComparison.map((sc) => (
              <OverlapRow key={sc.pair} sc={sc} />
            ))}
          </div>
        )}
      </section>

      {/* ── footer nav ────────────────────────────────────────────────── */}
      <footer style={{ ...S.wrap, ...S.footer }}>
        <p style={S.disclaimer}>{research.disclaimer}</p>
        <Link href="/screener" style={S.footerLink}>
          Open the full 100-stock screener <ArrowRight size={13} />
        </Link>
      </footer>
    </div>
  );
}

/* ── small presentational helpers ───────────────────────────────────────── */
function PanelHead({ n, title, sub }: { n: string; title: string; sub: string }) {
  return (
    <div style={S.panelHead}>
      <span style={S.panelNo}>{n}</span>
      <div>
        <div style={S.panelTitle}>{title}</div>
        <div style={S.panelSub}>{sub}</div>
      </div>
    </div>
  );
}

function CardMetric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={S.cardMetric}>
      <div style={{ ...S.cardMetricVal, color: color ?? "#f4efe3" }}>{value}</div>
      <div style={S.cardMetricLabel}>{label}</div>
    </div>
  );
}

function FwdStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={S.fwdStatVal}>{value}</div>
      <div style={S.fwdStatLabel}>{label}</div>
    </div>
  );
}

function OverlapRow({ sc }: { sc: SelectionComparison }) {
  const [a, b] = sc.pair.split("_vs_");
  return (
    <div style={S.overlapCard}>
      <div style={S.overlapHead}>
        <span style={{ color: ARM_COLORS[a] ?? "#e8b34e" }}>{ARM_TITLE[a] ?? a}</span>
        <span style={S.overlapVs}>vs</span>
        <span style={{ color: ARM_COLORS[b] ?? "#6f8f7a" }}>{ARM_TITLE[b] ?? b}</span>
        <span style={S.overlapStats}>
          Jaccard {sc.jaccard == null ? "—" : sc.jaccard.toFixed(2)} · {sc.overlapCount} shared
        </span>
      </div>
      <div style={S.overlapCols}>
        <div style={S.overlapCol}>
          <div style={{ ...S.overlapColLabel, color: ARM_COLORS[a] ?? "#e8b34e" }}>
            ONLY IN {(ARM_TITLE[a] ?? a).toUpperCase()} ({sc.onlyA.length})
          </div>
          <div style={S.chipWrap}>
            {sc.onlyA.map((t) => <span key={t} style={S.tickerChip}>{t}</span>)}
          </div>
        </div>
        <div style={S.overlapCol}>
          <div style={{ ...S.overlapColLabel, color: ARM_COLORS[b] ?? "#6f8f7a" }}>
            ONLY IN {(ARM_TITLE[b] ?? b).toUpperCase()} ({sc.onlyB.length})
          </div>
          <div style={S.chipWrap}>
            {sc.onlyB.map((t) => <span key={t} style={S.tickerChip}>{t}</span>)}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── styles ─────────────────────────────────────────────────────────────── */
const S: Record<string, React.CSSProperties> = {
  root: {
    background: "#0b0d0f", minHeight: "100vh", paddingBottom: 64,
    fontFamily: "'IBM Plex Sans', sans-serif", color: "#f4efe3",
    backgroundImage:
      "radial-gradient(1200px 600px at 80% -10%,rgba(232,179,78,.07),transparent 60%)," +
      "radial-gradient(900px 500px at -10% 110%,rgba(143,127,212,.05),transparent 60%)",
  },
  wrap: { maxWidth: 1240, margin: "0 auto", padding: "0 28px" },
  centered: { minHeight: "70vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: 28 },

  topbar: { display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 34 },
  kicker: { fontSize: 11, letterSpacing: 3, color: "#a8a08c", fontWeight: 600, fontFamily: "IBM Plex Mono" },
  navLink: { fontSize: 11.5, color: "#a8a08c", textDecoration: "none", fontFamily: "IBM Plex Mono", letterSpacing: 0.5 },
  rule: { height: 1, background: "linear-gradient(90deg,#2a2f36,transparent)", margin: "20px 0 26px" },

  mastRow: { display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 24 },
  h1: { fontFamily: "'Fraunces', serif", fontWeight: 500, fontSize: 58, lineHeight: 1.0, margin: 0, letterSpacing: -1, color: "#f4efe3" },
  tagline: { fontSize: 14, color: "#a8a08c", marginTop: 12, maxWidth: 520, lineHeight: 1.5 },
  statusBar: { display: "flex", alignItems: "center", gap: 18, border: "1px solid #1d2127", borderRadius: 4, padding: "12px 18px", background: "#0e1113" },
  statusItem: { display: "flex", flexDirection: "column", gap: 4 },
  statusLabel: { fontSize: 9.5, letterSpacing: 1.5, color: "#7a7566", fontFamily: "IBM Plex Mono" },
  statusVal: { fontSize: 15, color: "#e8b34e", fontFamily: "IBM Plex Mono" },
  statusDivider: { width: 1, height: 30, background: "#1d2127" },

  panelHead: { display: "flex", gap: 14, alignItems: "baseline", marginBottom: 18 },
  panelNo: { fontFamily: "IBM Plex Mono", fontSize: 11, color: "#7a7566", borderRight: "1px solid #2a2f36", paddingRight: 14 },
  panelTitle: { fontFamily: "'Fraunces', serif", fontSize: 24, color: "#f4efe3" },
  panelSub: { fontSize: 11, color: "#7a7566", letterSpacing: 1, marginTop: 3, fontFamily: "IBM Plex Mono" },

  cardStrip: { display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 16 },
  fundCard: { background: "#0e1113", border: "1px solid #1d2127", borderRadius: 4, padding: "20px 20px 18px", display: "flex", flexDirection: "column" },
  ghostCard: { borderStyle: "dashed", borderWidth: 1, justifyContent: "flex-start" },
  ghostBody: { display: "flex", flexDirection: "column", alignItems: "center", gap: 14, padding: "34px 14px", textAlign: "center" },
  ghostText: { fontSize: 12.5, color: "#7a7566", lineHeight: 1.6, fontFamily: "IBM Plex Mono", maxWidth: 220 },
  cardArm: { fontFamily: "'Fraunces', serif", fontSize: 21, letterSpacing: -0.2 },
  cardHoldings: { fontSize: 11.5, color: "#a8a08c", fontFamily: "IBM Plex Mono", marginTop: 4 },
  cardMetricGrid: { display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 1, background: "#1d2127", border: "1px solid #1d2127", borderRadius: 4, overflow: "hidden", marginTop: 16 },
  cardMetric: { background: "#0c0f11", padding: "12px 10px" },
  cardMetricVal: { fontFamily: "IBM Plex Mono", fontSize: 17, lineHeight: 1 },
  cardMetricLabel: { fontSize: 9, letterSpacing: 0.8, color: "#7a7566", marginTop: 6, fontFamily: "IBM Plex Mono" },
  sparkWrap: { marginTop: 16, height: 64, display: "flex", flexDirection: "column", justifyContent: "center" },
  sparkEmpty: { fontSize: 10.5, color: "#7a7566", fontFamily: "IBM Plex Mono", height: 42, display: "flex", alignItems: "center" },
  sparkTag: { fontSize: 9, color: "#7a7566", letterSpacing: 0.5, fontFamily: "IBM Plex Mono", marginTop: 2 },
  cardSectors: { display: "flex", flexDirection: "column", gap: 6, marginTop: 14, flex: 1 },
  cardSectorsLabel: { fontSize: 9, letterSpacing: 1, color: "#7a7566", fontFamily: "IBM Plex Mono" },
  sectorChip: { fontSize: 11, color: "#a8a08c", fontFamily: "IBM Plex Mono", display: "flex", justifyContent: "space-between" },
  viewBtn: { marginTop: 18, display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6, fontSize: 12, fontFamily: "IBM Plex Mono", letterSpacing: 0.5, border: "1px solid", borderRadius: 4, padding: "9px 0", textDecoration: "none", background: "transparent" },

  tableScroll: { overflowX: "auto", border: "1px solid #1d2127", borderRadius: 4, background: "#0e1113" },
  cmpTable: { width: "100%", borderCollapse: "collapse", fontFamily: "IBM Plex Sans", minWidth: 560 },
  cmpTh: { fontSize: 10, letterSpacing: 1, color: "#7a7566", padding: "12px 16px", borderBottom: "1px solid #232830", textTransform: "uppercase", textAlign: "right", fontFamily: "IBM Plex Mono", whiteSpace: "nowrap" },
  cmpTr: { borderBottom: "1px solid #15181c" },
  cmpTd: { padding: "11px 16px", fontSize: 13, whiteSpace: "nowrap" },
  cmpRowLabel: { color: "#a8a08c", textAlign: "left" },
  cmpNum: { fontFamily: "IBM Plex Mono", color: "#f4efe3", textAlign: "right" },

  fwdMeta: { fontSize: 11.5, color: "#a8a08c", fontFamily: "IBM Plex Mono", marginBottom: 14 },
  fwdGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))", gap: 14 },
  fwdCard: { background: "#0e1113", border: "1px solid #1d2127", borderRadius: 4, padding: "16px 18px" },
  fwdArm: { fontFamily: "'Fraunces', serif", fontSize: 17 },
  fwdVs: { fontFamily: "IBM Plex Mono", fontSize: 11, color: "#7a7566" },
  fwdStatRow: { display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10, marginTop: 14 },
  fwdStatVal: { fontFamily: "IBM Plex Mono", fontSize: 15, color: "#f4efe3", lineHeight: 1 },
  fwdStatLabel: { fontSize: 9, letterSpacing: 0.6, color: "#7a7566", marginTop: 5, fontFamily: "IBM Plex Mono" },
  fwdSharpe: { marginTop: 14, paddingTop: 12, borderTop: "1px solid #1d2127", display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" },
  fwdSharpeLabel: { fontSize: 9, letterSpacing: 0.8, color: "#7a7566", fontFamily: "IBM Plex Mono" },
  fwdSharpeVal: { fontFamily: "IBM Plex Mono", fontSize: 16, color: "#f4efe3" },
  fwdSharpeCi: { fontSize: 10.5, color: "#7a7566", fontFamily: "IBM Plex Mono" },

  holding: { fontSize: 13, color: "#a8a08c", lineHeight: 1.7, background: "#0e1113", border: "1px solid #1d2127", borderRadius: 4, padding: "18px 20px", fontFamily: "IBM Plex Sans" },
  caveat: { fontSize: 12, color: "#7a7566", fontStyle: "italic", lineHeight: 1.65, marginTop: 14, maxWidth: 880, fontFamily: "IBM Plex Sans" },

  overlapStack: { display: "flex", flexDirection: "column", gap: 14 },
  overlapCard: { background: "#0e1113", border: "1px solid #1d2127", borderRadius: 4, padding: "16px 18px" },
  overlapHead: { display: "flex", alignItems: "baseline", gap: 8, fontFamily: "'Fraunces', serif", fontSize: 17, flexWrap: "wrap" },
  overlapVs: { fontFamily: "IBM Plex Mono", fontSize: 12, color: "#7a7566" },
  overlapStats: { marginLeft: "auto", fontFamily: "IBM Plex Mono", fontSize: 11.5, color: "#a8a08c", letterSpacing: 0.3 },
  overlapCols: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18, marginTop: 14 },
  overlapCol: {},
  overlapColLabel: { fontSize: 9.5, letterSpacing: 1, fontFamily: "IBM Plex Mono", marginBottom: 8 },
  chipWrap: { display: "flex", flexWrap: "wrap", gap: 5 },
  tickerChip: { fontSize: 10.5, color: "#cfc8b8", background: "#15181c", border: "1px solid #232830", borderRadius: 3, padding: "2px 7px", fontFamily: "IBM Plex Mono" },

  footer: { marginTop: 44, paddingTop: 22, borderTop: "1px solid #1d2127", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 16 },
  disclaimer: { fontSize: 11.5, color: "#7a7566", lineHeight: 1.7, maxWidth: 820, margin: 0, fontFamily: "IBM Plex Sans" },
  footerLink: { fontSize: 12, color: "#e8b34e", textDecoration: "none", fontFamily: "IBM Plex Mono", display: "inline-flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" },
};

const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
* { box-sizing: border-box; }
body { margin: 0; background: #0b0d0f; }
::selection { background: #e8b34e; color: #0b0d0f; }
a:hover { opacity: 0.82; }
.rise { opacity:0; transform:translateY(14px); animation:rise .7s cubic-bezier(.2,.7,.2,1) forwards; }
.d1{animation-delay:.06s} .d2{animation-delay:.12s} .d3{animation-delay:.18s} .d4{animation-delay:.24s}
@keyframes rise { to { opacity:1; transform:none; } }
.recharts-surface { overflow:visible; }
@media (prefers-reduced-motion: reduce) { .rise { animation: none; opacity: 1; transform: none; } }
@media (max-width: 880px) {
  [style*="repeat(3,1fr)"] { grid-template-columns: 1fr !important; }
}
@media (max-width: 600px) {
  [style*="grid-template-columns: 1fr 1fr"] { grid-template-columns: 1fr !important; }
}
`;

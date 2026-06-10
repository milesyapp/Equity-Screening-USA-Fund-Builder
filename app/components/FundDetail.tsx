"use client";

// app/components/FundDetail.tsx
// Per-arm deep dive: overview + metrics, full methodology prose, a sortable /
// searchable holdings table with a sticky detail panel, and (once the record
// accumulates) the realized forward-performance section. Reads /api/portfolio.

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import {
  ArrowLeft, Search, ChevronUp, ChevronDown, Cpu, Atom, FlaskConical,
} from "lucide-react";
import type {
  Screen, FundArm, StockPick, FundWindow, QuboDiagnostics,
} from "../../lib/types";

/* ── formatting ─────────────────────────────────────────────────────────── */
const pct = (x: number | null | undefined, d = 1) =>
  x == null || Number.isNaN(x) ? "—" : `${(x * 100).toFixed(d)}%`;
const signedPct = (x: number | null | undefined, d = 1) =>
  x == null || Number.isNaN(x) ? "—" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(d)}%`;
const num = (x: number | null | undefined, d = 2) =>
  x == null || Number.isNaN(x) ? "—" : x.toFixed(d);
const money = (x: number | null | undefined) => {
  if (x == null || Number.isNaN(x)) return "—";
  if (x >= 1e12) return `$${(x / 1e12).toFixed(2)}T`;
  if (x >= 1e9) return `$${(x / 1e9).toFixed(1)}B`;
  if (x >= 1e6) return `$${(x / 1e6).toFixed(0)}M`;
  return `$${x.toFixed(0)}`;
};
const fmtDate = (s?: string) => {
  if (!s) return "—";
  try {
    return new Date(s + "T00:00:00").toLocaleDateString("en-US", {
      year: "numeric", month: "short", day: "numeric",
    });
  } catch { return s; }
};

/* ── palette ────────────────────────────────────────────────────────────── */
const ARM_COLORS: Record<string, string> = {
  greedy: "#e8b34e", qubo_classical: "#6f8f7a", qubo_quantum: "#8f7fd4",
};
const ARM_TITLE: Record<string, string> = {
  greedy: "Greedy", qubo_classical: "QUBO Classical", qubo_quantum: "QUBO Quantum",
};
const GREEN = "#5a9e6f";
const RED = "#c46a5a";
const scoreColor = (s: number) => (s >= 75 ? GREEN : s >= 55 ? "#e8b34e" : "#7a7566");
const retColor = (x: number | null | undefined) =>
  x == null ? "#7a7566" : x >= 0 ? GREEN : RED;

/* ── holdings row model ─────────────────────────────────────────────────── */
interface Row {
  ticker: string;
  partial: boolean;          // true => ranked 101–150, not in published top-100
  stock: StockPick | null;
  weight: number | null;
}
type SortKey =
  | "rank" | "ticker" | "sector" | "score" | "healthScore" | "valuationScore"
  | "momentumScore" | "weight" | "peRatio" | "fcfYield" | "revenueGrowth"
  | "returnOnEquity" | "return6M" | "return3M";

const sortValue = (r: Row, k: SortKey): number | string | null => {
  if (k === "ticker") return r.ticker;
  if (k === "weight") return r.weight;
  if (k === "rank") return r.stock?.rank ?? null;
  if (k === "sector") return r.stock?.sector ?? null;
  if (!r.stock) return null;
  return r.stock[k as keyof StockPick] as number | null;
};

/* ── component ──────────────────────────────────────────────────────────── */
export default function FundDetail({ arm: armKey }: { arm: string }) {
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

  const color = ARM_COLORS[armKey] ?? "#e8b34e";
  const research = data?.research ?? null;
  const arm: FundArm | undefined = research?.arms.find((a) => a.key === armKey);

  /* holdings rows (hooks must run before any early return) */
  const stockByTicker = useMemo(() => {
    const m: Record<string, StockPick> = {};
    (data?.stocks ?? []).forEach((s) => { m[s.ticker] = s; });
    return m;
  }, [data]);

  const rows: Row[] = useMemo(() => {
    if (!arm) return [];
    return arm.selection.map((t) => {
      const stock = stockByTicker[t] ?? null;
      const weight = arm.weights[t] ?? stock?.fundWeight ?? null;
      return { ticker: t, partial: !stock, stock, weight };
    });
  }, [arm, stockByTicker]);

  const sectors = useMemo(() => {
    const set = new Set<string>();
    rows.forEach((r) => { if (r.stock) set.add(r.stock.sector); });
    return ["All", ...Array.from(set).sort()];
  }, [rows]);

  const [sortKey, setSortKey] = useState<SortKey>("weight");
  const [sortAsc, setSortAsc] = useState(false);
  const [query, setQuery] = useState("");
  const [sector, setSector] = useState("All");
  const [selected, setSelected] = useState<string | null>(null);

  const filtered = useMemo(() => {
    let r = rows;
    if (sector !== "All") r = r.filter((x) => x.stock?.sector === sector);
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      r = r.filter((x) =>
        x.ticker.toLowerCase().includes(q) ||
        (x.stock?.name ?? "").toLowerCase().includes(q));
    }
    const sorted = [...r].sort((a, b) => {
      const av = sortValue(a, sortKey), bv = sortValue(b, sortKey);
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") return sortAsc ? av - bv : bv - av;
      return sortAsc
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av));
    });
    return sorted;
  }, [rows, sector, query, sortKey, sortAsc]);

  const selRow = filtered.find((r) => r.ticker === selected) ?? rows.find((r) => r.ticker === selected) ?? null;

  /* ── error / loading ─────────────────────────────────────────────────── */
  if (error) {
    return <Shell color={color}><div style={S.centered}>
      <p style={{ fontSize: 16, marginBottom: 8 }}>Couldn&apos;t load this fund.</p>
      <p style={{ fontSize: 13, color: "#7a7566", fontFamily: "IBM Plex Mono" }}>/api/portfolio: {error}</p>
    </div></Shell>;
  }
  if (!data || !research) {
    return <Shell color={color}><div style={S.centered}>
      <p style={{ fontSize: 14, color: "#7a7566", fontFamily: "IBM Plex Mono" }}>Loading fund…</p>
    </div></Shell>;
  }

  /* ── arm not yet present (e.g. qubo_quantum before D-Wave access) ─────── */
  if (!arm) {
    const known = armKey in ARM_TITLE;
    return (
      <Shell color={color}>
        <div style={{ ...S.ghostPage, borderColor: color }}>
          <FlaskConical size={26} color={color} />
          <h1 style={{ ...S.ghostTitle, color }}>{ARM_TITLE[armKey] ?? armKey}</h1>
          <p style={S.ghostMsg}>
            {known
              ? "Hardware arm activates on next weekly run after D-Wave access is granted."
              : "No arm with this key exists in the current run."}
          </p>
          <Link href="/" style={{ ...S.backLink, color }}>
            <ArrowLeft size={14} /> Back to research home
          </Link>
        </div>
      </Shell>
    );
  }

  const fund = arm.fund;
  const m = fund.metrics3Y;
  const b = fund.blended;
  const diag = arm.diagnostics;
  const fs = research.forwardStats;
  const fwdAvailable = fs.available;
  const fwdForArm = (fs.perArm ?? []).find((p) => p.arm === armKey);

  /* in-sample NAV + benchmark + realized-forward overlay, merged by date */
  const navData = useMemo(() => {
    const map = new Map<string, { date: string; fund?: number; benchmark?: number; forward?: number }>();
    fund.navSeries.forEach((p) => map.set(p.date, { date: p.date, fund: p.fund, benchmark: p.benchmark }));
    (research.forwardNav ?? []).forEach((r) => {
      const v = r[armKey];
      if (typeof v === "number") {
        const e = map.get(r.date) ?? { date: r.date };
        e.forward = v;
        map.set(r.date, e);
      }
    });
    return Array.from(map.values()).sort((a, z) => a.date.localeCompare(z.date));
  }, [fund.navSeries, research.forwardNav, armKey]);

  return (
    <Shell color={color}>
      {/* breadcrumb */}
      <div style={S.topbar} className="rise">
        <Link href="/" style={S.crumb}><ArrowLeft size={13} /> Research home</Link>
        <Link href="/screener" style={S.crumb}>Full screener →</Link>
      </div>

      {/* ── SECTION 1 · OVERVIEW ──────────────────────────────────────── */}
      <section style={{ ...S.wrap, ...S.overviewWrap, borderLeft: `3px solid ${color}` }} className="rise d1">
        <div style={S.armRow}>
          {armKey === "qubo_quantum" ? <Atom size={22} color={color} />
            : armKey === "qubo_classical" ? <Cpu size={22} color={color} />
            : <FlaskConical size={22} color={color} />}
          <div>
            <h1 style={{ ...S.h1, color }}>{ARM_TITLE[armKey] ?? armKey}</h1>
            <div style={S.armLabel}>{arm.label}</div>
          </div>
        </div>

        <div style={S.metricGrid}>
          <Metric label="HOLDINGS" value={String(fund.constituents)} />
          <Metric label="3Y RETURN" value={pct(m?.annualReturn)} color={GREEN} />
          <Metric label="3Y SHARPE" value={num(m?.sharpeRatio)} />
          <Metric label="3Y MAX DD" value={pct(m?.maximumDrawdown)} color={RED} />
          <Metric label="3Y ALPHA" value={pct(m?.alpha)} />
          <Metric label="3Y BETA (vs IVV)" value={num(m?.beta)} />
          <Metric label="VOLATILITY" value={pct(m?.annualVolatility)} />
        </div>

        <div style={S.blendedLabel}>BLENDED FUNDAMENTALS</div>
        <div style={S.blendedRow}>
          <Metric label="P/E" value={num(b.pe, 1)} small />
          <Metric label="FCF YIELD" value={pct(b.fcfYield)} small />
          <Metric label="REV GROWTH" value={pct(b.revenueGrowth)} small color={GREEN} />
          <Metric label="ROE" value={pct(b.returnOnEquity)} small />
          <Metric label="NET MARGIN" value={pct(b.netMargin)} small />
        </div>

        {/* NAV chart */}
        <div style={S.chartHead}>
          <span style={S.chartTitle}>Net asset value</span>
        </div>
        <div style={{ width: "100%", height: 300 }}>
          <ResponsiveContainer>
            <LineChart data={navData} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
              <CartesianGrid stroke="#15181c" vertical={false} />
              <XAxis dataKey="date" tick={{ fill: "#7a7566", fontSize: 10, fontFamily: "IBM Plex Mono" }}
                tickLine={false} axisLine={{ stroke: "#1d2127" }} minTickGap={48} />
              <YAxis tick={{ fill: "#7a7566", fontSize: 10, fontFamily: "IBM Plex Mono" }}
                tickLine={false} axisLine={false} width={44} domain={["auto", "auto"]} />
              <Tooltip contentStyle={TIP} labelStyle={{ color: "#a8a08c", fontFamily: "IBM Plex Mono", fontSize: 11 }}
                itemStyle={{ fontFamily: "IBM Plex Mono", fontSize: 12 }} />
              <Line type="monotone" dataKey="fund" name="In-sample basket" stroke={color}
                strokeWidth={1.6} dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="benchmark" name="Benchmark (IVV)" stroke="#5a9e6f"
                strokeWidth={1.1} strokeOpacity={0.55} dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="forward" name="Realized forward" stroke={color}
                strokeWidth={2.2} strokeDasharray="2 2" connectNulls={false}
                dot={{ r: 2, fill: color }} isAnimationActive={false} />
              <Legend wrapperStyle={{ fontFamily: "IBM Plex Mono", fontSize: 10.5, color: "#a8a08c" }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <p style={S.chartNote}>
          The solid line is an <b style={{ color: "#cfc8b8" }}>in-sample characterisation of the current
          basket, not a track record</b> — today&apos;s weights applied backward. The benchmark (IVV) is
          overlaid in muted green. The dashed line is the{" "}
          <b style={{ color }}>realized forward record from {fmtDate(research.inceptionDate)}</b>,
          rebased to $1 at inception, so it sits near 1.0 at the right edge while the multi-year
          in-sample curve is on a different base.
        </p>
      </section>

      {/* ── SECTION 2 · METHODOLOGY ───────────────────────────────────── */}
      <section style={{ ...S.wrap, marginTop: 40 }} className="rise d2">
        <PanelHead n="02" title="Methodology" sub="HOW THIS BASKET IS BUILT" />
        <Methodology armKey={armKey} diag={diag} color={color} />
      </section>

      {/* ── SECTION 3 · HOLDINGS ──────────────────────────────────────── */}
      <section style={{ ...S.wrap, marginTop: 40 }} className="rise d3">
        <PanelHead n="03" title="Holdings" sub={`${rows.length} SELECTED NAMES`} />
        <div style={S.controls}>
          <div style={S.searchBox}>
            <Search size={14} color="#7a7566" />
            <input style={S.searchInput} placeholder="Search ticker or company"
              value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <select style={S.select} value={sector} onChange={(e) => setSector(e.target.value)}>
            {sectors.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <span style={S.resultCount}>{filtered.length} shown</span>
        </div>

        <div style={S.split}>
          <div style={S.tableWrap}>
            <div style={S.tableScroll}>
              <table style={S.table}>
                <thead>
                  <tr>
                    {HEADERS.map((h) => (
                      <th key={h.key}
                        style={{ ...S.th, textAlign: h.align, cursor: "pointer" }}
                        className={h.narrow ? "" : "hide-narrow"}
                        onClick={() => {
                          if (sortKey === h.key) setSortAsc(!sortAsc);
                          else { setSortKey(h.key); setSortAsc(false); }
                        }}>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                          {h.label}
                          {sortKey === h.key && (sortAsc ? <ChevronUp size={11} /> : <ChevronDown size={11} />)}
                        </span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.length === 0 ? (
                    <tr><td colSpan={HEADERS.length} style={S.noRows}>No matches.</td></tr>
                  ) : filtered.map((r, i) => {
                    const s = r.stock;
                    const top10 = i < 10;
                    const isSel = r.ticker === selected;
                    return (
                      <tr key={r.ticker}
                        style={{
                          ...S.tr,
                          background: isSel ? "rgba(232,179,78,.10)" : top10 ? "rgba(232,179,78,.04)" : "transparent",
                        }}
                        onMouseEnter={() => setSelected(r.ticker)}
                        onClick={() => setSelected(r.ticker)}>
                        <td style={{ ...S.td, ...S.mono }}>{s?.rank ?? "—"}</td>
                        <td style={S.td}>
                          <span style={S.coCell}>
                            <span style={S.coTk}>{r.ticker}</span>
                            <span style={S.coName}>{s?.name ?? "candidate pool (101–150)"}</span>
                          </span>
                        </td>
                        <td style={{ ...S.td }} className="hide-narrow"><span style={S.sectorCell}>{s?.sector ?? "—"}</span></td>
                        <td style={{ ...S.td }}>
                          {s ? (
                            <span style={S.scoreWrap}>
                              <span style={S.scoreBarTrack}>
                                <span style={{ ...S.scoreBarFill, width: `${s.score}%`, background: scoreColor(s.score) }} />
                              </span>
                              <b style={{ ...S.scoreNum, color: scoreColor(s.score) }}>{s.score.toFixed(1)}</b>
                            </span>
                          ) : <span style={S.mono}>—</span>}
                        </td>
                        <td style={{ ...S.td, ...S.mono }} className="hide-narrow">{s ? s.healthScore.toFixed(0) : "—"}</td>
                        <td style={{ ...S.td, ...S.mono }} className="hide-narrow">{s ? s.valuationScore.toFixed(0) : "—"}</td>
                        <td style={{ ...S.td, ...S.mono }} className="hide-narrow">{s ? s.momentumScore.toFixed(0) : "—"}</td>
                        <td style={{ ...S.td, ...S.mono, color: "#e8b34e" }}>{pct(r.weight, 2)}</td>
                        <td style={{ ...S.td, ...S.mono }} className="hide-narrow">{num(s?.peRatio, 1)}</td>
                        <td style={{ ...S.td, ...S.mono }} className="hide-narrow">{pct(s?.fcfYield)}</td>
                        <td style={{ ...S.td, ...S.mono, color: retColor(s?.revenueGrowth) }} className="hide-narrow">{signedPct(s?.revenueGrowth, 0)}</td>
                        <td style={{ ...S.td, ...S.mono }} className="hide-narrow">{pct(s?.returnOnEquity, 0)}</td>
                        <td style={{ ...S.td, ...S.mono, color: retColor(s?.return6M) }} className="hide-narrow">{signedPct(s?.return6M, 1)}</td>
                        <td style={{ ...S.td, ...S.mono, color: retColor(s?.return3M) }} className="hide-narrow">{signedPct(s?.return3M, 1)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* detail panel */}
          <div style={S.detailWrap}>
            <div style={S.detail}>
              {!selRow ? (
                <p style={S.detailEmpty}>Hover or tap a holding to inspect it.</p>
              ) : (
                <HoldingDetail row={selRow} color={color} />
              )}
            </div>
          </div>
        </div>
      </section>

      {/* ── SECTION 4 · FORWARD PERFORMANCE (only when available) ─────── */}
      {fwdAvailable && fwdForArm && (
        <section style={{ ...S.wrap, marginTop: 40 }} className="rise d4">
          <PanelHead n="04" title="Forward performance" sub="REALIZED OUT-OF-SAMPLE RECORD" />
          <div style={S.fwdMeta}>{fwdForArm.nDays} days on record · vs {ARM_TITLE[fwdForArm.vsBaseline] ?? fwdForArm.vsBaseline}</div>
          <div style={S.fwdStatRow4}>
            <Metric label="ACTIVE RETURN" value={signedPct(fwdForArm.activeReturnAnnualised)} small />
            <Metric label="TRACKING ERR" value={pct(fwdForArm.trackingError)} small />
            <Metric label="INFO RATIO" value={num(fwdForArm.informationRatio)} small />
            <Metric label="SHARPE Δ" value={num(fwdForArm.sharpeDifference.difference)} small />
            <Metric label="NEWEY-WEST t" value={num(fwdForArm.neweyWestT_meanActive)} small />
          </div>
          <p style={S.ciLine}>
            {fwdForArm.sharpeDifference.ci95
              ? `Sharpe Δ 95% CI [${num(fwdForArm.sharpeDifference.ci95[0])}, ${num(fwdForArm.sharpeDifference.ci95[1])}]`
              : "Sharpe Δ 95% CI —"}
            {" · p "}
            {fwdForArm.sharpeDifference.pValue == null ? "—" : fwdForArm.sharpeDifference.pValue.toFixed(3)}
          </p>
          <div style={{ width: "100%", height: 220, marginTop: 10 }}>
            <ResponsiveContainer>
              <LineChart data={research.forwardNav ?? []} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
                <CartesianGrid stroke="#15181c" vertical={false} />
                <XAxis dataKey="date" tick={{ fill: "#7a7566", fontSize: 10, fontFamily: "IBM Plex Mono" }}
                  tickLine={false} axisLine={{ stroke: "#1d2127" }} minTickGap={40} />
                <YAxis tick={{ fill: "#7a7566", fontSize: 10, fontFamily: "IBM Plex Mono" }}
                  tickLine={false} axisLine={false} width={44} domain={["auto", "auto"]} />
                <Tooltip contentStyle={TIP} />
                <Line type="monotone" dataKey={fwdForArm.vsBaseline} name="Baseline" stroke="#e8b34e"
                  strokeWidth={1.4} dot={false} connectNulls isAnimationActive={false} />
                <Line type="monotone" dataKey={armKey} name={ARM_TITLE[armKey]} stroke={color}
                  strokeWidth={1.8} dot={false} connectNulls isAnimationActive={false} />
                <Legend wrapperStyle={{ fontFamily: "IBM Plex Mono", fontSize: 10.5 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p style={S.chartNote}>Realized forward returns only.</p>
          {fs.caveat && <p style={S.caveat}>{fs.caveat}</p>}
        </section>
      )}

      <footer style={{ ...S.wrap, ...S.footer }}>
        <p style={S.disclaimer}>{research.disclaimer}</p>
      </footer>
    </Shell>
  );
}

/* ── methodology prose (arm-specific) ───────────────────────────────────── */
function Methodology({ armKey, diag, color }: { armKey: string; diag: QuboDiagnostics | null; color: string }) {
  const isQubo = armKey === "qubo_classical" || armKey === "qubo_quantum";
  const isQuantum = armKey === "qubo_quantum";
  return (
    <div style={S.method}>
      <H>Universe &amp; scoring</H>
      <P>
        The candidate universe is the combined S&amp;P 500 / 400 / 600 — roughly 1,506 names — screened
        down to about 750 with usable, complete fundamentals. Every survivor is scored on three pillars:{" "}
        <b style={B}>Financial Health (70%)</b>, <b style={B}>Valuation (20%)</b>, and{" "}
        <b style={B}>Momentum (10%)</b>.
      </P>
      <P>
        <b style={B}>Health</b> blends return on equity, operating margin, net margin, free-cash-flow
        margin, year-over-year revenue growth, and debt/equity (inverted, so less leverage scores
        higher). <b style={B}>Valuation</b> uses P/E (inverted, negatives excluded), FCF yield, and PEG
        (inverted, positive growth only). <b style={B}>Momentum</b> reads 6-month and 3-month price
        return. Each raw metric is converted to a percentile rank across the universe before it is
        blended — this makes the composite robust to outliers and to the inconsistent scales between,
        say, a margin and a debt ratio.
      </P>

      {!isQubo && (
        <>
          <H>Construction</H>
          <P>
            The top 100 names by composite score form the fund. Each is weighted by its score divided by
            the sum of all selected scores, then capped at 4% per name with the excess redistributed
            proportionally across the rest. There is no optimisation step — the greedy fund simply takes
            the highest scorers and weights them.
          </P>
        </>
      )}

      {isQubo && (
        <>
          <H>Why QUBO</H>
          <P>
            The greedy fund never looks at how holdings move <i>together</i>. Two highly correlated
            high-scorers can both make the cut even though owning both adds little real diversification.
            The QUBO arm optimises selection and diversification at the same time, rather than ranking
            names in isolation.
          </P>
          <H>The objective, in plain English</H>
          <P>Selection is posed as one optimisation that balances four competing pulls:</P>
          <ul style={S.ul}>
            <li style={S.li}><b style={B}>Quality</b> — reward including high-scoring names.</li>
            <li style={S.li}><b style={B}>Risk</b> — penalise including pairs whose returns are highly correlated.</li>
            <li style={S.li}><b style={B}>Size</b> — penalise drifting away from the 100-name target.</li>
            <li style={S.li}><b style={B}>Sector concentration</b> — penalise pairs drawn from the same sector.</li>
          </ul>
          <H>The lambda weights</H>
          <P>
            Four hyperparameters set how hard each pull is felt: <Code>λ1 = 1.0</Code> (quality),{" "}
            <Code>λ2 = 1.0</Code> (risk), <Code>λ3 = 3.0</Code> (size), <Code>λ4 = 0.1</Code> (sector).
            λ3 is deliberately the largest so the optimiser keeps the basket near 100 names; λ1 and λ2 are
            balanced so quality and covariance-aware diversification trade off roughly one-for-one; λ4 is a
            light touch that nudges sector spread without overriding quality.
          </P>
          <H>Candidate pool &amp; solver</H>
          <P>
            The QUBO is fed the top <b style={B}>150</b> names by score — not 100 — so the optimiser has
            room to trade a little score for better diversification. {isQuantum ? (
              <>It is then solved on <b style={{ color }}>D-Wave&apos;s LeapHybridSampler</b>, quantum
              annealing hardware.</>
            ) : (
              <>It is solved with a <b style={{ color }}>SimulatedAnnealingSampler</b> — a classical
              solver. Using a classical solver demonstrates the QUBO objective independently of any
              quantum hardware, which is exactly what makes this the controlled comparison arm.</>
            )} The optimiser returns roughly 96–100 names, which are then score-weighted with the same
            capped scheme as the greedy fund — the continuous weighting is classical; only the selection
            is the QUBO step.
          </P>

          {isQuantum && (
            <>
              <H>What quantum annealing is</H>
              <P>
                Quantum annealing is a physical process: quantum fluctuations let the system tunnel
                straight through energy barriers, where classical simulated annealing has to climb over
                them thermally. In principle that lets the hardware reach lower-energy — i.e. better —
                solutions on the right kind of problem.
              </P>
              <H>Why annealing fits this problem</H>
              <P>
                Portfolio selection is combinatorial — which <i>combination</i> of stocks gives the best
                portfolio — and combinatorial optimisation is precisely what quantum annealing was built
                to attack.
              </P>
            </>
          )}

          <H>The controlled comparison</H>
          <P>
            {isQuantum ? (
              <>QUBO-classical versus QUBO-quantum isolates the <b style={B}>solver</b>. Both arms solve an
              identical problem — built once, handed to two different samplers — so any performance
              difference between them is attributable to the quantum solver alone.</>
            ) : (
              <>Because both QUBO arms solve the <b style={B}>identical</b> problem, the greedy vs
              QUBO-classical gap measures the <b style={B}>objective-function effect</b>: does
              covariance-aware selection help at all, before any quantum hardware enters the picture?</>
            )}
          </P>

          {isQuantum && (
            <P style={{ color: "#7a7566", fontStyle: "italic" }}>
              Honest caveat: at 150 binary variables this is a small problem for both classical and
              quantum solvers. Quantum advantage has not been demonstrated at this scale on current
              hardware. This experiment is built to measure whether it exists — not to assert that it
              does — and the comparison grows more informative over time and as hardware improves.
            </P>
          )}
        </>
      )}

      <H>An honest caveat</H>
      <P style={{ color: "#7a7566", fontStyle: "italic" }}>
        All scoring is backward-looking — drawn from each company&apos;s last annual filing, which can be
        up to twelve months old. The in-sample metrics apply today&apos;s weights backward, so they
        characterise the current basket; they are not a track record. The live forward record begins from
        the deployment date and is the only out-of-sample evidence.
      </P>

      {/* diagnostics */}
      {diag && (
        <div style={S.diagBox}>
          <div style={S.diagTitle}>SOLVER DIAGNOSTICS</div>
          <div style={S.diagGrid}>
            <Diag label="Solver" value={diag.solver} />
            <Diag label="Best energy" value={num(diag.bestEnergy, 2)} />
            <Diag label="Energy std" value={num(diag.energyStd, 3)} />
            <Diag label="Wall time" value={diag.wallSeconds == null ? "—" : `${diag.wallSeconds.toFixed(2)}s`} />
            <Diag label="Num reads" value={diag.numReads == null ? "—" : String(diag.numReads)} />
            <Diag label="Target size" value={diag.targetSize == null ? "—" : String(diag.targetSize)} />
            {diag.lambdas && (
              <Diag label="Lambdas" value={`λ1 ${diag.lambdas.l1} · λ2 ${diag.lambdas.l2} · λ3 ${diag.lambdas.l3} · λ4 ${diag.lambdas.l4}`} wide />
            )}
            {diag.chainBreakFraction != null && (
              <Diag label="Chain breaks" value={diag.chainBreakFraction.toFixed(4)} wide />
            )}
          </div>
          {diag.chainBreakFraction != null && (
            <p style={S.diagNote}>
              Chain breaks occur when the qubit chains representing a single variable disagree; lower is
              better.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/* ── holding detail panel ───────────────────────────────────────────────── */
function HoldingDetail({ row, color }: { row: Row; color: string }) {
  const s = row.stock;
  if (!s) {
    return (
      <div>
        <div style={S.detailTop}>
          <span style={S.detailTk}>{row.ticker}</span>
        </div>
        <div style={S.detailSector}>Candidate pool · ranked 101–150 by score</div>
        <p style={S.partialNote}>
          This name sits in the QUBO candidate pool beyond the published top 100, so per-stock
          fundamentals aren&apos;t in this dataset. Its fund weight is shown below; blended fund-level
          fundamentals appear in the overview.
        </p>
        <div style={S.fundWeightRow}>Fund weight · <b style={{ color: "#e8b34e" }}>{pct(row.weight, 2)}</b></div>
      </div>
    );
  }
  return (
    <div>
      <div style={S.detailTop}>
        <span style={S.detailTk}>{s.ticker}</span>
        <span style={S.detailRank}>#{s.rank}</span>
        <span style={{ ...S.detailPrice, marginLeft: "auto" }}>{s.price == null ? "—" : `$${s.price.toFixed(2)}`}</span>
      </div>
      <div style={S.detailName}>{s.name}</div>
      <div style={S.detailSector}>{s.sector} · {s.subIndustry}</div>

      <div style={S.scoreBreakdown}>
        {([["Composite", s.score], ["Health", s.healthScore], ["Valuation", s.valuationScore], ["Momentum", s.momentumScore]] as [string, number][]).map(([label, v]) => (
          <div key={label} style={S.sbRow}>
            <span style={S.sbLabel}>{label}</span>
            <span style={S.sbTrack}>
              <span style={{ ...S.sbFill, width: `${v}%`, height: 4, background: scoreColor(v) }} />
            </span>
            <b style={{ ...S.sbNum, color: scoreColor(v) }}>{v.toFixed(1)}</b>
          </div>
        ))}
      </div>

      <div style={S.detailSectionLabel}>FUNDAMENTALS</div>
      <div style={S.fundGridMini}>
        <Mini label="P/E" value={num(s.peRatio, 1)} />
        <Mini label="FCF YIELD" value={pct(s.fcfYield)} />
        <Mini label="REV GROWTH" value={signedPct(s.revenueGrowth, 0)} />
        <Mini label="ROE" value={pct(s.returnOnEquity, 0)} />
        <Mini label="NET MARGIN" value={pct(s.netMargin, 0)} />
        <Mini label="OP MARGIN" value={pct(s.operatingMargin, 0)} />
        <Mini label="GROSS MARGIN" value={pct(s.grossMargin, 0)} />
        <Mini label="FCF MARGIN" value={pct(s.fcfMargin, 0)} />
        <Mini label="DEBT/EQUITY" value={num(s.debtToEquity, 2)} />
        <Mini label="DIV YIELD" value={pct(s.dividendYield)} />
        <Mini label="MKT CAP" value={money(s.marketCap)} />
        <Mini label="FUND WT" value={pct(row.weight, 2)} accent />
      </div>

      <div style={S.detailSectionLabel}>TRAILING RETURNS</div>
      <div style={S.returnRow}>
        {([["1W", s.return1W], ["1M", s.return1M], ["3M", s.return3M], ["6M", s.return6M], ["1Y", s.return1Y]] as [string, number | null][]).map(([label, v]) => (
          <div key={label} style={S.returnCell}>
            <div style={{ ...S.returnVal, color: retColor(v) }}>{signedPct(v, 0)}</div>
            <div style={S.returnLabel}>{label}</div>
          </div>
        ))}
      </div>

      {s.reasons.length > 0 && (
        <>
          <div style={S.detailSectionLabel}>WHY IT SCORED</div>
          <ul style={S.reasonList}>
            {s.reasons.map((r, i) => (
              <li key={i} style={S.reasonItem}><span style={{ ...S.reasonTick, color }}>›</span>{r}</li>
            ))}
          </ul>
        </>
      )}
      {s.flags.length > 0 && (
        <>
          <div style={S.detailSectionLabel}>FLAGS</div>
          <div style={S.chipWrap}>
            {s.flags.map((f) => <span key={f} style={S.flagChip}>{f}</span>)}
          </div>
        </>
      )}
    </div>
  );
}

/* ── tiny helpers ───────────────────────────────────────────────────────── */
function Shell({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <div style={{ ...S.root, ["--arm" as string]: color }}>
      <style>{CSS}</style>
      {children}
    </div>
  );
}
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
function Metric({ label, value, color, small }: { label: string; value: string; color?: string; small?: boolean }) {
  return (
    <div style={S.metricCell}>
      <div style={{ ...(small ? S.metricValSm : S.metricVal), color: color ?? "#f4efe3" }}>{value}</div>
      <div style={S.metricLabel}>{label}</div>
    </div>
  );
}
function Mini({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div style={S.miniCell}>
      <div style={{ ...S.miniVal, color: accent ? "#e8b34e" : "#f4efe3" }}>{value}</div>
      <div style={S.miniLabel}>{label}</div>
    </div>
  );
}
function Diag({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return (
    <div style={{ ...S.diagCell, gridColumn: wide ? "1 / -1" : undefined }}>
      <span style={S.diagLabel}>{label}</span>
      <span style={S.diagVal}>{value}</span>
    </div>
  );
}
const H = ({ children }: { children: React.ReactNode }) => <h3 style={S.methodH}>{children}</h3>;
const P = ({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) =>
  <p style={{ ...S.methodP, ...style }}>{children}</p>;
const Code = ({ children }: { children: React.ReactNode }) => <code style={S.code}>{children}</code>;
const B: React.CSSProperties = { color: "#cfc8b8", fontWeight: 600 };

/* ── column headers ─────────────────────────────────────────────────────── */
const HEADERS: { key: SortKey; label: string; align: "left" | "right"; narrow?: boolean }[] = [
  { key: "rank", label: "#", align: "right", narrow: true },
  { key: "ticker", label: "Company", align: "left", narrow: true },
  { key: "sector", label: "Sector", align: "left" },
  { key: "score", label: "Score", align: "right", narrow: true },
  { key: "healthScore", label: "Health", align: "right" },
  { key: "valuationScore", label: "Val", align: "right" },
  { key: "momentumScore", label: "Mom", align: "right" },
  { key: "weight", label: "Weight", align: "right", narrow: true },
  { key: "peRatio", label: "P/E", align: "right" },
  { key: "fcfYield", label: "FCF Yld", align: "right" },
  { key: "revenueGrowth", label: "Rev Gr", align: "right" },
  { key: "returnOnEquity", label: "ROE", align: "right" },
  { key: "return6M", label: "6M", align: "right" },
  { key: "return3M", label: "3M", align: "right" },
];

const TIP: React.CSSProperties = { background: "#11151a", border: "1px solid #232830", borderRadius: 4, fontFamily: "IBM Plex Mono", fontSize: 12, color: "#f4efe3" };

/* ── styles ─────────────────────────────────────────────────────────────── */
const S: Record<string, React.CSSProperties> = {
  root: {
    background: "#0b0d0f", minHeight: "100vh", paddingBottom: 64,
    fontFamily: "'IBM Plex Sans', sans-serif", color: "#f4efe3",
  },
  wrap: { maxWidth: 1240, margin: "0 auto", padding: "0 28px" },
  centered: { minHeight: "70vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: 28 },

  topbar: { maxWidth: 1240, margin: "0 auto", padding: "26px 28px 0", display: "flex", justifyContent: "space-between" },
  crumb: { fontSize: 11.5, color: "#a8a08c", textDecoration: "none", fontFamily: "IBM Plex Mono", display: "inline-flex", alignItems: "center", gap: 5 },

  overviewWrap: { marginTop: 22, paddingTop: 4, paddingBottom: 4 },
  armRow: { display: "flex", alignItems: "center", gap: 14, paddingLeft: 18 },
  h1: { fontFamily: "'Fraunces', serif", fontWeight: 500, fontSize: 46, lineHeight: 1, margin: 0, letterSpacing: -0.8 },
  armLabel: { fontSize: 12.5, color: "#a8a08c", marginTop: 6, fontFamily: "IBM Plex Mono" },

  metricGrid: { display: "grid", gridTemplateColumns: "repeat(7,1fr)", gap: 1, background: "#1d2127", border: "1px solid #1d2127", borderRadius: 4, overflow: "hidden", marginTop: 24, marginLeft: 18 },
  metricCell: { background: "#0e1113", padding: "16px 14px" },
  metricVal: { fontFamily: "IBM Plex Mono", fontSize: 22, lineHeight: 1, letterSpacing: -0.5 },
  metricValSm: { fontFamily: "IBM Plex Mono", fontSize: 17, lineHeight: 1 },
  metricLabel: { fontSize: 9, letterSpacing: 0.8, color: "#7a7566", marginTop: 9, fontFamily: "IBM Plex Mono" },

  blendedLabel: { fontSize: 9.5, letterSpacing: 1.5, color: "#7a7566", margin: "22px 0 10px 18px", fontFamily: "IBM Plex Mono" },
  blendedRow: { display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 1, background: "#1d2127", border: "1px solid #1d2127", borderRadius: 4, overflow: "hidden", marginLeft: 18 },

  chartHead: { display: "flex", justifyContent: "space-between", alignItems: "baseline", margin: "28px 0 6px 18px" },
  chartTitle: { fontFamily: "'Fraunces', serif", fontSize: 18, color: "#f4efe3" },
  chartNote: { fontSize: 11.5, color: "#7a7566", lineHeight: 1.65, marginTop: 8, marginLeft: 18, maxWidth: 900, fontFamily: "IBM Plex Sans" },

  panelHead: { display: "flex", gap: 14, alignItems: "baseline", marginBottom: 18 },
  panelNo: { fontFamily: "IBM Plex Mono", fontSize: 11, color: "#7a7566", borderRight: "1px solid #2a2f36", paddingRight: 14 },
  panelTitle: { fontFamily: "'Fraunces', serif", fontSize: 24, color: "#f4efe3" },
  panelSub: { fontSize: 11, color: "#7a7566", letterSpacing: 1, marginTop: 3, fontFamily: "IBM Plex Mono" },

  method: { maxWidth: 820, background: "#0e1113", border: "1px solid #1d2127", borderRadius: 6, padding: "26px 30px" },
  methodH: { fontFamily: "'Fraunces', serif", fontSize: 19, color: "#f4efe3", margin: "22px 0 8px", fontWeight: 500 },
  methodP: { fontSize: 14, lineHeight: 1.75, color: "#a8a08c", margin: "0 0 12px" },
  ul: { margin: "0 0 12px", padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 7 },
  li: { fontSize: 14, lineHeight: 1.6, color: "#a8a08c", paddingLeft: 16, position: "relative" },
  code: { fontFamily: "IBM Plex Mono", fontSize: 12.5, color: "#e8b34e", background: "#15181c", border: "1px solid #232830", borderRadius: 3, padding: "1px 6px" },

  diagBox: { marginTop: 24, paddingTop: 18, borderTop: "1px solid #1d2127" },
  diagTitle: { fontSize: 9.5, letterSpacing: 1.5, color: "#7a7566", marginBottom: 12, fontFamily: "IBM Plex Mono" },
  diagGrid: { display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 1, background: "#1d2127", border: "1px solid #1d2127", borderRadius: 4, overflow: "hidden" },
  diagCell: { background: "#0c0f11", padding: "11px 13px", display: "flex", flexDirection: "column", gap: 5 },
  diagLabel: { fontSize: 9, letterSpacing: 0.6, color: "#7a7566", fontFamily: "IBM Plex Mono" },
  diagVal: { fontSize: 13, color: "#f4efe3", fontFamily: "IBM Plex Mono", wordBreak: "break-word" },
  diagNote: { fontSize: 11.5, color: "#7a7566", fontStyle: "italic", marginTop: 10, lineHeight: 1.6 },

  controls: { display: "flex", alignItems: "center", gap: 12, marginBottom: 14, flexWrap: "wrap" },
  searchBox: { display: "flex", alignItems: "center", gap: 8, background: "#0e1113", border: "1px solid #1d2127", borderRadius: 4, padding: "8px 12px", flex: 1, minWidth: 200, maxWidth: 360 },
  searchInput: { background: "transparent", border: "none", outline: "none", color: "#f4efe3", fontSize: 13, fontFamily: "IBM Plex Sans", width: "100%" },
  select: { background: "#0e1113", border: "1px solid #1d2127", borderRadius: 4, color: "#cfc8b8", fontSize: 12.5, padding: "8px 12px", fontFamily: "IBM Plex Sans", cursor: "pointer" },
  resultCount: { fontSize: 11.5, color: "#7a7566", fontFamily: "IBM Plex Mono", marginLeft: "auto" },

  split: { display: "grid", gridTemplateColumns: "1.55fr 1fr", gap: 18, alignItems: "start" },
  tableWrap: { background: "#0e1113", border: "1px solid #1d2127", borderRadius: 4, overflow: "hidden" },
  tableScroll: { maxHeight: 720, overflowY: "auto", overflowX: "auto" },
  table: { width: "100%", borderCollapse: "collapse", fontFamily: "IBM Plex Sans" },
  th: { position: "sticky", top: 0, zIndex: 2, background: "#11151a", fontSize: 10, letterSpacing: 0.8, color: "#7a7566", padding: "11px 12px", borderBottom: "1px solid #232830", whiteSpace: "nowrap", textTransform: "uppercase", userSelect: "none" },
  tr: { borderBottom: "1px solid #15181c", cursor: "pointer", transition: "background .12s ease" },
  td: { padding: "9px 12px", fontSize: 13, whiteSpace: "nowrap", verticalAlign: "middle" },
  noRows: { padding: 30, textAlign: "center", color: "#7a7566", fontSize: 13 },

  mono: { fontFamily: "IBM Plex Mono", fontSize: 12.5, color: "#cfc8b8" },
  coCell: { display: "flex", flexDirection: "column", gap: 1, minWidth: 0 },
  coTk: { fontFamily: "IBM Plex Mono", fontSize: 13, color: "#f4efe3", fontWeight: 600, letterSpacing: 0.3 },
  coName: { fontSize: 11, color: "#7a7566", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 200, whiteSpace: "nowrap" },
  sectorCell: { fontSize: 11.5, color: "#a8a08c" },
  scoreWrap: { display: "inline-flex", alignItems: "center", gap: 8, justifyContent: "flex-end", width: "100%" },
  scoreBarTrack: { width: 44, height: 4, background: "#1d2127", borderRadius: 3, overflow: "hidden", flexShrink: 0 },
  scoreBarFill: { display: "block", height: "100%", borderRadius: 3, transition: "width .2s ease" },
  scoreNum: { fontFamily: "IBM Plex Mono", fontSize: 12.5, minWidth: 32, textAlign: "right" },

  detailWrap: { position: "sticky", top: 16, alignSelf: "start" },
  detail: { background: "#0e1113", border: "1px solid #1d2127", borderRadius: 4, padding: "18px 20px", maxHeight: "calc(100vh - 32px)", overflowY: "auto" },
  detailEmpty: { fontSize: 12.5, color: "#7a7566", fontFamily: "IBM Plex Mono", lineHeight: 1.6 },
  detailTop: { display: "flex", alignItems: "baseline", gap: 4 },
  detailTk: { fontFamily: "IBM Plex Mono", fontSize: 22, color: "#f4efe3", fontWeight: 600, letterSpacing: 0.5 },
  detailRank: { fontFamily: "IBM Plex Mono", fontSize: 12, color: "#7a7566", marginLeft: 8 },
  detailPrice: { fontFamily: "IBM Plex Mono", fontSize: 16, color: "#e8b34e" },
  detailName: { fontFamily: "'Fraunces',serif", fontSize: 16, color: "#f4efe3", marginTop: 8 },
  detailSector: { fontSize: 11.5, color: "#7a7566", marginTop: 3, fontFamily: "IBM Plex Mono" },
  partialNote: { fontSize: 12, color: "#a8a08c", lineHeight: 1.6, marginTop: 14, fontFamily: "IBM Plex Sans" },

  scoreBreakdown: { display: "flex", flexDirection: "column", gap: 7, margin: "16px 0", padding: "14px 0", borderTop: "1px solid #1d2127", borderBottom: "1px solid #1d2127" },
  sbRow: { display: "flex", alignItems: "center", gap: 10 },
  sbLabel: { fontSize: 11.5, width: 76, flexShrink: 0, color: "#a8a08c" },
  sbTrack: { flex: 1, height: 4, background: "#1d2127", borderRadius: 3, overflow: "hidden", display: "flex", alignItems: "center" },
  sbFill: { display: "block", borderRadius: 3, transition: "width .25s ease" },
  sbNum: { fontFamily: "IBM Plex Mono", fontSize: 12, width: 38, textAlign: "right" },

  detailSectionLabel: { fontSize: 9.5, letterSpacing: 1.5, color: "#7a7566", marginTop: 16, marginBottom: 8, fontFamily: "IBM Plex Mono" },
  fundGridMini: { display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 1, background: "#1d2127", borderRadius: 4, overflow: "hidden" },
  miniCell: { background: "#0c0f11", padding: "11px 12px" },
  miniVal: { fontFamily: "IBM Plex Mono", fontSize: 14, color: "#f4efe3", lineHeight: 1 },
  miniLabel: { fontSize: 9, letterSpacing: 0.5, color: "#7a7566", marginTop: 5, fontFamily: "IBM Plex Mono" },

  returnRow: { display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 1, background: "#1d2127", borderRadius: 4, overflow: "hidden" },
  returnCell: { background: "#0c0f11", padding: "10px 6px", textAlign: "center" },
  returnVal: { fontFamily: "IBM Plex Mono", fontSize: 13, lineHeight: 1 },
  returnLabel: { fontSize: 9.5, color: "#7a7566", marginTop: 5, fontFamily: "IBM Plex Mono" },
  fundWeightRow: { marginTop: 16, fontSize: 13, fontFamily: "IBM Plex Mono", color: "#a8a08c" },

  reasonList: { listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 },
  reasonItem: { fontSize: 12.5, lineHeight: 1.5, color: "#a8a08c", display: "flex", gap: 8, alignItems: "flex-start" },
  reasonTick: { fontFamily: "IBM Plex Mono", fontWeight: 700, flexShrink: 0 },
  chipWrap: { display: "flex", flexWrap: "wrap", gap: 5 },
  flagChip: { fontSize: 10.5, color: "#c46a5a", background: "rgba(196,106,90,.08)", border: "1px solid rgba(196,106,90,.3)", borderRadius: 3, padding: "2px 7px", fontFamily: "IBM Plex Mono" },

  fwdMeta: { fontSize: 11.5, color: "#a8a08c", fontFamily: "IBM Plex Mono", marginBottom: 14 },
  fwdStatRow4: { display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 1, background: "#1d2127", border: "1px solid #1d2127", borderRadius: 4, overflow: "hidden" },
  ciLine: { fontSize: 11.5, color: "#7a7566", fontFamily: "IBM Plex Mono", marginTop: 12 },
  caveat: { fontSize: 12, color: "#7a7566", fontStyle: "italic", lineHeight: 1.65, marginTop: 12, maxWidth: 880, fontFamily: "IBM Plex Sans" },

  ghostPage: { maxWidth: 560, margin: "80px auto", textAlign: "center", border: "1px dashed", borderRadius: 6, padding: "48px 40px", display: "flex", flexDirection: "column", alignItems: "center", gap: 16, background: "#0e1113" },
  ghostTitle: { fontFamily: "'Fraunces', serif", fontSize: 34, margin: 0, fontWeight: 500 },
  ghostMsg: { fontSize: 13.5, color: "#a8a08c", lineHeight: 1.7, fontFamily: "IBM Plex Sans", maxWidth: 360 },
  backLink: { fontSize: 12.5, textDecoration: "none", fontFamily: "IBM Plex Mono", display: "inline-flex", alignItems: "center", gap: 6, marginTop: 6 },

  footer: { marginTop: 44, paddingTop: 22, borderTop: "1px solid #1d2127" },
  disclaimer: { fontSize: 11.5, color: "#7a7566", lineHeight: 1.7, maxWidth: 900, margin: 0, fontFamily: "IBM Plex Sans" },
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
li[style*="padding-left"]::before { content:"·"; position:absolute; left:2px; color:#e8b34e; }
@media (prefers-reduced-motion: reduce) { .rise { animation: none; opacity: 1; transform: none; } }
@media (max-width: 1000px) {
  [style*="grid-template-columns: 1.55fr 1fr"] { grid-template-columns: 1fr !important; }
  [style*="position: sticky"][style*="top: 16"] { position: static !important; }
}
@media (max-width: 820px) {
  [style*="repeat(7,1fr)"] { grid-template-columns: 1fr 1fr 1fr !important; }
  [style*="repeat(5,1fr)"] { grid-template-columns: 1fr 1fr 1fr !important; }
}
@media (max-width: 680px) {
  .hide-narrow { display: none !important; }
  [style*="repeat(3,1fr)"] { grid-template-columns: 1fr 1fr !important; }
}
`;

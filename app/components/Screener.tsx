"use client";

import React, { useMemo, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { Search, TrendingUp, ShieldCheck, Activity, Info, ChevronUp, ChevronDown } from "lucide-react";
import type { Screen, StockPick, FundWindow } from "../../lib/types";

/* ──────────────────────────────────────────────────────────────────────────
   Formatting helpers
   ────────────────────────────────────────────────────────────────────────── */
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
const titleCase = (s: string) =>
  s.replace(/([A-Z])/g, " $1").replace(/^./, (c) => c.toUpperCase()).trim();

const scoreColor = (s: number) => (s >= 75 ? "#7bbf95" : s >= 55 ? "#e8b34e" : "#b88a6a");
const retColor = (x: number | null | undefined) =>
  x == null ? "#8a8576" : x >= 0 ? "#7bbf95" : "#d98a72";

/* ──────────────────────────────────────────────────────────────────────────
   Table column definitions
   ────────────────────────────────────────────────────────────────────────── */
type ColKey =
  | "rank" | "ticker" | "sector" | "score"
  | "peRatio" | "fcfYield" | "revenueGrowth" | "returnOnEquity"
  | "return1M" | "return3M" | "return1Y";

interface Col {
  key: ColKey;
  label: string;
  align: "left" | "right";
  num: boolean;
  hideNarrow?: boolean;
  get: (s: StockPick) => number | string | null;
  render: (s: StockPick) => React.ReactNode;
}

const COLS: Col[] = [
  { key: "rank", label: "#", align: "left", num: true, get: (s) => s.rank,
    render: (s) => <span style={S.rankNum}>{s.rank}</span> },
  { key: "ticker", label: "Company", align: "left", num: false, get: (s) => s.ticker,
    render: (s) => (
      <span style={S.coCell}>
        <span style={S.coTk}>{s.ticker}</span>
        <span style={S.coName}>{s.name}</span>
      </span>
    ) },
  { key: "sector", label: "Sector", align: "left", num: false, hideNarrow: true, get: (s) => s.sector,
    render: (s) => <span style={S.sectorCell}>{s.sector}</span> },
  { key: "score", label: "Score", align: "right", num: true, get: (s) => s.score,
    render: (s) => (
      <span style={S.scoreWrap}>
        <span style={S.scoreBarTrack}>
          <span style={{ ...S.scoreBarFill, width: `${s.score}%`, background: scoreColor(s.score) }} />
        </span>
        <b style={{ ...S.scoreNum, color: scoreColor(s.score) }}>{s.score.toFixed(1)}</b>
      </span>
    ) },
  { key: "peRatio", label: "P/E", align: "right", num: true, get: (s) => s.peRatio,
    render: (s) => <span style={S.mono}>{num(s.peRatio, 1)}</span> },
  { key: "fcfYield", label: "FCF Yld", align: "right", num: true, hideNarrow: true, get: (s) => s.fcfYield,
    render: (s) => <span style={S.mono}>{pct(s.fcfYield, 1)}</span> },
  { key: "revenueGrowth", label: "Rev Gr", align: "right", num: true, hideNarrow: true, get: (s) => s.revenueGrowth,
    render: (s) => <span style={{ ...S.mono, color: retColor(s.revenueGrowth) }}>{signedPct(s.revenueGrowth, 0)}</span> },
  { key: "returnOnEquity", label: "ROE", align: "right", num: true, hideNarrow: true, get: (s) => s.returnOnEquity,
    render: (s) => <span style={S.mono}>{pct(s.returnOnEquity, 0)}</span> },
  { key: "return1M", label: "1M", align: "right", num: true, hideNarrow: true, get: (s) => s.return1M,
    render: (s) => <span style={{ ...S.mono, color: retColor(s.return1M) }}>{signedPct(s.return1M, 1)}</span> },
  { key: "return3M", label: "3M", align: "right", num: true, get: (s) => s.return3M,
    render: (s) => <span style={{ ...S.mono, color: retColor(s.return3M) }}>{signedPct(s.return3M, 1)}</span> },
  { key: "return1Y", label: "1Y", align: "right", num: true, get: (s) => s.return1Y,
    render: (s) => <span style={{ ...S.mono, color: retColor(s.return1Y) }}>{signedPct(s.return1Y, 0)}</span> },
];

interface Meta {
  date?: string; elapsed_seconds?: number; backend_version?: string; run_type?: string;
}

/* ──────────────────────────────────────────────────────────────────────────
   Component
   ────────────────────────────────────────────────────────────────────────── */
export default function Screener({ data, meta }: { data: Screen; meta?: Meta | null }) {
  const [sortKey, setSortKey] = useState<ColKey>("rank");
  const [sortAsc, setSortAsc] = useState(true);
  const [query, setQuery] = useState("");
  const [sector, setSector] = useState("All");
  const [hovered, setHovered] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const [showMethod, setShowMethod] = useState(false);

  const sectors = useMemo(
    () => ["All", ...Array.from(new Set(data.stocks.map((s) => s.sector))).sort()],
    [data.stocks]
  );

  const rows = useMemo(() => {
    let r = data.stocks;
    if (sector !== "All") r = r.filter((s) => s.sector === sector);
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      r = r.filter((s) => s.ticker.toLowerCase().includes(q) || s.name.toLowerCase().includes(q));
    }
    const col = COLS.find((c) => c.key === sortKey)!;
    const sorted = [...r].sort((a, b) => {
      const av = col.get(a), bv = col.get(b);
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") return sortAsc ? av - bv : bv - av;
      return sortAsc ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
    });
    return sorted;
  }, [data.stocks, sector, query, sortKey, sortAsc]);

  const activeTicker = pinned ?? hovered ?? data.stocks[0]?.ticker ?? null;
  const active = data.stocks.find((s) => s.ticker === activeTicker) ?? data.stocks[0];

  const onSort = (key: ColKey) => {
    if (key === sortKey) setSortAsc((v) => !v);
    else { setSortKey(key); setSortAsc(key === "rank"); }
  };

  const f = data.fund;
  const w = data.methodology.weights;

  return (
    <div style={S.root}>
      <style>{CSS}</style>

      {/* ════════ HEADER ════════ */}
      <header style={S.wrap}>
        <div style={S.topbar} className="rise">
          <span style={S.kicker}>QUANTITATIVE EQUITY SCREEN</span>
          <span style={S.method}>{f.benchmark} BENCHMARK · US LISTED</span>
        </div>
        <div style={S.rule} />
        <div style={S.mastRow} className="rise d1">
          <h1 style={S.h1}>US Equity Screener</h1>
          <div style={S.dateBlock}>
            <div style={S.dateLabel}>RANKS AS OF</div>
            <div style={S.dateVal}>{fmtDate(data.asOf)}</div>
            <div style={S.dateSub}>
              prices {fmtDate(data.pricesAsOf ?? data.asOf)}
              {meta?.backend_version ? ` · v${meta.backend_version}` : ""}
            </div>
          </div>
        </div>
        <p style={S.intro} className="rise d1">
          Every US-listed name with at least {data.minHistoryYears}+ years of price history is
          screened and scored on three pillars — <b style={{ color: "#cfc8b8" }}>financial health</b>{" "}
          ({pct(w.health, 0)}), <b style={{ color: "#cfc8b8" }}>valuation</b> ({pct(w.valuation, 0)}),
          and <b style={{ color: "#cfc8b8" }}>momentum</b> ({pct(w.momentum, 0)}). These are the top{" "}
          {data.stocks.length}, ranked by composite score. Hover any row for the reasoning.
        </p>
      </header>

      {/* ════════ DATA QUALITY STRIP ════════ */}
      <section style={{ ...S.wrap, marginTop: 26 }} className="rise d2">
        <div style={S.qualityGrid}>
          <Quality label="Universe scanned" value={data.universeSize.toLocaleString()} />
          <Quality label="Passed screen" value={data.screenedCount.toLocaleString()} sub={`${data.minHistoryYears}y history · liquidity`} />
          <Quality label="Scored" value={data.scoredCount.toLocaleString()} sub="usable fundamentals" />
          <Quality label="Ranked & shown" value={String(data.stocks.length)} accent />
        </div>
        <div style={S.exclRow}>
          <span style={S.exclLabel}>EXCLUDED {data.excludedCount.toLocaleString()}:</span>
          {Object.entries(data.exclusionReasons)
            .filter(([, n]) => n > 0)
            .map(([k, n]) => (
              <span key={k} style={S.exclChip}>{titleCase(k)} <b style={{ color: "#bcae8f" }}>{n.toLocaleString()}</b></span>
            ))}
          <button style={S.methodToggle} onClick={() => setShowMethod((v) => !v)}>
            <Info size={11} /> Methodology {showMethod ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
        </div>
        {showMethod && (
          <div style={S.methodPanel}>
            <MethodPillar
              title="Financial Health" weight={pct(w.health, 0)} color="#7bbf95"
              icon={<ShieldCheck size={13} />} factors={data.methodology.healthFactors}
              blurb="The strength and durability of the business itself — profitability, cash generation, growth, and balance-sheet safety. Each factor is percentile-ranked across the scored universe." />
            <MethodPillar
              title="Valuation" weight={pct(w.valuation, 0)} color="#e8b34e"
              icon={<TrendingUp size={13} />} factors={data.methodology.valuationFactors}
              blurb="Whether the current price is attractive for what you get. A negative P/E is treated as 'no earnings', not as cheap. PEG blends price against growth." />
            <MethodPillar
              title="Momentum" weight={pct(w.momentum, 0)} color="#7fa6a0"
              icon={<Activity size={13} />} factors={data.methodology.momentumFactors}
              blurb="Whether the market is already confirming the thesis. Kept deliberately small so the screen leans on fundamentals, not chasing price." />
          </div>
        )}
      </section>

      {/* ════════ TABLE + DETAIL ════════ */}
      <section style={{ ...S.wrap, marginTop: 22 }} className="rise d3">
        <div style={S.controls}>
          <div style={S.searchBox}>
            <Search size={13} color="#7a7566" />
            <input
              style={S.searchInput}
              placeholder="Search ticker or company…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <select style={S.select} value={sector} onChange={(e) => setSector(e.target.value)}>
            {sectors.map((s) => <option key={s} value={s}>{s === "All" ? "All sectors" : s}</option>)}
          </select>
          <span style={S.resultCount}>{rows.length} shown</span>
        </div>

        <div style={S.split}>
          {/* Table */}
          <div style={S.tableWrap}>
            <div style={S.tableScroll}>
              <table style={S.table}>
                <thead>
                  <tr>
                    {COLS.map((c) => (
                      <th
                        key={c.key}
                        className={c.hideNarrow ? "hide-narrow" : undefined}
                        style={{ ...S.th, textAlign: c.align, cursor: "pointer" }}
                        onClick={() => onSort(c.key)}
                      >
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 3,
                          justifyContent: c.align === "right" ? "flex-end" : "flex-start" }}>
                          {c.label}
                          {sortKey === c.key && (sortAsc ? <ChevronUp size={11} /> : <ChevronDown size={11} />)}
                        </span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((s) => {
                    const isActive = s.ticker === activeTicker;
                    const isTop10 = s.rank <= 10;
                    return (
                      <tr
                        key={s.ticker}
                        onMouseEnter={() => setHovered(s.ticker)}
                        onMouseLeave={() => setHovered(null)}
                        onClick={() => setPinned((p) => (p === s.ticker ? null : s.ticker))}
                        style={{
                          ...S.tr,
                          background: isActive
                            ? "rgba(232,179,78,.10)"
                            : isTop10 ? "rgba(232,179,78,.03)" : "transparent",
                          boxShadow: isActive ? "inset 2px 0 0 #e8b34e" : "none",
                        }}
                      >
                        {COLS.map((c) => (
                          <td
                            key={c.key}
                            className={c.hideNarrow ? "hide-narrow" : undefined}
                            style={{ ...S.td, textAlign: c.align }}
                          >
                            {c.render(s)}
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                  {rows.length === 0 && (
                    <tr><td colSpan={COLS.length} style={S.noRows}>No matches.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Detail panel (updates on hover, click to pin) */}
          <aside style={S.detailWrap}>
            {active && <DetailPanel s={active} pinned={pinned === active.ticker} />}
          </aside>
        </div>
      </section>

      {/* ════════ FUND SECTION ════════ */}
      <section style={{ ...S.wrap, marginTop: 30 }} className="rise d4">
        <PanelHead n="01" title={f.name} sub={`${f.constituents} holdings · ${f.weighting} · vs ${f.benchmark}`} />
        <div style={S.fundGrid}>
          {/* Metrics */}
          <div style={S.fundPanel}>
            <div style={S.blendedRow}>
              <Blended label="Blended P/E" value={num(f.blended.pe, 1)} />
              <Blended label="FCF Yield" value={pct(f.blended.fcfYield, 1)} />
              <Blended label="Rev Growth" value={pct(f.blended.revenueGrowth, 0)} />
              <Blended label="ROE" value={pct(f.blended.returnOnEquity, 0)} />
              <Blended label="Net Margin" value={pct(f.blended.netMargin, 0)} />
            </div>
            <div style={S.windowGrid}>
              <FundWindowCard title="Trailing 3-Year" w={f.metrics3Y} />
              <FundWindowCard title="Trailing 5-Year" w={f.metrics5Y} />
            </div>
          </div>

          {/* NAV chart */}
          <div style={S.fundPanel}>
            <div style={S.chartHead}>
              <span style={S.chartTitle}>Growth of $1 — fund vs {f.benchmark}</span>
              <span style={S.chartTag}>in-sample, current holdings</span>
            </div>
            <div style={{ width: "100%", height: 230 }}>
              <ResponsiveContainer>
                <LineChart data={f.navSeries} margin={{ top: 8, right: 10, bottom: 4, left: -8 }}>
                  <CartesianGrid stroke="#23272d" strokeDasharray="2 4" />
                  <XAxis dataKey="date" tick={{ fill: "#8b867a", fontSize: 10, fontFamily: "IBM Plex Mono" }}
                    tickLine={false} axisLine={{ stroke: "#2a2f36" }} minTickGap={60}
                    tickFormatter={(d) => String(d).slice(0, 7)} />
                  <YAxis tick={{ fill: "#8b867a", fontSize: 10, fontFamily: "IBM Plex Mono" }}
                    tickLine={false} axisLine={{ stroke: "#2a2f36" }} width={42}
                    tickFormatter={(v) => `$${Number(v).toFixed(1)}`} domain={["auto", "auto"]} />
                  <Tooltip content={<NavTip benchName={f.benchmark} />} />
                  <Line type="monotone" dataKey="benchmark" stroke="#6f8f7a" strokeWidth={1.4} dot={false} />
                  <Line type="monotone" dataKey="fund" stroke="#e8b34e" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div style={S.chartKey}>
              <span><i style={{ ...S.keyDot, background: "#e8b34e" }} />Fund</span>
              <span><i style={{ ...S.keyDot, background: "#6f8f7a" }} />{f.benchmark}</span>
            </div>
          </div>
        </div>

        {/* Sector breakdown */}
        <div style={{ ...S.fundPanel, marginTop: 16 }}>
          <span style={S.chartTitle}>Sector allocation</span>
          <div style={S.sectorBars}>
            {f.sectorBreakdown.map((sec) => (
              <div key={sec.sector} style={S.sectorBarRow}>
                <span style={S.sectorBarLabel}>{sec.sector}</span>
                <span style={S.sectorBarTrack}>
                  <span style={{ ...S.sectorBarFill, width: `${(sec.weight / f.sectorBreakdown[0].weight) * 100}%` }} />
                </span>
                <span style={S.sectorBarPct}>{pct(sec.weight, 1)}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ════════ FOOTER ════════ */}
      <footer style={{ ...S.wrap, ...S.footer }}>
        <p style={S.footerNote}>
          Scores are percentile ranks within the scored universe, combined {pct(w.health, 0)} financial
          health / {pct(w.valuation, 0)} valuation / {pct(w.momentum, 0)} momentum. Prices from Alpaca;
          fundamentals from SEC EDGAR (most recent annual filing). The fund&apos;s NAV and 3Y/5Y metrics
          apply today&apos;s holdings and score weights backward over the window — an <b>in-sample</b>{" "}
          characterisation of the current basket, not a live track record.
        </p>
        <p style={S.disc}>
          For research and educational use only. Not investment advice. Past performance does not
          predict future results.
        </p>
      </footer>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────────────
   Sub-components
   ────────────────────────────────────────────────────────────────────────── */
function DetailPanel({ s, pinned }: { s: StockPick; pinned: boolean }) {
  return (
    <div style={S.detail}>
      <div style={S.detailTop}>
        <div>
          <span style={S.detailTk}>{s.ticker}</span>
          <span style={S.detailRank}>#{s.rank}</span>
          {pinned && <span style={S.pinTag}>PINNED</span>}
        </div>
        <span style={S.detailPrice}>{s.price != null ? `$${s.price.toFixed(2)}` : "—"}</span>
      </div>
      <div style={S.detailName}>{s.name}</div>
      <div style={S.detailSector}>{s.sector}{s.subIndustry ? ` · ${s.subIndustry}` : ""} · {money(s.marketCap)}</div>

      {/* Score breakdown */}
      <div style={S.scoreBreakdown}>
        <ScoreBar label="Composite" value={s.score} bold />
        <ScoreBar label="Health" value={s.healthScore} />
        <ScoreBar label="Valuation" value={s.valuationScore} />
        <ScoreBar label="Momentum" value={s.momentumScore} />
      </div>

      {/* Reasons */}
      <div style={S.detailSectionLabel}>WHY IT RANKS</div>
      <ul style={S.reasonList}>
        {s.reasons.map((r, i) => (
          <li key={i} style={S.reasonItem}><span style={S.reasonTick}>+</span>{r}</li>
        ))}
      </ul>

      {/* Flags */}
      {s.flags.length > 0 && (
        <>
          <div style={S.detailSectionLabel}>WATCH</div>
          <ul style={S.reasonList}>
            {s.flags.map((flag, i) => (
              <li key={i} style={{ ...S.reasonItem, color: "#c9a07a" }}>
                <span style={{ ...S.reasonTick, color: "#c9886a" }}>!</span>{flag}
              </li>
            ))}
          </ul>
        </>
      )}

      {/* Fundamentals grid */}
      <div style={S.detailSectionLabel}>FUNDAMENTALS</div>
      <div style={S.fundGridMini}>
        <Mini label="P/E" value={num(s.peRatio, 1)} />
        <Mini label="ROE" value={pct(s.returnOnEquity, 0)} />
        <Mini label="Op Margin" value={pct(s.operatingMargin, 0)} />
        <Mini label="Net Margin" value={pct(s.netMargin, 0)} />
        <Mini label="FCF Margin" value={pct(s.fcfMargin, 0)} />
        <Mini label="FCF Yield" value={pct(s.fcfYield, 1)} />
        <Mini label="Rev Growth" value={signedPct(s.revenueGrowth, 0)} />
        <Mini label="Debt/Equity" value={num(s.debtToEquity, 2)} />
        <Mini label="Div Yield" value={pct(s.dividendYield, 2)} />
      </div>

      {/* Returns */}
      <div style={S.detailSectionLabel}>TRAILING RETURNS</div>
      <div style={S.returnRow}>
        {([["1W", s.return1W], ["1M", s.return1M], ["3M", s.return3M], ["6M", s.return6M], ["1Y", s.return1Y]] as const).map(
          ([k, v]) => (
            <div key={k} style={S.returnCell}>
              <div style={{ ...S.returnVal, color: retColor(v) }}>{signedPct(v, 0)}</div>
              <div style={S.returnLabel}>{k}</div>
            </div>
          )
        )}
      </div>

      <div style={S.fundWeightRow}>
        Weight in fund <b style={{ color: "#e8b34e" }}>{pct(s.fundWeight, 2)}</b>
      </div>
    </div>
  );
}

function ScoreBar({ label, value, bold }: { label: string; value: number; bold?: boolean }) {
  return (
    <div style={S.sbRow}>
      <span style={{ ...S.sbLabel, color: bold ? "#cfc8b8" : "#8a8576", fontWeight: bold ? 600 : 400 }}>{label}</span>
      <span style={S.sbTrack}>
        <span style={{ ...S.sbFill, width: `${value}%`, background: scoreColor(value), height: bold ? 6 : 4 }} />
      </span>
      <b style={{ ...S.sbNum, color: scoreColor(value) }}>{value.toFixed(1)}</b>
    </div>
  );
}

function FundWindowCard({ title, w }: { title: string; w: FundWindow | null }) {
  if (!w) {
    return (
      <div style={S.windowCard}>
        <div style={S.windowTitle}>{title}</div>
        <div style={S.windowEmpty}>Insufficient history</div>
      </div>
    );
  }
  return (
    <div style={S.windowCard}>
      <div style={S.windowTitle}>{title}</div>
      <div style={S.windowMetrics}>
        <WM label="Return" value={signedPct(w.annualReturn, 1)} color={retColor(w.annualReturn)} />
        <WM label="Volatility" value={pct(w.annualVolatility, 1)} />
        <WM label="Sharpe" value={num(w.sharpeRatio, 2)} color={w.sharpeRatio > 0.8 ? "#7bbf95" : "#ece6d8"} />
        <WM label="Max DD" value={pct(w.maximumDrawdown, 1)} color="#d98a72" />
        <WM label="Alpha" value={w.alpha != null ? signedPct(w.alpha, 1) : "—"} color={retColor(w.alpha)} />
        <WM label="Beta" value={num(w.beta, 2)} />
      </div>
    </div>
  );
}

function WM({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={S.wmCell}>
      <div style={{ ...S.wmVal, color: color ?? "#ece6d8" }}>{value}</div>
      <div style={S.wmLabel}>{label}</div>
    </div>
  );
}

function Quality({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div style={S.qualityCell}>
      <div style={{ ...S.qualityVal, color: accent ? "#e8b34e" : "#ece6d8" }}>{value}</div>
      <div style={S.qualityLabel}>{label}</div>
      {sub && <div style={S.qualitySub}>{sub}</div>}
    </div>
  );
}

function Blended({ label, value }: { label: string; value: string }) {
  return (
    <div style={S.blendedCell}>
      <div style={S.blendedVal}>{value}</div>
      <div style={S.blendedLabel}>{label}</div>
    </div>
  );
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div style={S.miniCell}>
      <div style={S.miniVal}>{value}</div>
      <div style={S.miniLabel}>{label}</div>
    </div>
  );
}

function MethodPillar({ title, weight, color, icon, factors, blurb }: {
  title: string; weight: string; color: string; icon: React.ReactNode; factors: string[]; blurb: string;
}) {
  return (
    <div style={S.pillar}>
      <div style={S.pillarHead}>
        <span style={{ color, display: "flex", alignItems: "center", gap: 6 }}>{icon}{title}</span>
        <span style={{ ...S.pillarWeight, color }}>{weight}</span>
      </div>
      <p style={S.pillarBlurb}>{blurb}</p>
      <div style={S.pillarFactors}>
        {factors.map((fac) => <span key={fac} style={S.factorChip}>{titleCase(fac)}</span>)}
      </div>
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

function NavTip({ active, payload, label, benchName }: any) {
  if (!active || !payload?.length) return null;
  const fund = payload.find((p: any) => p.dataKey === "fund")?.value;
  const bench = payload.find((p: any) => p.dataKey === "benchmark")?.value;
  return (
    <div style={S.tip}>
      <div style={{ color: "#7a7566", marginBottom: 4 }}>{label}</div>
      <div style={{ color: "#e8b34e" }}>Fund ${Number(fund).toFixed(2)}</div>
      <div style={{ color: "#8fa694" }}>{benchName} ${Number(bench).toFixed(2)}</div>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────────────
   Styles
   ────────────────────────────────────────────────────────────────────────── */
const S: Record<string, React.CSSProperties> = {
  root: {
    background: "#0b0d0f", minHeight: "100vh", paddingBottom: 64,
    fontFamily: "'IBM Plex Sans', sans-serif", color: "#ece6d8",
    backgroundImage:
      "radial-gradient(1200px 600px at 80% -10%,rgba(212,162,78,.07),transparent 60%)," +
      "radial-gradient(900px 500px at -10% 110%,rgba(127,166,160,.05),transparent 60%)",
  },
  wrap: { maxWidth: 1240, margin: "0 auto", padding: "0 28px" },

  topbar: { display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 34 },
  kicker: { fontSize: 11, letterSpacing: 3, color: "#8a8472", fontWeight: 600 },
  method: { fontSize: 10, letterSpacing: 1.5, color: "#7fa6a0" },
  rule: { height: 1, background: "linear-gradient(90deg,#2a2f36,transparent)", margin: "20px 0 26px" },
  mastRow: { display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 20 },
  h1: { fontFamily: "'Fraunces', serif", fontWeight: 500, fontSize: 52, lineHeight: 1.02, margin: 0, letterSpacing: -0.5, color: "#f4efe3" },
  dateBlock: { textAlign: "right" },
  dateLabel: { fontSize: 10, letterSpacing: 2.5, color: "#7a7566" },
  dateVal: { fontFamily: "'Fraunces', serif", fontSize: 22, color: "#e8b34e", margin: "2px 0" },
  dateSub: { fontSize: 11.5, color: "#8a8576", fontFamily: "IBM Plex Mono" },
  intro: { fontSize: 14.5, lineHeight: 1.75, color: "#b8b2a4", maxWidth: 880, marginTop: 22, marginBottom: 0 },

  qualityGrid: { display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 1, background: "#1c2025", border: "1px solid #1c2025", borderRadius: 4, overflow: "hidden" },
  qualityCell: { background: "#0e1113", padding: "20px 22px" },
  qualityVal: { fontFamily: "'IBM Plex Mono', monospace", fontWeight: 500, fontSize: 30, lineHeight: 1, letterSpacing: -1 },
  qualityLabel: { fontSize: 11, letterSpacing: 1.2, color: "#8a8576", marginTop: 12, textTransform: "uppercase" },
  qualitySub: { fontSize: 10.5, color: "#6f6a5f", marginTop: 4 },

  exclRow: { display: "flex", alignItems: "center", flexWrap: "wrap", gap: 10, marginTop: 14 },
  exclLabel: { fontSize: 10, letterSpacing: 1.3, color: "#6f6a5f" },
  exclChip: { fontSize: 11, color: "#8a8576", border: "1px solid #1d2127", borderRadius: 20, padding: "3px 10px", fontFamily: "IBM Plex Mono" },
  methodToggle: { marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, letterSpacing: 0.5, color: "#bcae8f", background: "rgba(188,174,143,.05)", border: "1px solid #2c3026", borderRadius: 20, padding: "5px 12px", cursor: "pointer", fontFamily: "IBM Plex Sans" },

  methodPanel: { display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 14, marginTop: 16 },
  pillar: { background: "#0e1113", border: "1px solid #1d2127", borderRadius: 4, padding: "16px 18px" },
  pillarHead: { display: "flex", justifyContent: "space-between", alignItems: "center", fontFamily: "'Fraunces',serif", fontSize: 16 },
  pillarWeight: { fontFamily: "IBM Plex Mono", fontSize: 15, fontWeight: 600 },
  pillarBlurb: { fontSize: 12, lineHeight: 1.6, color: "#8a8576", margin: "10px 0 12px" },
  pillarFactors: { display: "flex", flexWrap: "wrap", gap: 6 },
  factorChip: { fontSize: 10.5, color: "#a39a82", background: "#15181c", border: "1px solid #232830", borderRadius: 3, padding: "2px 7px", fontFamily: "IBM Plex Mono" },

  controls: { display: "flex", alignItems: "center", gap: 12, marginBottom: 14, flexWrap: "wrap" },
  searchBox: { display: "flex", alignItems: "center", gap: 8, background: "#0e1113", border: "1px solid #1d2127", borderRadius: 4, padding: "8px 12px", flex: 1, minWidth: 200, maxWidth: 360 },
  searchInput: { background: "transparent", border: "none", outline: "none", color: "#ece6d8", fontSize: 13, fontFamily: "IBM Plex Sans", width: "100%" },
  select: { background: "#0e1113", border: "1px solid #1d2127", borderRadius: 4, color: "#cfc8b8", fontSize: 12.5, padding: "8px 12px", fontFamily: "IBM Plex Sans", cursor: "pointer" },
  resultCount: { fontSize: 11.5, color: "#7a7566", fontFamily: "IBM Plex Mono", marginLeft: "auto" },

  split: { display: "grid", gridTemplateColumns: "1.55fr 1fr", gap: 18, alignItems: "start" },
  tableWrap: { background: "#0e1113", border: "1px solid #1d2127", borderRadius: 4, overflow: "hidden" },
  tableScroll: { maxHeight: 680, overflowY: "auto", overflowX: "auto" },
  table: { width: "100%", borderCollapse: "collapse", fontFamily: "IBM Plex Sans" },
  th: { position: "sticky", top: 0, zIndex: 2, background: "#11151a", fontSize: 10, letterSpacing: 1, color: "#7a7566", padding: "11px 12px", borderBottom: "1px solid #232830", whiteSpace: "nowrap", textTransform: "uppercase", userSelect: "none" },
  tr: { borderBottom: "1px solid #15181c", cursor: "pointer", transition: "background .12s ease" },
  td: { padding: "9px 12px", fontSize: 13, whiteSpace: "nowrap", verticalAlign: "middle" },
  noRows: { padding: 30, textAlign: "center", color: "#6f6a5f", fontSize: 13 },

  rankNum: { fontFamily: "IBM Plex Mono", fontSize: 12, color: "#6f6a5f" },
  coCell: { display: "flex", flexDirection: "column", gap: 1, minWidth: 0 },
  coTk: { fontFamily: "IBM Plex Mono", fontSize: 13, color: "#f0ead8", fontWeight: 600, letterSpacing: 0.3 },
  coName: { fontSize: 11, color: "#7a7566", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 200, whiteSpace: "nowrap" },
  sectorCell: { fontSize: 11.5, color: "#9a958a" },
  mono: { fontFamily: "IBM Plex Mono", fontSize: 12.5, color: "#cfc8b8" },

  scoreWrap: { display: "inline-flex", alignItems: "center", gap: 8, justifyContent: "flex-end", width: "100%" },
  scoreBarTrack: { width: 46, height: 4, background: "#1d2127", borderRadius: 3, overflow: "hidden", flexShrink: 0 },
  scoreBarFill: { display: "block", height: "100%", borderRadius: 3, transition: "width .2s ease" },
  scoreNum: { fontFamily: "IBM Plex Mono", fontSize: 12.5, minWidth: 34, textAlign: "right" },

  detailWrap: { position: "sticky", top: 16, alignSelf: "start" },
  detail: { background: "#0e1113", border: "1px solid #1d2127", borderRadius: 4, padding: "18px 20px", maxHeight: "calc(100vh - 32px)", overflowY: "auto" },
  detailTop: { display: "flex", justifyContent: "space-between", alignItems: "baseline" },
  detailTk: { fontFamily: "IBM Plex Mono", fontSize: 22, color: "#f4efe3", fontWeight: 600, letterSpacing: 0.5 },
  detailRank: { fontFamily: "IBM Plex Mono", fontSize: 12, color: "#7a7566", marginLeft: 10 },
  pinTag: { fontSize: 9, letterSpacing: 1, color: "#e8b34e", border: "1px solid #3a2e10", borderRadius: 3, padding: "2px 6px", marginLeft: 8 },
  detailPrice: { fontFamily: "IBM Plex Mono", fontSize: 16, color: "#e8b34e" },
  detailName: { fontFamily: "'Fraunces',serif", fontSize: 16, color: "#e6dfce", marginTop: 6 },
  detailSector: { fontSize: 11.5, color: "#7a7566", marginTop: 3, fontFamily: "IBM Plex Mono" },

  scoreBreakdown: { display: "flex", flexDirection: "column", gap: 7, margin: "16px 0", padding: "14px 0", borderTop: "1px solid #1d2127", borderBottom: "1px solid #1d2127" },
  sbRow: { display: "flex", alignItems: "center", gap: 10 },
  sbLabel: { fontSize: 11.5, width: 76, flexShrink: 0 },
  sbTrack: { flex: 1, height: 4, background: "#1d2127", borderRadius: 3, overflow: "hidden", display: "flex", alignItems: "center" },
  sbFill: { display: "block", borderRadius: 3, transition: "width .25s ease" },
  sbNum: { fontFamily: "IBM Plex Mono", fontSize: 12, width: 38, textAlign: "right" },

  detailSectionLabel: { fontSize: 9.5, letterSpacing: 1.5, color: "#6f6a5f", marginTop: 14, marginBottom: 8, textTransform: "uppercase" },
  reasonList: { listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 },
  reasonItem: { fontSize: 12.5, lineHeight: 1.5, color: "#b8b2a4", display: "flex", gap: 8, alignItems: "flex-start" },
  reasonTick: { color: "#7bbf95", fontFamily: "IBM Plex Mono", fontWeight: 700, flexShrink: 0 },

  fundGridMini: { display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 1, background: "#1d2127", borderRadius: 4, overflow: "hidden" },
  miniCell: { background: "#0c0f11", padding: "11px 12px" },
  miniVal: { fontFamily: "IBM Plex Mono", fontSize: 15, color: "#ece6d8", lineHeight: 1 },
  miniLabel: { fontSize: 9.5, letterSpacing: 0.5, color: "#7a7566", marginTop: 5, textTransform: "uppercase" },

  returnRow: { display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 1, background: "#1d2127", borderRadius: 4, overflow: "hidden" },
  returnCell: { background: "#0c0f11", padding: "10px 6px", textAlign: "center" },
  returnVal: { fontFamily: "IBM Plex Mono", fontSize: 13, lineHeight: 1 },
  returnLabel: { fontSize: 9.5, color: "#7a7566", marginTop: 5 },
  fundWeightRow: { marginTop: 14, fontSize: 12, fontFamily: "IBM Plex Mono", color: "#7a7566", textAlign: "right" },

  panelHead: { display: "flex", gap: 14, alignItems: "baseline", marginBottom: 18 },
  panelNo: { fontFamily: "IBM Plex Mono", fontSize: 11, color: "#5e5a4e", borderRight: "1px solid #2a2f36", paddingRight: 14 },
  panelTitle: { fontFamily: "'Fraunces', serif", fontSize: 22, color: "#f0ead8" },
  panelSub: { fontSize: 11.5, color: "#7a7566", letterSpacing: 0.5, marginTop: 2, fontFamily: "IBM Plex Mono" },

  fundGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 },
  fundPanel: { background: "#0e1113", border: "1px solid #1d2127", borderRadius: 4, padding: 20 },
  blendedRow: { display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 1, background: "#1d2127", borderRadius: 4, overflow: "hidden", marginBottom: 14 },
  blendedCell: { background: "#0c0f11", padding: "13px 10px" },
  blendedVal: { fontFamily: "IBM Plex Mono", fontSize: 17, color: "#ece6d8", lineHeight: 1 },
  blendedLabel: { fontSize: 9.5, letterSpacing: 0.5, color: "#7a7566", marginTop: 6, textTransform: "uppercase" },

  windowGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 },
  windowCard: { border: "1px solid #1d2127", borderRadius: 4, padding: "12px 14px" },
  windowTitle: { fontSize: 11, letterSpacing: 1, color: "#bcae8f", marginBottom: 10, textTransform: "uppercase" },
  windowEmpty: { fontSize: 12, color: "#6f6a5f", padding: "12px 0" },
  windowMetrics: { display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "12px 8px" },
  wmCell: {},
  wmVal: { fontFamily: "IBM Plex Mono", fontSize: 15, lineHeight: 1 },
  wmLabel: { fontSize: 9.5, color: "#7a7566", marginTop: 4, textTransform: "uppercase", letterSpacing: 0.5 },

  chartHead: { display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 },
  chartTitle: { fontFamily: "'Fraunces',serif", fontSize: 14, color: "#e6dfce" },
  chartTag: { fontSize: 10, color: "#6f6a5f", letterSpacing: 0.5, fontFamily: "IBM Plex Mono" },
  chartKey: { display: "flex", gap: 20, fontSize: 11, color: "#8a8576", marginTop: 6, fontFamily: "IBM Plex Mono" },
  keyDot: { display: "inline-block", width: 8, height: 8, borderRadius: 8, marginRight: 6, verticalAlign: "middle" },

  sectorBars: { display: "flex", flexDirection: "column", gap: 8, marginTop: 14 },
  sectorBarRow: { display: "grid", gridTemplateColumns: "180px 1fr 56px", alignItems: "center", gap: 12 },
  sectorBarLabel: { fontSize: 12, color: "#9a958a" },
  sectorBarTrack: { height: 6, background: "#15181c", borderRadius: 3, overflow: "hidden" },
  sectorBarFill: { display: "block", height: "100%", borderRadius: 3, background: "linear-gradient(90deg,#9c7b4a,#e8b34e)" },
  sectorBarPct: { fontFamily: "IBM Plex Mono", fontSize: 12, color: "#cfc8b8", textAlign: "right" },

  footer: { marginTop: 36, paddingTop: 22, borderTop: "1px solid #1d2127" },
  footerNote: { fontSize: 12.5, lineHeight: 1.7, color: "#8a8576", maxWidth: 900, margin: 0 },
  disc: { fontSize: 11, color: "#5e5a4e", marginTop: 12, letterSpacing: 0.3, fontFamily: "IBM Plex Mono" },

  tip: { background: "#15181c", border: "1px solid #2a2f36", borderRadius: 4, padding: "8px 11px", fontFamily: "IBM Plex Mono", fontSize: 12, color: "#ece6d8" },
};

const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
* { box-sizing: border-box; }
body { margin: 0; background: #0b0d0f; }
::selection { background: #e8b34e; color: #0b0d0f; }
.rise { opacity:0; transform:translateY(14px); animation:rise .7s cubic-bezier(.2,.7,.2,1) forwards; }
.d1{animation-delay:.06s} .d2{animation-delay:.12s} .d3{animation-delay:.18s} .d4{animation-delay:.24s}
@keyframes rise { to { opacity:1; transform:none; } }
.recharts-surface { overflow:visible; }
/* slim scrollbar for the table */
*::-webkit-scrollbar { width: 9px; height: 9px; }
*::-webkit-scrollbar-track { background: #0c0f11; }
*::-webkit-scrollbar-thumb { background: #232830; border-radius: 6px; }
*::-webkit-scrollbar-thumb:hover { background: #2e353e; }
@media (max-width: 1000px) {
  [style*="grid-template-columns: 1.55fr 1fr"] { grid-template-columns: 1fr !important; }
  [style*="grid-template-columns: 1fr 1fr"][style*="gap: 16px"] { grid-template-columns: 1fr !important; }
  [style*="position: sticky"][style*="top: 16"] { position: static !important; }
}
@media (max-width: 760px) {
  .rise h1 { font-size: 34px !important; }
  [style*="repeat(4,1fr)"] { grid-template-columns: 1fr 1fr !important; }
  [style*="repeat(3,1fr)"] { grid-template-columns: 1fr 1fr !important; }
  [style*="repeat(5,1fr)"] { grid-template-columns: 1fr 1fr 1fr !important; }
  .hide-narrow { display: none !important; }
}
`;

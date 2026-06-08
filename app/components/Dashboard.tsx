"use client";

import React, { useState } from "react";
import {
  ScatterChart, Scatter, XAxis, YAxis, ZAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell,
} from "recharts";
import { TrendingUp, TrendingDown, Activity, ShieldAlert, BarChart2, Info } from "lucide-react";
import type { Portfolio } from "../../lib/types";

/* ── Palette ── warm gold-anchored, asset-class coded */
const ASSET_COLORS: Record<string, string> = {
  Equity:         "#d4a24e",
  "Fixed Income": "#7fa6a0",
  Commodity:      "#c8852f",
  "Real Estate":  "#9c7b4a",
  Cash:           "#8a8576",
};
const FALLBACK_COLORS = ["#b9742f","#caa66a","#5f8b91","#6f8f7a","#a98a55","#83785a"];
const colorFor = (assetClass: string, i: number) =>
  ASSET_COLORS[assetClass] ?? FALLBACK_COLORS[i % FALLBACK_COLORS.length];

/* ── ETF detail lookup ──────────────────────────────────────────────────── */
interface EtfDetail {
  fullName: string;
  tracks: string;
  why: string;
  expenseRatio: string;
  geography: string;
}
const ETF_INFO: Record<string, EtfDetail> = {
  IVV: {
    fullName: "iShares Core S&P 500 ETF",
    tracks: "S&P 500 — the 500 largest US companies by market capitalisation",
    why: "Core US equity exposure. Represents ~30% of global equity market cap. Top positions: Apple, Microsoft, NVIDIA, Amazon, Alphabet.",
    expenseRatio: "0.03%",
    geography: "United States",
  },
  VEA: {
    fullName: "Vanguard Developed Markets ETF",
    tracks: "FTSE Developed All Cap ex US — large, mid, and small-cap stocks in Europe, Japan, Australia, Canada",
    why: "Diversifies equity risk outside the US. Captures different economic cycles, interest-rate regimes, and currency movements. Japan ~25%, UK ~15%, France ~8%.",
    expenseRatio: "0.05%",
    geography: "Europe · Japan · Australia · Canada",
  },
  VWO: {
    fullName: "Vanguard Emerging Markets Stock Index ETF",
    tracks: "FTSE Emerging Markets All Cap China A Inclusion Index",
    why: "Exposure to faster-growing developing economies. Historically higher long-run return potential in exchange for higher short-run volatility and currency risk.",
    expenseRatio: "0.08%",
    geography: "China · India · Brazil · Taiwan · South Africa",
  },
  AGG: {
    fullName: "iShares Core US Aggregate Bond ETF",
    tracks: "Bloomberg US Aggregate Bond Index — investment-grade US bonds",
    why: "The portfolio's ballast. Holds US Treasuries, investment-grade corporate bonds, and mortgage-backed securities. Provides income and tends to rise when equities fall — the diversification engine of risk parity.",
    expenseRatio: "0.03%",
    geography: "United States",
  },
  GLD: {
    fullName: "SPDR Gold Shares",
    tracks: "Physical gold bullion — each share represents ~0.0926 troy oz held in London vaults",
    why: "Hard-asset diversifier with low correlation to both equities and bonds. Tends to rally during inflation shocks, currency crises, and geopolitical stress — exactly when other assets often fall together.",
    expenseRatio: "0.40%",
    geography: "Global store of value",
  },
  VNQ: {
    fullName: "Vanguard Real Estate ETF",
    tracks: "MSCI US Investable Market Real Estate 25/50 Index — US REITs",
    why: "Real-asset exposure with a meaningful income component. REITs own physical property — data centres, warehouses, apartments, offices — and must distribute 90% of taxable income as dividends.",
    expenseRatio: "0.13%",
    geography: "United States",
  },
  BIL: {
    fullName: "SPDR Bloomberg 1-3 Month T-Bill ETF",
    tracks: "Bloomberg 1-3 Month US Treasury Bill Index — effectively cash",
    why: "Near-zero-risk cash sleeve sized from the market regime. In a neutral market the portfolio holds 5% here as a buffer. Earns the current short-term risk-free rate with virtually no duration or credit risk.",
    expenseRatio: "0.14%",
    geography: "United States",
  },
};

const pct  = (x: number | null | undefined, d = 1) =>
  x == null ? "—" : `${(x * 100).toFixed(d)}`+ "%";
const num  = (x: number | null | undefined, d = 2) =>
  x == null ? "—" : x.toFixed(d);
const fmtMethod = (s: string) =>
  s === "risk_parity" ? "Risk Parity" : s === "min_variance" ? "Min Variance" : s;
const fmtDate = (s: string) => {
  try {
    return new Date(s + "T00:00:00").toLocaleDateString("en-US", {
      year: "numeric", month: "long", day: "numeric",
    });
  } catch { return s; }
};

/* ── Types ── */
interface Meta {
  date?: string;
  elapsed_seconds?: number;
  backend_version?: string;
}

export default function Dashboard({
  data, meta,
}: {
  data: Portfolio;
  meta?: Meta | null;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const m = data.metrics;
  const alloc = data.assetAllocation;

  /* frontier */
  const frontierRaw = data.efficientFrontier.map((p) => ({
    x: +(p.volatility * 100).toFixed(3),
    y: +(p.return * 100).toFixed(3),
    s: p.sharpeRatio,
  }));
  const seen = new Set<string>();
  const frontier = frontierRaw.filter((p) => {
    const k = `${p.x},${p.y}`;
    return seen.has(k) ? false : (seen.add(k), true);
  });
  // Where THIS portfolio (risk parity) actually sits — emitted by the backend
  // in the same return/cov model as the frontier curve, so the marker is honest.
  const portfolioPt = data.portfolioPoint
    ? {
        x: +(data.portfolioPoint.volatility * 100).toFixed(3),
        y: +(data.portfolioPoint.return * 100).toFixed(3),
      }
    : null;
  const xs = [...frontier.map((p) => p.x), ...(portfolioPt ? [portfolioPt.x] : [])];
  const ys = [...frontier.map((p) => p.y), ...(portfolioPt ? [portfolioPt.y] : [])];
  const xDomain: [number, number] = [Math.floor(Math.min(...xs) - 0.5), Math.ceil(Math.max(...xs) + 0.5)];
  const yDomain: [number, number] = [Math.floor(Math.min(...ys) - 1),  Math.ceil(Math.max(...ys) + 1)];

  /* market */
  const mc  = data.marketConditions;
  const sum = mc?.marketSummary ?? {};

  /* benchmark bar data */
  const benchRows: { name: string; ret: number; vol: number; sharpe: number; mdd: number }[] = [];
  benchRows.push({
    name: "Portfolio",
    ret: +(m.annualReturn * 100).toFixed(2),
    vol: +(m.annualVolatility * 100).toFixed(2),
    sharpe: +m.sharpeRatio.toFixed(2),
    mdd: +(Math.abs(m.maximumDrawdown) * 100).toFixed(2),
  });
  if (data.benchmark) {
    benchRows.push({
      name: data.benchmark.name,
      ret: +(data.benchmark.annualReturn * 100).toFixed(2),
      vol: +(data.benchmark.annualVolatility * 100).toFixed(2),
      sharpe: +data.benchmark.sharpeRatio.toFixed(2),
      mdd: +(Math.abs(data.benchmark.maximumDrawdown) * 100).toFixed(2),
    });
  }
  if (data.equityContext) {
    benchRows.push({
      name: "S&P 500",
      ret: +(data.equityContext.annualReturn * 100).toFixed(2),
      vol: +(data.equityContext.annualVolatility * 100).toFixed(2),
      sharpe: +data.equityContext.sharpeRatio.toFixed(2),
      mdd: +(Math.abs(data.equityContext.maximumDrawdown) * 100).toFixed(2),
    });
  }

  return (
    <div style={S.root}>
      <style>{CSS}</style>

      {/* ═══════════ MASTHEAD ═══════════ */}
      <header style={S.wrap} className="rise">
        <div style={S.topbar}>
          <span style={S.kicker}>THE PYTHON PORTFOLIO PROJECT</span>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span style={S.methodBadge}>{fmtMethod(data.allocationMethod)}</span>
            <span style={S.regimeWrap}>
              <span style={S.regimeDot} />
              {(data.marketRegime ?? "neutral").toUpperCase()} REGIME
            </span>
          </div>
        </div>
        <div style={S.rule} />
        <div style={S.mastRow}>
          <h1 style={S.h1}>
            Multi-Asset<br />Risk Parity Portfolio
          </h1>
          <div style={S.dateBlock}>
            <div style={S.dateLabel}>OPTIMIZED</div>
            <div style={S.dateVal}>{fmtDate(data.date)}</div>
            <div style={S.dateSub}>
              {data.allocationMethod === "risk_parity" ? "Equal risk contribution · " : "Min variance · "}
              {alloc.length} assets · {(data.cashWeight * 100).toFixed(0)}% cash
            </div>
            {meta?.elapsed_seconds && (
              <div style={{ ...S.dateSub, marginTop: 4, color: "#5e5a4e" }}>
                Generated in {meta.elapsed_seconds}s
                {meta.backend_version ? ` · v${meta.backend_version}` : ""}
              </div>
            )}
          </div>
        </div>
      </header>

      <div style={S.wrap} className="rise d1">
        <p style={S.intro}>
          A quantitative algorithm allocates across six asset classes — equities, international,
          emerging markets, bonds, gold, and real estate — using risk parity: each asset
          contributes an <em>equal share of portfolio risk</em>, regardless of its weight.
          A cash sleeve is sized automatically from the market regime.
        </p>
      </div>

      {/* ═══════════ HEADLINE STATS ═══════════ */}
      <section style={{ ...S.wrap, ...S.statGrid }} className="rise d1">
        <Stat label="Annualised Return"   value={pct(m.annualReturn)}   tone="up" />
        <Stat label="Sharpe Ratio"        value={num(m.sharpeRatio)}    big />
        <Stat label="Annualised Volatility" value={pct(m.annualVolatility)} />
        <Stat label="Max Drawdown"        value={pct(m.maximumDrawdown)} tone="down" />
      </section>
      <div style={S.wrap} className="rise d1">
        <p style={S.headlineNote}>
          <b style={{ color: "#a39a82" }}>Trailing 3-year, in-sample</b> figures — they describe
          the historical window the weights were fit on. Forward-looking forecasts are not used;
          the risk-parity method requires no return forecast. Covariance is estimated with EWMA
          (63-day halflife) so recent correlation regimes are weighted more than historical shocks.
        </p>
      </div>

      {/* ═══════════ CHARTS — Allocation + Frontier ═══════════ */}
      <section style={{ ...S.wrap, ...S.chartGrid }} className="rise d2">

        {/* Allocation donut */}
        <div style={S.panel}>
          <PanelHead n="01" title="Asset Allocation" sub="portfolio weights" />
          <div style={{ display: "flex", gap: 18, alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ position: "relative", width: 230, height: 230 }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={alloc} dataKey="weight" nameKey="key"
                    innerRadius={68} outerRadius={104} paddingAngle={1.5}
                    stroke="none" startAngle={90} endAngle={-270}
                  >
                    {alloc.map((a, i) => (
                      <Cell
                        key={a.key}
                        fill={colorFor(a.assetClass, i)}
                        opacity={hover === null || hover === i ? 1 : 0.25}
                        style={{ transition: "opacity .2s", cursor: "default" }}
                      />
                    ))}
                  </Pie>
                  <Tooltip content={<DonutTip />} />
                </PieChart>
              </ResponsiveContainer>
              <div style={S.donutCenter}>
                <div style={S.donutTop}>
                  {hover !== null ? alloc[hover].key : "TOTAL"}
                </div>
                <div style={S.donutPct}>
                  {hover !== null ? pct(alloc[hover].weight) : pct(1 - data.cashWeight)}
                </div>
                <div style={S.donutSub}>
                  {hover !== null ? alloc[hover].assetClass : "risky assets"}
                </div>
              </div>
            </div>

            <div style={S.legend}>
              {alloc.map((a, i) => (
                <div key={a.key} style={{
                  ...S.legRow,
                  background: hover === i ? "rgba(232,179,78,.06)" : "transparent",
                  borderRadius: 4,
                  padding: "3px 6px",
                }}
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover(null)}
                >
                  <span style={{ ...S.legDot, background: colorFor(a.assetClass, i) }} />
                  <span style={S.legTk}>{a.key}</span>
                  <span style={S.legPct}>{pct(a.weight)}</span>
                </div>
              ))}
            </div>
          </div>
          {/* ETF info card — appears when hovering any item */}
          {hover !== null && ETF_INFO[alloc[hover].key] && (
            <EtfCard
              etf={alloc[hover]}
              info={ETF_INFO[alloc[hover].key]}
              color={colorFor(alloc[hover].assetClass, hover)}
            />
          )}
        </div>

        {/* Efficient frontier */}
        <div style={S.panel}>
          <PanelHead n="02" title="Efficient Frontier" sub="risk / return locus" />
          <div style={{ width: "100%", height: 268 }}>
            <ResponsiveContainer>
              <ScatterChart margin={{ top: 12, right: 16, bottom: 28, left: 4 }}>
                <CartesianGrid stroke="#23272d" strokeDasharray="2 4" />
                <XAxis type="number" dataKey="x" domain={xDomain}
                  tick={{ fill: "#8b867a", fontSize: 11, fontFamily: "IBM Plex Mono" }}
                  tickLine={false} axisLine={{ stroke: "#2a2f36" }}
                  label={{ value: "VOLATILITY  (%)", position: "bottom", offset: 8,
                    fill: "#6f6a5f", fontSize: 10, letterSpacing: 1.5, fontFamily: "IBM Plex Sans" }} />
                <YAxis type="number" dataKey="y" domain={yDomain}
                  tick={{ fill: "#8b867a", fontSize: 11, fontFamily: "IBM Plex Mono" }}
                  tickLine={false} axisLine={{ stroke: "#2a2f36" }}
                  label={{ value: "RETURN (%)", angle: -90, position: "insideLeft",
                    fill: "#6f6a5f", fontSize: 10, letterSpacing: 1.5, dy: 40, fontFamily: "IBM Plex Sans" }} />
                <ZAxis range={[42, 42]} />
                <Tooltip content={<FrontierTip />} cursor={{ stroke: "#3a3f46" }} />
                <Scatter data={frontier} fill="#7fa6a0" fillOpacity={0.55} />
                {portfolioPt && <Scatter data={[portfolioPt]} fill="#e8b34e" />}
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <div style={S.frontierKey}>
            <span><i style={{ ...S.keyDot, background: "#7fa6a0" }} />feasible frontier</span>
            <span><i style={{ ...S.keyDot, background: "#e8b34e" }} />this portfolio (risk parity)</span>
          </div>
        </div>
      </section>

      {/* ═══════════ ALLOCATION TABLE with risk contributions ═══════════ */}
      <section style={S.wrap} className="rise d3">
        <div style={S.panel}>
          <PanelHead n="03" title="Allocation Detail" sub="weights & risk contributions" icon={<BarChart2 size={13} />} />
          <div style={S.tHead}>
            <span>ASSET</span>
            <span>CLASS</span>
            <span style={{ textAlign: "right" }}>WEIGHT</span>
            <span style={{ textAlign: "right" }}>RISK CONTRIBUTION</span>
          </div>
          {alloc.map((a, i) => {
            const maxW = Math.max(...alloc.map((x) => x.weight));
            return (
              <div key={a.key} style={S.tRow}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
              >
                {/* Asset name */}
                <span style={S.coCell}>
                  <i style={{ ...S.legDot, background: colorFor(a.assetClass, i) }} />
                  <span>
                    <span style={S.coName}>{a.name}</span>
                    <span style={S.coTk}>{a.key}</span>
                  </span>
                </span>
                {/* Asset class */}
                <span style={S.secCell}>{a.assetClass}</span>
                {/* Weight bar */}
                <span style={S.wCell}>
                  <span style={S.barTrack}>
                    <span style={{
                      ...S.barFill,
                      width: `${(a.weight / maxW) * 92}%`,
                      background: `linear-gradient(90deg, ${colorFor(a.assetClass, i)}88, ${colorFor(a.assetClass, i)})`,
                    }} />
                  </span>
                  <b style={S.wNum}>{pct(a.weight)}</b>
                </span>
                {/* Risk contribution bar */}
                <span style={S.wCell}>
                  <span style={S.barTrack}>
                    <span style={{
                      ...S.barFill,
                      width: `${(a.riskContribution) * 92}%`,
                      background: "linear-gradient(90deg,#3a5a5688,#7fa6a0)",
                    }} />
                  </span>
                  <b style={S.wNum}>{pct(a.riskContribution)}</b>
                </span>
              </div>
            );
          })}
          <div style={{ fontSize: 11, color: "#5e5a4e", marginTop: 14, fontFamily: "IBM Plex Mono" }}>
            Risk parity target: each asset contributes {pct(1 / alloc.filter(a => a.assetClass !== "Cash").length)} of total portfolio risk
          </div>
        </div>
      </section>

      {/* ═══════════ BENCHMARK COMPARISON ═══════════ */}
      {benchRows.length > 1 && (
        <section style={S.wrap} className="rise d3">
          <div style={S.panel}>
            <PanelHead n="04" title="Benchmark Comparison" sub="portfolio vs 60/40 vs S&P 500" />
            <div style={{ overflowX: "auto" }}>
              <table style={S.compTable}>
                <thead>
                  <tr>
                    <th style={S.thLeft}>STRATEGY</th>
                    <th style={S.th}>ANN. RETURN</th>
                    <th style={S.th}>VOLATILITY</th>
                    <th style={S.th}>SHARPE</th>
                    <th style={S.th}>MAX DRAWDOWN</th>
                  </tr>
                </thead>
                <tbody>
                  {benchRows.map((row, i) => (
                    <tr key={row.name} style={{ background: i === 0 ? "rgba(232,179,78,.04)" : "transparent" }}>
                      <td style={{ ...S.tdLeft, color: i === 0 ? "#e8b34e" : "#9a958a" }}>
                        {row.name}
                        {i === 0 && <span style={S.portfolioBadge}>THIS PORTFOLIO</span>}
                      </td>
                      <td style={{ ...S.td, color: row.ret >= 0 ? "#7bbf95" : "#d98a72" }}>
                        {row.ret >= 0 ? "+" : ""}{row.ret.toFixed(1)}%
                      </td>
                      <td style={S.td}>{row.vol.toFixed(1)}%</td>
                      <td style={{ ...S.td, color: row.sharpe > 0.8 ? "#7bbf95" : row.sharpe > 0.4 ? "#ece6d8" : "#d98a72" }}>
                        {row.sharpe.toFixed(2)}
                      </td>
                      <td style={{ ...S.td, color: "#d98a72" }}>−{row.mdd.toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}

      {/* ═══════════ RISK + MARKET ═══════════ */}
      <section style={{ ...S.wrap, ...S.dualGrid }} className="rise d4">
        {/* Risk profile */}
        <div style={S.panel}>
          <PanelHead n={benchRows.length > 1 ? "05" : "04"} title="Risk Profile" sub="downside & tail" icon={<ShieldAlert size={13} />} />
          <div style={S.miniGrid}>
            <Mini label="Sortino"        value={num(m.sortinoRatio)} />
            <Mini label="Calmar"         value={num(m.calmarRatio)} />
            <Mini label="VaR · 95%"      value={pct(m.valueAtRisk95, 2)} />
            <Mini label="CVaR · 95%"     value={pct(m.conditionalVar95, 2)} />
          </div>
          {/* Professional metrics row */}
          <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 1, background: "#1d2127", borderRadius: 4, overflow: "hidden" }}>
            <ProMini label="Win Rate"     value={m.winRate != null ? pct(m.winRate, 1) : "—"} tip="% of trading days with positive return" />
            <ProMini label="Skewness"     value={m.skewness != null ? num(m.skewness) : "—"} tip="Negative = left tail risk (crash bias)" />
            <ProMini label="Kurtosis"     value={m.kurtosis != null ? num(m.kurtosis) : "—"} tip="Excess kurtosis — fat tails vs normal" />
          </div>
          {(m.maxDrawdownDuration != null || m.trackingError != null || m.informationRatio != null) && (
            <div style={{ marginTop: 1, display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 1, background: "#1d2127", overflow: "hidden", borderRadius: "0 0 4px 4px" }}>
              <ProMini label="MDD Duration" value={m.maxDrawdownDuration != null ? `${m.maxDrawdownDuration}d` : "—"} tip="Longest consecutive days below peak" />
              <ProMini label="Tracking Err" value={m.trackingError != null ? pct(m.trackingError, 1) : "—"} tip="Annualised std dev of excess returns vs benchmark" />
              <ProMini label="Info Ratio"   value={m.informationRatio != null ? num(m.informationRatio) : "—"} tip="Active return / tracking error. >0.5 = strong" />
            </div>
          )}
        </div>

        {/* Market tape */}
        <div style={S.panel}>
          <PanelHead n={benchRows.length > 1 ? "06" : "05"} title="Market Tape" sub="trailing week" icon={<Activity size={13} />} />
          <div style={S.tape}>
            <Tape label="VIX"      value={mc?.vix != null ? num(mc.vix) : "—"} tag={mc?.volatilityLevel} />
            <Tape label="Regime"   value={(mc?.riskSentiment ?? "—").toUpperCase()} />
            <Tape label="S&P 500"  value={pct(mc?.sp500Return)}    tone />
            <Tape label="Nasdaq"   value={pct(mc?.nasdaqReturn)}   tone />
            <Tape label="Russell 2K" value={pct(sum["Russell 2000"]?.weeklyReturn)} tone />
            <Tape label="10Y UST"  value={mc?.treasuryYield != null ? `${num(mc.treasuryYield)}%` : "—"} />
            <Tape label="Gold"     value={pct(sum["Gold"]?.weeklyReturn)} tone />
          </div>
        </div>
      </section>

      {/* ═══════════ PLAIN ENGLISH ═══════════ */}
      <section style={S.wrap} className="rise d5">
        <div style={S.panel}>
          <PanelHead n={benchRows.length > 1 ? "07" : "06"} title="Plain English" sub="what the numbers mean" />
          <div style={S.glossary}>
            <Term term="Risk parity"
              def="Instead of allocating by dollar weight, each asset contributes an equal share of total portfolio risk. Bonds get more dollars because they're less volatile — the risk is balanced, not the money." />
            <Term term="Sharpe ratio"
              def="Return earned per unit of risk. Above 1 is good, above 1.5 is strong. Read it as a description of the past — not a promise about the future." />
            <Term term="Volatility"
              def="How much the portfolio swings up and down. Lower means a steadier ride. Risk parity tends to produce lower volatility than an equity-heavy approach." />
            <Term term="Max drawdown"
              def="The worst peak-to-trough drop over the period — how much you'd have been down at the lowest point." />
            <Term term="Sortino ratio"
              def="Like Sharpe, but only penalises downside moves. A portfolio that jumps up a lot isn't punished — only the downward volatility counts." />
            <Term term="VaR & CVaR (95%)"
              def="On the worst day in roughly 20, you'd expect to lose about the VaR. CVaR is the average loss across those worst days — a more conservative gauge." />
            <Term term="Skewness"
              def="Negative skewness means the portfolio has a larger-than-normal chance of a big drop. Positive is better. Most equity portfolios are negatively skewed." />
            <Term term="Kurtosis"
              def="How fat the tails are vs a normal distribution. High kurtosis means extreme days happen more often than statistics would suggest." />
            <Term term="Win rate"
              def="The percentage of trading days with a positive return. 52%+ is typical for well-diversified portfolios." />
            <Term term="Max drawdown duration"
              def="How many consecutive days the portfolio spent below its prior peak. Shorter means faster recovery from market stress." />
            <Term term="Information ratio"
              def="How much excess return is generated per unit of active risk vs the benchmark. Above 0.5 is considered strong; above 1.0 is exceptional." />
            <Term term="Efficient frontier"
              def="The curve of best-possible portfolios — the most return for each level of risk. The gold dot is the risk-parity-selected portfolio." />
          </div>
        </div>
      </section>

      {/* ═══════════ FOOTER ═══════════ */}
      <footer style={{ ...S.wrap, ...S.footer }} className="rise d5">
        <p style={S.method}>
          <b style={{ color: "#bcae8f" }}>Methodology.</b> Six asset-class ETFs (IVV, VEA, VWO,
          AGG, GLD, VNQ) allocated via risk parity (Maillard–Roncalli–Teiletche log-barrier).
          Covariance estimated with an EWMA estimator (63-day half-life) so recent correlation
          regimes outweigh historical shocks. Market regime detected from VIX level; the cash
          sleeve is sized from the regime. All figures are <i>in-sample trailing 3-year</i> —
          descriptive of the historical window, not a forecast of future returns.
        </p>
        <p style={S.disc}>
          Research &amp; educational tool. Not investment advice. · Data via Alpaca &amp; Yahoo Finance.
        </p>
      </footer>
    </div>
  );
}

/* ── Sub-components ── */

function Stat({ label, value, big, tone }: {
  label: string; value: string; big?: boolean; tone?: "up" | "down";
}) {
  const color = tone === "up" ? "#7bbf95" : tone === "down" ? "#d98a72" : "#ece6d8";
  return (
    <div style={S.statCell}>
      <div style={S.statLabel}>
        {tone === "up"   && <TrendingUp   size={12} style={{ marginRight: 5, verticalAlign: "middle" }} />}
        {tone === "down" && <TrendingDown size={12} style={{ marginRight: 5, verticalAlign: "middle" }} />}
        {label}
      </div>
      <div style={{ ...S.statVal, color, fontSize: big ? 54 : 42 }}>{value}</div>
    </div>
  );
}

function PanelHead({ n, title, sub, icon }: {
  n: string; title: string; sub: string; icon?: React.ReactNode;
}) {
  return (
    <div style={S.panelHead}>
      <span style={S.panelNo}>{n}</span>
      <div>
        <div style={S.panelTitle}>
          {icon && <span style={{ marginRight: 6, opacity: 0.7 }}>{icon}</span>}
          {title}
        </div>
        <div style={S.panelSub}>{sub}</div>
      </div>
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

function ProMini({ label, value, tip }: { label: string; value: string; tip?: string }) {
  return (
    <div style={S.proMiniCell} title={tip}>
      <div style={S.proMiniVal}>{value}</div>
      <div style={S.miniLabel}>{label}</div>
    </div>
  );
}

function Tape({ label, value, tone, tag }: {
  label: string; value: string; tone?: boolean; tag?: string;
}) {
  const neg = !!tone && value.startsWith("-");
  const color = !tone ? "#ece6d8" : neg ? "#d98a72" : "#7bbf95";
  return (
    <div style={S.tapeRow}>
      <span style={S.tapeLabel}>{label}</span>
      <span style={{ ...S.tapeVal, color }}>
        {value}
        {tag && <em style={S.tapeTag}>{tag}</em>}
      </span>
    </div>
  );
}

function EtfCard({ etf, info, color }: {
  etf: { key: string; name: string; assetClass: string; weight: number; riskContribution: number };
  info: EtfDetail;
  color: string;
}) {
  return (
    <div style={{
      marginTop: 16,
      padding: "14px 16px",
      background: "#0a0d10",
      border: `1px solid ${color}33`,
      borderLeft: `3px solid ${color}`,
      borderRadius: 4,
      animation: "rise .25s ease forwards",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
        <div>
          <span style={{ fontFamily: "IBM Plex Mono", fontSize: 15, color, fontWeight: 600 }}>{etf.key}</span>
          <span style={{ fontFamily: "'Fraunces',serif", fontSize: 13, color: "#c8c2b4", marginLeft: 10 }}>{info.fullName}</span>
        </div>
        <span style={{ fontFamily: "IBM Plex Mono", fontSize: 10, color: "#5e5a4e", letterSpacing: 1 }}>
          TER {info.expenseRatio}
        </span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 12px", fontSize: 12 }}>
        <span style={{ color: "#6f6a5f", letterSpacing: 1, fontSize: 10, textTransform: "uppercase", paddingTop: 1 }}>Tracks</span>
        <span style={{ color: "#a39a82", lineHeight: 1.5 }}>{info.tracks}</span>
        <span style={{ color: "#6f6a5f", letterSpacing: 1, fontSize: 10, textTransform: "uppercase", paddingTop: 1 }}>Why</span>
        <span style={{ color: "#8a8576", lineHeight: 1.55 }}>{info.why}</span>
        <span style={{ color: "#6f6a5f", letterSpacing: 1, fontSize: 10, textTransform: "uppercase", paddingTop: 1 }}>Geo</span>
        <span style={{ color: "#7fa6a0", fontFamily: "IBM Plex Mono", fontSize: 11 }}>{info.geography}</span>
      </div>
      <div style={{ display: "flex", gap: 20, marginTop: 10, paddingTop: 10, borderTop: "1px solid #1d2127" }}>
        <span style={{ fontSize: 11, fontFamily: "IBM Plex Mono", color: "#7a7566" }}>
          Weight <b style={{ color: "#ece6d8" }}>{pct(etf.weight)}</b>
        </span>
        <span style={{ fontSize: 11, fontFamily: "IBM Plex Mono", color: "#7a7566" }}>
          Risk contribution <b style={{ color: "#7fa6a0" }}>{pct(etf.riskContribution)}</b>
        </span>
        <span style={{ fontSize: 11, fontFamily: "IBM Plex Mono", color: "#7a7566" }}>
          Class <b style={{ color: "#c8c2b4" }}>{etf.assetClass}</b>
        </span>
      </div>
    </div>
  );
}

function DonutTip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload as { key: string; name: string; weight: number; assetClass: string; riskContribution: number };
  const info = ETF_INFO[d.key];
  return (
    <div style={{ ...S.tip, maxWidth: 260 }}>
      <b style={{ color: "#e8b34e" }}>{d.key}</b>
      {info && <span style={{ color: "#8a8576", fontSize: 11 }}> · {info.fullName}</span>}
      <br />
      <span style={{ color: "#9a958a", fontSize: 11 }}>{d.assetClass} · {pct(d.weight)}</span><br />
      {info && (
        <span style={{ color: "#7a7566", fontSize: 11, lineHeight: 1.5, display: "block", marginTop: 4 }}>
          {info.tracks}
        </span>
      )}
      <span style={{ color: "#7fa6a0", fontSize: 11, display: "block", marginTop: 3 }}>
        Risk contribution: {pct(d.riskContribution)}
      </span>
    </div>
  );
}

function FrontierTip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return <div style={S.tip}>σ {(+d.x).toFixed(2)}% · μ {(+d.y).toFixed(2)}%</div>;
}

function Term({ term, def }: { term: string; def: string }) {
  return (
    <div>
      <div style={S.termName}>{term}</div>
      <div style={S.termDef}>{def}</div>
    </div>
  );
}

/* ── Styles ── */
const S: Record<string, React.CSSProperties> = {
  root: {
    background: "#0b0d0f", minHeight: "100vh", paddingBottom: 60,
    fontFamily: "'IBM Plex Sans', sans-serif", color: "#ece6d8",
    backgroundImage:
      "radial-gradient(1200px 600px at 80% -10%,rgba(212,162,78,.07),transparent 60%)," +
      "radial-gradient(900px 500px at -10% 110%,rgba(127,166,160,.05),transparent 60%)",
  },
  wrap: { maxWidth: 1080, margin: "0 auto", padding: "0 28px" },
  topbar: { display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 34 },
  kicker: { fontSize: 11, letterSpacing: 3, color: "#8a8472", fontWeight: 600 },
  methodBadge: {
    fontSize: 10, letterSpacing: 1.5, color: "#7fa6a0", border: "1px solid #2a3830",
    borderRadius: 20, padding: "4px 10px", background: "rgba(127,166,160,.06)",
  },
  regimeWrap: {
    fontSize: 11, letterSpacing: 2, color: "#bcae8f",
    display: "flex", alignItems: "center", gap: 7,
    border: "1px solid #2c3026", borderRadius: 20, padding: "5px 12px",
    background: "rgba(188,174,143,.05)",
  },
  regimeDot: { width: 6, height: 6, borderRadius: 6, background: "#cdbf7a", boxShadow: "0 0 8px #cdbf7a" },
  rule: { height: 1, background: "linear-gradient(90deg,#2a2f36,transparent)", margin: "20px 0 26px" },
  mastRow: { display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 20 },
  h1: {
    fontFamily: "'Fraunces', serif", fontWeight: 500, fontSize: 52,
    lineHeight: 1.02, margin: 0, letterSpacing: -0.5, color: "#f4efe3",
  },
  dateBlock: { textAlign: "right" },
  dateLabel: { fontSize: 10, letterSpacing: 2.5, color: "#7a7566" },
  dateVal: { fontFamily: "'Fraunces', serif", fontSize: 22, color: "#e8b34e", margin: "2px 0" },
  dateSub: { fontSize: 11.5, color: "#8a8576", fontFamily: "IBM Plex Mono" },
  intro: { fontSize: 14.5, lineHeight: 1.75, color: "#b8b2a4", maxWidth: 720, marginTop: 22, marginBottom: 0 },

  statGrid: {
    display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 1, marginTop: 40,
    background: "#1c2025", border: "1px solid #1c2025", borderRadius: 4, overflow: "hidden",
  },
  statCell: { background: "#0e1113", padding: "26px 24px" },
  statLabel: { fontSize: 11, letterSpacing: 1.2, color: "#8a8576", marginBottom: 14, textTransform: "uppercase" },
  statVal: { fontFamily: "'IBM Plex Mono', monospace", fontWeight: 500, lineHeight: 1, letterSpacing: -1 },
  headlineNote: {
    fontSize: 12, lineHeight: 1.6, color: "#7a7566", marginTop: 14, maxWidth: 640,
    borderLeft: "2px solid #2a2f36", paddingLeft: 12,
  },

  chartGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginTop: 20 },
  panel: { background: "#0e1113", border: "1px solid #1d2127", borderRadius: 4, padding: 22 },
  panelHead: { display: "flex", gap: 12, alignItems: "baseline", marginBottom: 20 },
  panelNo: { fontFamily: "IBM Plex Mono", fontSize: 11, color: "#5e5a4e", borderRight: "1px solid #2a2f36", paddingRight: 12 },
  panelTitle: { fontFamily: "'Fraunces', serif", fontSize: 19, color: "#f0ead8", display: "flex", alignItems: "center" },
  panelSub: { fontSize: 11, color: "#7a7566", letterSpacing: 1, marginTop: 1 },

  donutCenter: {
    position: "absolute", inset: 0, display: "flex", flexDirection: "column",
    alignItems: "center", justifyContent: "center", pointerEvents: "none",
  },
  donutTop: { fontSize: 10, letterSpacing: 2, color: "#7a7566" },
  donutPct: { fontFamily: "IBM Plex Mono", fontSize: 30, color: "#e8b34e", lineHeight: 1.1 },
  donutSub: { fontSize: 10, color: "#8a8576", maxWidth: 110, textAlign: "center" },
  legend: { flex: 1, minWidth: 150, display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 14px" },
  legRow: { display: "flex", alignItems: "center", gap: 7, cursor: "default", padding: "2px 0" },
  legDot: { width: 8, height: 8, borderRadius: 2, flexShrink: 0 },
  legTk: { fontFamily: "IBM Plex Mono", fontSize: 12.5, color: "#cfc8b8", flex: 1 },
  legPct: { fontFamily: "IBM Plex Mono", fontSize: 12.5, color: "#8a8576" },

  frontierKey: { display: "flex", gap: 22, fontSize: 11, color: "#8a8576", marginTop: 6, fontFamily: "IBM Plex Mono" },
  keyDot: { display: "inline-block", width: 8, height: 8, borderRadius: 8, marginRight: 6, verticalAlign: "middle" },

  tHead: {
    display: "grid", gridTemplateColumns: "2fr 1.2fr 1.3fr 1.3fr",
    fontSize: 10, letterSpacing: 1.3, color: "#6f6a5f", padding: "0 0 10px",
    borderBottom: "1px solid #1d2127",
  },
  tRow: {
    display: "grid", gridTemplateColumns: "2fr 1.2fr 1.3fr 1.3fr",
    alignItems: "center", padding: "11px 0", borderBottom: "1px solid #15181c",
  },
  coCell: { display: "flex", alignItems: "center", gap: 10, minWidth: 0 },
  coName: { display: "block", fontSize: 13.5, color: "#f0ead8", fontWeight: 500 },
  coTk: { display: "block", fontFamily: "IBM Plex Mono", fontSize: 10.5, color: "#7a7566", letterSpacing: 0.5, marginTop: 1 },
  secCell: { fontSize: 12.5, color: "#9a958a" },
  wCell: { display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 10 },
  barTrack: { width: 70, height: 4, background: "#1d2127", borderRadius: 3, overflow: "hidden" },
  barFill: { display: "block", height: "100%", borderRadius: 3 },
  wNum: { fontFamily: "IBM Plex Mono", fontSize: 13, color: "#ece6d8", minWidth: 48, textAlign: "right", fontWeight: 500 },

  /* benchmark table */
  compTable: { width: "100%", borderCollapse: "collapse", fontFamily: "IBM Plex Mono" },
  thLeft: { fontSize: 10, letterSpacing: 1.3, color: "#6f6a5f", padding: "0 12px 10px 0", textAlign: "left", fontFamily: "IBM Plex Sans" },
  th: { fontSize: 10, letterSpacing: 1.3, color: "#6f6a5f", padding: "0 0 10px 12px", textAlign: "right", fontFamily: "IBM Plex Sans" },
  tdLeft: { fontSize: 13, padding: "12px 12px 12px 0", borderTop: "1px solid #15181c", fontFamily: "IBM Plex Sans" },
  td: { fontSize: 13, padding: "12px 0 12px 12px", borderTop: "1px solid #15181c", textAlign: "right" },
  portfolioBadge: {
    marginLeft: 8, fontSize: 9, letterSpacing: 1.2, color: "#e8b34e",
    border: "1px solid #3a2e10", padding: "2px 6px", borderRadius: 3,
  },

  dualGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginTop: 20 },
  miniGrid: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1, background: "#1d2127", borderRadius: 4, overflow: "hidden" },
  miniCell: { background: "#0c0f11", padding: "20px 18px" },
  miniVal: { fontFamily: "IBM Plex Mono", fontSize: 28, color: "#ece6d8", lineHeight: 1 },
  miniLabel: { fontSize: 11, letterSpacing: 1, color: "#8a8576", marginTop: 8, textTransform: "uppercase" },
  proMiniCell: { background: "#0c0f11", padding: "14px 14px", cursor: "help" },
  proMiniVal: { fontFamily: "IBM Plex Mono", fontSize: 20, color: "#c8c2b4", lineHeight: 1 },

  tape: { display: "flex", flexDirection: "column" },
  tapeRow: { display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10.5px 0", borderBottom: "1px solid #15181c" },
  tapeLabel: { fontSize: 12.5, color: "#9a958a", letterSpacing: 0.5 },
  tapeVal: { fontFamily: "IBM Plex Mono", fontSize: 15, display: "flex", alignItems: "center", gap: 8 },
  tapeTag: {
    fontSize: 9, letterSpacing: 1, color: "#8a8576", fontStyle: "normal",
    border: "1px solid #2a2f36", borderRadius: 3, padding: "1px 5px", textTransform: "uppercase",
  },

  glossary: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px 32px" },
  termName: { fontSize: 13.5, color: "#e0c178", fontWeight: 600, marginBottom: 4 },
  termDef: { fontSize: 12.5, lineHeight: 1.6, color: "#8a8576" },

  footer: { marginTop: 34, paddingTop: 22, borderTop: "1px solid #1d2127" },
  method: { fontSize: 12.5, lineHeight: 1.7, color: "#8a8576", maxWidth: 760, margin: 0 },
  disc: { fontSize: 11, color: "#5e5a4e", marginTop: 12, letterSpacing: 0.3, fontFamily: "IBM Plex Mono" },
  tip: {
    background: "#15181c", border: "1px solid #2a2f36", borderRadius: 4,
    padding: "8px 11px", fontFamily: "IBM Plex Mono", fontSize: 12.5, color: "#ece6d8",
  },
};

const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
* { box-sizing: border-box; }
body { margin: 0; background: #0b0d0f; }
::selection { background: #e8b34e; color: #0b0d0f; }
.rise { opacity:0; transform:translateY(14px); animation:rise .7s cubic-bezier(.2,.7,.2,1) forwards; }
.d1{animation-delay:.08s} .d2{animation-delay:.16s} .d3{animation-delay:.24s} .d4{animation-delay:.32s} .d5{animation-delay:.40s}
@keyframes rise { to { opacity:1; transform:none; } }
.recharts-surface { overflow:visible; }
@media (max-width:760px){
  .rise h1{font-size:34px!important}
  [style*="repeat(4,1fr)"]{grid-template-columns:1fr 1fr!important}
  [style*="grid-template-columns: 1fr 1fr"]>div+div{margin-top:0}
  [style*="chartGrid"],[style*="dualGrid"]{grid-template-columns:1fr!important}
}
`;

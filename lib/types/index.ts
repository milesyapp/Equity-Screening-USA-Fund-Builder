// lib/types/index.ts
// Data contract for the US Equity Screener (backend v2.x).
// Mirrors the JSON written by python/run_screen.py (and refreshed by run_daily.py).

export interface StockPick {
  rank: number;
  ticker: string;
  name: string;
  sector: string;
  subIndustry: string;
  price: number | null;
  score: number;
  healthScore: number;
  valuationScore: number;
  momentumScore: number;

  // Fundamentals (any may be null when a company doesn't report the line item)
  peRatio: number | null;
  dividendYield: number | null;
  grossMargin: number | null;
  operatingMargin: number | null;
  netMargin: number | null;
  returnOnEquity: number | null;
  fcfMargin: number | null;
  fcfYield: number | null;
  revenueGrowth: number | null;
  debtToEquity: number | null;
  marketCap: number | null;

  // Trailing price returns
  return1W: number | null;
  return1M: number | null;
  return3M: number | null;
  return6M: number | null;
  return1Y: number | null;

  reasons: string[];
  flags: string[];
  fundWeight: number;
}

export interface FundWindow {
  annualReturn: number;
  annualVolatility: number;
  sharpeRatio: number;
  // Optional: absent from JSON produced by backend versions < 2.2.
  sortinoRatio?: number | null;
  maximumDrawdown: number;
  // Optional: absent from JSON produced by backend versions < 2.2.
  calmarRatio?: number | null;
  alpha: number | null;
  // Newey-West t-statistic of the daily OLS alpha (|t| >= ~2 ≈ significant at
  // 5%). Optional: absent from JSON produced by backend versions < 2.1.
  alphaTStat?: number | null;
  beta: number | null;
  benchmarkReturn: number;
}

export interface NavPoint {
  date: string;
  fund: number;
  benchmark: number;
}

export interface SectorWeight {
  sector: string;
  weight: number;
}

export interface Fund {
  name: string;
  constituents: number;
  weighting: string;
  benchmark: string;
  blended: {
    pe: number | null;
    fcfYield: number | null;
    revenueGrowth: number | null;
    returnOnEquity: number | null;
    netMargin: number | null;
  };
  metrics3Y: FundWindow | null;
  metrics5Y: FundWindow | null;
  navSeries: NavPoint[];
  sectorBreakdown: SectorWeight[];
}

export interface Methodology {
  weights: { health: number; valuation: number; momentum: number };
  healthFactors: string[];
  valuationFactors: string[];
  momentumFactors: string[];
  // Known, disclosed limitations of the data/methodology, written by the
  // backend and rendered verbatim. Optional: absent before backend v2.1.
  limitations?: string[];
  // Sector-neutral scoring descriptor. Optional: absent before backend v2.3.
  sectorNeutral?: {
    pillars: string[];
    groupBy: string;
    minCount: number;
    momentumScope: string;
  };
}

// --- Classical-vs-quantum research instrumentation -------------------------
// Mirrors python/core/research_log.py. Each arm reuses the Fund type above, so
// any arm renders with the existing fund components.

export interface QuboDiagnostics {
  solver: string;
  isQuantum: boolean;
  numReads: number | null;
  bestEnergy: number | null;
  energyStd: number | null;
  chainBreakFraction: number | null; // QPU only
  numQubitsUsed: number | null;      // QPU only (post-embedding)
  wallSeconds: number | null;
  lambdas: { l1: number; l2: number; l3: number; l4: number } | null;
  targetSize: number | null;
}

export interface FundArm {
  key: "greedy" | "qubo_classical" | "qubo_quantum" | string;
  label: string;
  isQuantum: boolean;
  selection: string[];
  weights: Record<string, number>;
  diagnostics: QuboDiagnostics | null; // null for the greedy arm
  fund: Fund;
}

export interface SelectionComparison {
  pair: string;            // e.g. "qubo_classical_vs_qubo_quantum"
  jaccard: number | null;
  overlapCount: number;
  nA: number;
  nB: number;
  onlyA: string[];
  onlyB: string[];
}

export interface SharpeDifference {
  difference: number | null;
  ci95: [number, number] | null;
  pValue: number | null;
  method?: string;
  note?: string;
}

export interface ForwardArmStat {
  arm: string;
  vsBaseline: string;
  nDays: number;
  activeReturnCumulative?: number | null;
  activeReturnAnnualised: number | null;
  minDaysForAnnualised?: number;
  trackingError: number | null;
  informationRatio: number | null;
  sharpe: { arm: number | null; baseline: number | null };
  // Robustness-to-non-normality stats (backend >= 2.2; all optional for
  // back-compat with old latest.json blobs). maxDrawdown is cumulative and
  // ungated; sortino (zero-rf) and probSharpePositive (Bailey-López de Prado
  // PSR vs 0) gate at minDaysForAnnualised; calmar gates at minDaysForCalmar.
  maxDrawdown?: { arm: number | null; baseline: number | null };
  sortino?: { arm: number | null; baseline: number | null };
  minDaysForCalmar?: number;
  calmar?: { arm: number | null; baseline: number | null };
  probSharpePositive?: { arm: number | null; baseline: number | null };
  neweyWestT_meanActive: number | null;
  sharpeDifference: SharpeDifference;
  ledoitWolfTest: unknown | null; // reserved hook
}

export interface ForwardStats {
  available: boolean;
  nDays: number;
  baseline?: string;
  perArm?: ForwardArmStat[];
  caveat?: string;
  reason?: string;
}

export interface ResearchBlock {
  schemaVersion: number;
  asOf: string;
  inceptionDate: string;
  baselineArm: string;
  armOrder: string[];
  arms: FundArm[];
  selectionComparison: SelectionComparison[];
  forwardStats: ForwardStats;
  // Growth of $1 from realized forward returns only (one point per logged run).
  // Keys beyond `date` are arm keys; an arm appears from its own inception.
  forwardNav?: Array<{ date: string } & Record<string, number | string>>;
  disclaimer: string;
}

export interface MarketConditions {
  date?: string;
  vix?: number | null;
  volatilityLevel?: string;
  riskSentiment?: string;
  sp500Return?: number | null;
  nasdaqReturn?: number | null;
  treasuryYield?: number | null;
  marketSummary?: Record<string, { weeklyReturn?: number | null }>;
}

export interface Screen {
  asOf: string;
  pricesAsOf?: string;
  universeSize: number;
  screenedCount: number;
  scoredCount: number;
  excludedCount: number;
  exclusionReasons: Record<string, number>;
  minHistoryYears: number;
  methodology: Methodology;
  stocks: StockPick[];
  fund: Fund;
  research?: ResearchBlock | null;
  marketConditions?: MarketConditions | null;
}

// The wrapper the backend prints and lib/portfolio.ts reads.
export interface PipelineOutput {
  success: boolean;
  error?: string;
  date?: string;
  elapsed_seconds?: number;
  backend_version?: string;
  run_type?: string;
  portfolio?: Screen;
}

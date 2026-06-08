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
  maximumDrawdown: number;
  alpha: number | null;
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

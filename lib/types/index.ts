// Portfolio types
export interface PortfolioWeights {
  [ticker: string]: number;
}

export interface PortfolioMetrics {
  annualReturn: number;
  annualVolatility: number;
  sharpeRatio: number;
  sortinoRatio: number;
  maximumDrawdown: number;
  calmarRatio: number;
}

export interface Stock {
  ticker: string;
  weight: number;
  avgVolume: number;
  totalReturn: number;
  sector: string;
  peRatio: number;
  dividendYield: number;
}

export interface PortfolioData {
  date: string;
  weights: PortfolioWeights;
  metrics: PortfolioMetrics;
  stocks: Stock[];
  marketRegime: 'risk-on' | 'risk-off' | 'neutral';
  efficientFrontier: EfficientFrontierPoint[];
}

export interface EfficientFrontierPoint {
  volatility: number;
  return: number;
  sharpeRatio: number;
}

export interface MarketConditions {
  date: string;
  vix: number;
  sp500Return: number;
  nsdaqReturn: number;
  treasuryYield: number;
  riskSentiment: 'risk-on' | 'risk-off' | 'neutral';
  volatilityLevel: 'low' | 'moderate' | 'high';
  marketSummary: Record<string, {
    ticker: string;
    weeklyReturn: number;
    price: number;
  }>;
}

export interface BlogPost {
  id: string;
  date: string;
  title: string;
  content: string;
  excerpt: string;
  portfolio: PortfolioData;
  marketConditions: MarketConditions;
  aiGenerated: boolean;
  published: boolean;
  createdAt: Date;
  updatedAt: Date;
}

export interface APIResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}

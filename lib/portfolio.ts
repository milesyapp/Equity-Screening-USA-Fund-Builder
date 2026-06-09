// lib/portfolio.ts
// Server-only: reads the JSON the Python screener writes to data/latest.json.
// run_screen.py writes it weekly; run_daily.py refreshes prices in place.

import fs from "fs";
import path from "path";
import type { PipelineOutput, Screen, ResearchBlock } from "./types";

const DATA_PATH = path.join(process.cwd(), "data", "latest.json");

export function getScreen(): Screen | null {
  try {
    const raw = fs.readFileSync(DATA_PATH, "utf-8");
    const parsed = JSON.parse(raw) as PipelineOutput;
    if (!parsed.success || !parsed.portfolio) return null;
    return parsed.portfolio;
  } catch {
    return null;
  }
}

// Returns the classical-vs-quantum research block, or null until the quantum
// arm ships. Decoupled so the existing dashboard is unaffected by its absence.
export function getResearch(): ResearchBlock | null {
  const screen = getScreen();
  return screen?.research ?? null;
}

export function getMeta(): Pick<
  PipelineOutput,
  "date" | "elapsed_seconds" | "backend_version" | "run_type"
> | null {
  try {
    const raw = fs.readFileSync(DATA_PATH, "utf-8");
    const parsed = JSON.parse(raw) as PipelineOutput;
    return {
      date: parsed.date,
      elapsed_seconds: parsed.elapsed_seconds,
      backend_version: parsed.backend_version,
      run_type: parsed.run_type,
    };
  } catch {
    return null;
  }
}

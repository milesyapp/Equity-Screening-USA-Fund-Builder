// app/api/portfolio/route.ts
// Serves the latest screen as JSON at /api/portfolio (client refresh / external use).

import { NextResponse } from "next/server";
import { getScreen } from "../../../lib/portfolio";

export const dynamic = "force-dynamic";

export async function GET() {
  const screen = getScreen();
  if (!screen) {
    return NextResponse.json(
      { error: "No screen data yet. Run run_screen.py and copy output to data/latest.json." },
      { status: 404 }
    );
  }
  return NextResponse.json(screen);
}

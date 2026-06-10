// app/screener/page.tsx
// Server component: reads the screener JSON on the server, hands it to the
// client component for rendering + interactivity.

import { getScreen, getMeta } from "../../lib/portfolio";
import Screener from "../components/Screener";
import type { CSSProperties } from "react";

export const dynamic = "force-dynamic"; // re-read on every request

export default function Home() {
  const screen = getScreen();
  const meta = getMeta();

  if (!screen) {
    return (
      <main style={EMPTY}>
        <div>
          <p style={{ fontSize: 18, marginBottom: 10 }}>No screen data yet.</p>
          <p style={{ fontSize: 13, color: "#8a8576", lineHeight: 1.8 }}>
            Run the weekly screen, then copy its output to{" "}
            <code style={{ color: "#e8b34e" }}>data/latest.json</code>:
            <br />
            <code style={{ color: "#bcae8f" }}>
              cd python &amp;&amp; python3 run_screen.py &gt; test_output.json &amp;&amp; cd ..
            </code>
            <br />
            <code style={{ color: "#bcae8f" }}>
              mkdir -p data &amp;&amp; cp python/test_output.json data/latest.json
            </code>
          </p>
        </div>
      </main>
    );
  }

  // Guard against an old multi-asset latest.json (no `stocks` array).
  if (!Array.isArray(screen.stocks) || screen.stocks.length === 0) {
    return (
      <main style={EMPTY}>
        <div>
          <p style={{ fontSize: 18, marginBottom: 10 }}>Data is out of date.</p>
          <p style={{ fontSize: 13, color: "#8a8576", lineHeight: 1.8 }}>
            <code style={{ color: "#e8b34e" }}>data/latest.json</code> isn&apos;t in the
            screener format. Re-run <code style={{ color: "#bcae8f" }}>run_screen.py</code> and
            copy the fresh output to <code style={{ color: "#bcae8f" }}>data/latest.json</code>.
          </p>
        </div>
      </main>
    );
  }

  return <Screener data={screen} meta={meta} />;
}

const EMPTY: CSSProperties = {
  minHeight: "100vh",
  background: "#0b0d0f",
  color: "#ece6d8",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  fontFamily: "monospace",
  padding: 32,
  textAlign: "center",
};

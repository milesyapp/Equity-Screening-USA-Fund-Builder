// app/page.tsx
// New home: the research-publication landing page. The screener now lives at
// /screener. Data comes from the existing /api/portfolio route via <Landing/>.

import Landing from "./components/Landing";

export const dynamic = "force-dynamic";

export default function Home() {
  return <Landing />;
}

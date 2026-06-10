// app/fund/[arm]/page.tsx
// Per-arm detail route. [arm] is greedy | qubo_classical | qubo_quantum.
// FundDetail reads /api/portfolio and resolves the arm itself.

import FundDetail from "../../components/FundDetail";

export const dynamic = "force-dynamic";

export default async function FundPage({
  params,
}: {
  params: Promise<{ arm: string }>;
}) {
  const { arm } = await params;
  return <FundDetail arm={arm} />;
}

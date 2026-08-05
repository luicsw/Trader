import { useMemo, useState } from 'react'
import { useProjectedIncome } from '../api/hooks'
import type { HorizonProjection, ProjectionHolding } from '../api/types'

// Stable empty fallback so `horizons` keeps a constant reference across renders when there's no
// data yet -- otherwise a fresh `[]` each render would destabilize the useMemo deps below.
const NO_HORIZONS: HorizonProjection[] = []

// Portfolio income projection (spec.md FR-27 to FR-29). Fetches every holding at all three
// horizons in one call; the include/exclude chips filter the displayed totals client-side from
// that per-holding data (instant, no re-fetch) -- the server still owns each holding's
// expected_profit and eligibility. Ineligible cells show the AI's reason, never a hidden or
// zeroed value (the same honest-null convention used for price targets elsewhere).
export function ProjectionPanel() {
  const { data } = useProjectedIncome()
  const [excluded, setExcluded] = useState<Set<string>>(new Set())

  const horizons = data?.horizons ?? NO_HORIZONS
  const tickers = useMemo(() => (horizons[0]?.holdings ?? []).map((h) => h.ticker), [horizons])

  const cell = useMemo(() => {
    const map: Record<string, Record<number, ProjectionHolding>> = {}
    for (const block of horizons) {
      for (const holding of block.holdings) {
        map[holding.ticker] ??= {}
        map[holding.ticker][block.horizon_days] = holding
      }
    }
    return map
  }, [horizons])

  if (horizons.length === 0 || tickers.length === 0) return null

  function toggle(ticker: string) {
    setExcluded((prev) => {
      const next = new Set(prev)
      if (next.has(ticker)) next.delete(ticker)
      else next.add(ticker)
      return next
    })
  }

  const included = tickers.filter((ticker) => !excluded.has(ticker))
  const totals = horizons.map((block) => {
    const sum = included.reduce((acc, ticker) => acc + (cell[ticker]?.[block.horizon_days]?.expected_profit ?? 0), 0)
    const count = included.filter((ticker) => cell[ticker]?.[block.horizon_days]?.eligible).length
    return { horizon: block.horizon_days, sum, count }
  })

  return (
    <div className="mb-8 rounded-2xl border border-slate-800 bg-slate-900/40 p-5">
      <h2 className="text-lg font-semibold text-slate-100">Projected income if sold within…</h2>
      <p className="mt-1 text-xs text-slate-500">
        Expected profit from each position's latest AI sell target — a simplified projection, not advice.
        Positions with no reachable target for a horizon show the AI's reason instead of a number.
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        {tickers.map((ticker) => {
          const on = !excluded.has(ticker)
          return (
            <button
              key={ticker}
              type="button"
              onClick={() => toggle(ticker)}
              className={`rounded-full border px-3 py-1 text-xs font-medium ${
                on ? 'border-sky-500 bg-sky-500/10 text-sky-300' : 'border-slate-700 text-slate-500'
              }`}
            >
              {ticker}
            </button>
          )
        })}
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-500">
              <th className="py-2 pr-4 font-medium">Position</th>
              {horizons.map((block) => (
                <th key={block.horizon_days} className="py-2 pr-4 font-medium">
                  {block.horizon_days}d
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tickers.map((ticker) => (
              <tr key={ticker} className={`border-t border-slate-800 ${excluded.has(ticker) ? 'opacity-40' : ''}`}>
                <td className="py-2 pr-4 font-medium text-slate-200">{ticker}</td>
                {horizons.map((block) => {
                  const entry = cell[ticker]?.[block.horizon_days]
                  if (!entry) {
                    return (
                      <td key={block.horizon_days} className="py-2 pr-4 text-slate-600">
                        —
                      </td>
                    )
                  }
                  if (!entry.eligible) {
                    return (
                      <td key={block.horizon_days} className="py-2 pr-4 text-xs text-slate-500">
                        {entry.reason}
                      </td>
                    )
                  }
                  const profit = entry.expected_profit ?? 0
                  return (
                    <td
                      key={block.horizon_days}
                      className={`py-2 pr-4 ${profit >= 0 ? 'text-emerald-400' : 'text-red-400'}`}
                    >
                      {profit >= 0 ? '+' : ''}${profit.toFixed(2)}
                    </td>
                  )
                })}
              </tr>
            ))}
            <tr className="border-t border-slate-700">
              <td className="py-2 pr-4 text-xs font-semibold uppercase tracking-wide text-slate-400">Total</td>
              {totals.map((total) => (
                <td key={total.horizon} className="py-2 pr-4">
                  <span className={`font-semibold ${total.sum >= 0 ? 'text-emerald-300' : 'text-red-300'}`}>
                    {total.sum >= 0 ? '+' : ''}${total.sum.toFixed(2)}
                  </span>
                  <span className="ml-1 text-xs text-slate-600">({total.count} eligible)</span>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}

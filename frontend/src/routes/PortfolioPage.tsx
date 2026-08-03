import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useHoldings, useRemoveHolding, useUpsertHolding } from '../api/hooks'
import { ApiError } from '../api/client'
import { Skeleton } from '../components/Skeleton'

// Personal holdings tracking (Post-Phase-5 addition) -- deliberately scoped to shares + cost
// basis only, per the user's explicit decision: no tax lots, no realized-gains accounting, no
// cross-brokerage import. Adding a position here auto-promotes the ticker to the watchlist
// (backend-side), so it also shows up on the dashboard.
export function PortfolioPage() {
  const { data: holdings, isLoading } = useHoldings()
  const upsertMutation = useUpsertHolding()
  const removeMutation = useRemoveHolding()

  const [ticker, setTicker] = useState('')
  const [shares, setShares] = useState('')
  const [costBasis, setCostBasis] = useState('')
  const [acquiredAt, setAcquiredAt] = useState('')
  const [notes, setNotes] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  const totals = (holdings ?? []).reduce(
    (acc, h) => ({
      marketValue: acc.marketValue + (h.market_value ?? 0),
      costBasis: acc.costBasis + h.cost_basis_total,
    }),
    { marketValue: 0, costBasis: 0 },
  )
  const totalGain = totals.marketValue - totals.costBasis

  function resetForm() {
    setTicker('')
    setShares('')
    setCostBasis('')
    setAcquiredAt('')
    setNotes('')
    setFormError(null)
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setFormError(null)
    const sharesNum = Number(shares)
    const costBasisNum = Number(costBasis)
    if (!ticker.trim() || !(sharesNum > 0) || !(costBasisNum > 0)) {
      setFormError('Ticker, shares, and cost basis (both > 0) are required.')
      return
    }

    upsertMutation.mutate(
      {
        ticker: ticker.trim(),
        input: {
          shares: sharesNum,
          cost_basis_per_share: costBasisNum,
          acquired_at: acquiredAt ? new Date(acquiredAt).toISOString() : null,
          notes: notes.trim() || null,
        },
      },
      {
        onSuccess: () => resetForm(),
        onError: (error) => setFormError(error instanceof ApiError ? error.message : 'Failed to save position.'),
      },
    )
  }

  function startEdit(holding: NonNullable<typeof holdings>[number]) {
    setTicker(holding.ticker)
    setShares(String(holding.shares))
    setCostBasis(String(holding.cost_basis_per_share))
    setAcquiredAt(holding.acquired_at ? holding.acquired_at.slice(0, 10) : '')
    setNotes(holding.notes ?? '')
    setFormError(null)
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <h1 className="mb-6 text-2xl font-semibold text-slate-100">Portfolio</h1>

      {holdings && holdings.length > 0 && (
        <div className="mb-6 grid grid-cols-3 gap-4 rounded-2xl border border-slate-800 bg-slate-900/40 p-5">
          <div>
            <div className="text-xs text-slate-500">Market Value</div>
            <div className="text-lg font-semibold text-slate-100">${totals.marketValue.toFixed(2)}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500">Cost Basis</div>
            <div className="text-lg font-semibold text-slate-100">${totals.costBasis.toFixed(2)}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500">Unrealized Gain/Loss</div>
            <div className={`text-lg font-semibold ${totalGain >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {totalGain >= 0 ? '+' : ''}${totalGain.toFixed(2)}
            </div>
          </div>
        </div>
      )}

      <form
        onSubmit={handleSubmit}
        className="mb-8 grid grid-cols-2 gap-3 rounded-2xl border border-slate-800 bg-slate-900/40 p-5 sm:grid-cols-4"
      >
        <input
          value={ticker}
          onChange={(event) => setTicker(event.target.value.toUpperCase())}
          placeholder="Ticker"
          className="col-span-2 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none sm:col-span-1"
        />
        <input
          value={shares}
          onChange={(event) => setShares(event.target.value)}
          placeholder="Shares"
          type="number"
          step="any"
          className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none"
        />
        <input
          value={costBasis}
          onChange={(event) => setCostBasis(event.target.value)}
          placeholder="Cost basis / share"
          type="number"
          step="any"
          className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none"
        />
        <input
          value={acquiredAt}
          onChange={(event) => setAcquiredAt(event.target.value)}
          type="date"
          className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none"
        />
        <input
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          placeholder="Notes (optional)"
          className="col-span-2 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none sm:col-span-3"
        />
        <button
          type="submit"
          disabled={upsertMutation.isPending}
          className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-400 disabled:opacity-50"
        >
          {upsertMutation.isPending ? 'Saving…' : 'Save position'}
        </button>
        {formError && <p className="col-span-full text-sm text-red-400">{formError}</p>}
      </form>

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 2 }).map((_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      ) : !holdings || holdings.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-800 p-12 text-center">
          <p className="text-slate-400">No positions tracked yet.</p>
          <p className="mt-1 text-sm text-slate-500">Add one above to get AI verdicts aware of your position.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {holdings.map((holding) => (
            <div
              key={holding.ticker}
              className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-800 bg-slate-900/40 p-5"
            >
              <div>
                <Link to={`/company/${holding.ticker}`} className="font-semibold text-slate-100 hover:text-sky-400">
                  {holding.ticker}
                </Link>
                <div className="text-sm text-slate-400">
                  {holding.shares} sh @ ${holding.cost_basis_per_share.toFixed(2)}
                </div>
                {holding.notes && <div className="mt-1 text-xs text-slate-500">{holding.notes}</div>}
              </div>
              <div className="flex items-center gap-4">
                <div className="text-right">
                  <div className="text-slate-100">
                    {holding.market_value != null ? `$${holding.market_value.toFixed(2)}` : '—'}
                  </div>
                  {holding.unrealized_gain != null && (
                    <div className={`text-xs ${holding.unrealized_gain >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {holding.unrealized_gain >= 0 ? '+' : ''}
                      {holding.unrealized_gain.toFixed(2)} ({holding.unrealized_gain_pct?.toFixed(1)}%)
                    </div>
                  )}
                </div>
                <button
                  onClick={() => startEdit(holding)}
                  className="text-xs font-medium text-slate-400 hover:text-sky-400"
                >
                  Edit
                </button>
                <button
                  onClick={() => removeMutation.mutate(holding.ticker)}
                  className="text-xs font-medium text-slate-400 hover:text-red-400"
                >
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

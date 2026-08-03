import { useState } from 'react'
import type { AnalysisWithCritiques, CoverageTier } from '../api/types'
import { ApiError } from '../api/client'
import { useAnalyze, useCritique } from '../api/hooks'
import { Skeleton } from './Skeleton'
import { VerdictBadge } from './VerdictBadge'

interface VerdictBannerProps {
  ticker: string
  coverageTier: CoverageTier
  latest: AnalysisWithCritiques | undefined
  isLoading: boolean
}

// The AI verdict banner -- deliberately the *second* thing on the wiki page (plan.md), not
// buried. "Get Second Opinion" renders its result inline below the original verdict rather
// than replacing it (plan.md): the point is showing both takes, not silently overwriting one.
export function VerdictBanner({ ticker, coverageTier, latest, isLoading }: VerdictBannerProps) {
  const analyzeMutation = useAnalyze(ticker)
  const critiqueMutation = useCritique(ticker)
  const [showAllCritiques, setShowAllCritiques] = useState(false)

  if (isLoading) {
    return <Skeleton className="h-40 w-full rounded-2xl" />
  }

  if (!latest) {
    return (
      <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-6">
        <p className="mb-3 text-sm text-slate-400">No AI analysis yet for this company.</p>
        <AnalyzeButton mutation={analyzeMutation} label="Analyze with AI" />
      </div>
    )
  }

  const critiques = showAllCritiques ? latest.critiques : latest.critiques.slice(0, 1)

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <VerdictBadge verdict={latest.verdict} size="lg" />
        <span className="text-sm text-slate-400">confidence {Math.round(latest.confidence * 100)}%</span>
        <span className="text-xs text-slate-600">
          {new Date(latest.generated_at).toLocaleString()} · {latest.trigger.replace('_', ' ')}
        </span>
      </div>

      <p className="mt-3 text-slate-200">{latest.reasoning}</p>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <PriceStat label="Buy at/below" value={latest.price_targets.buy_at_or_below} />
        <PriceStat label="Sell at/above" value={latest.price_targets.sell_at_or_above} />
        <PriceStat label="Stop loss" value={latest.price_targets.stop_loss} />
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500">Hold period</div>
          <div className="text-sm text-slate-200">
            {latest.hold_period_days.min != null && latest.hold_period_days.max != null
              ? `${latest.hold_period_days.min}–${latest.hold_period_days.max}d`
              : '—'}
          </div>
          {latest.hold_period_days.note && <div className="text-xs text-slate-500">{latest.hold_period_days.note}</div>}
        </div>
      </div>

      {latest.cited_sources.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {latest.cited_sources.map((source, i) => (
            <span key={i} className="rounded-full border border-slate-700 px-2.5 py-1 text-xs text-slate-400">
              {source.type}: {source.reference}
            </span>
          ))}
        </div>
      )}

      <div className="mt-5 flex items-center gap-3 border-t border-slate-800 pt-4">
        <AnalyzeButton mutation={analyzeMutation} label="Re-analyze" />
        {coverageTier === 'watchlist' && (
          <button
            onClick={() => critiqueMutation.mutate(latest.id)}
            disabled={critiqueMutation.isPending}
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm font-medium text-slate-300 hover:bg-slate-800 disabled:opacity-50"
          >
            {critiqueMutation.isPending ? 'Getting second opinion…' : 'Get Second Opinion'}
          </button>
        )}
        {critiqueMutation.isError && (
          <span className="text-sm text-red-400">
            {critiqueMutation.error instanceof ApiError ? critiqueMutation.error.message : 'Something went wrong.'}
          </span>
        )}
      </div>

      {critiques.length > 0 && (
        <div className="mt-4 space-y-3">
          {critiques.map((critique) => (
            <div key={critique.id} className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
              <div className="flex items-center gap-2 text-sm">
                <span className={critique.agrees_with_verdict_direction ? 'text-emerald-400' : 'text-red-400'}>
                  {critique.agrees_with_verdict_direction ? 'Agrees with direction' : 'Disagrees with direction'}
                </span>
                <span className="text-xs text-slate-600">{new Date(critique.generated_at).toLocaleString()}</span>
              </div>
              <p className="mt-2 text-sm font-medium text-slate-200">{critique.biggest_weakness}</p>
              <p className="mt-1 text-sm text-slate-400">{critique.rationale}</p>
            </div>
          ))}
          {latest.critiques.length > 1 && (
            <button
              onClick={() => setShowAllCritiques((prev) => !prev)}
              className="text-xs font-medium text-sky-400 hover:text-sky-300"
            >
              {showAllCritiques ? 'Show latest only' : `Show all ${latest.critiques.length} critiques`}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function AnalyzeButton({ mutation, label }: { mutation: ReturnType<typeof useAnalyze>; label: string }) {
  return (
    <div className="flex items-center gap-3">
      <button
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending}
        className="rounded-lg bg-sky-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-sky-400 disabled:opacity-50"
      >
        {mutation.isPending ? 'Analyzing…' : label}
      </button>
      {mutation.isError && (
        <span className="text-sm text-red-400">
          {mutation.error instanceof ApiError ? mutation.error.message : 'Something went wrong.'}
        </span>
      )}
    </div>
  )
}

function PriceStat({ label, value }: { label: string; value: number | null }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="text-sm text-slate-200">{value != null ? `$${value.toFixed(2)}` : '—'}</div>
    </div>
  )
}

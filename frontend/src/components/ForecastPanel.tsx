import type { CoverageTier, ForecastGeneration } from '../api/types'
import { ApiError } from '../api/client'
import { useForecasts, useGenerateForecast, useStatus } from '../api/hooks'
import { Skeleton } from './Skeleton'

interface ForecastPanelProps {
  ticker: string
  coverageTier: CoverageTier
}

// Multi-horizon forecast panel (Post-Phase-5 Addition #2) -- a second, independent AI model
// (Groq) projecting an expected low/high price band at 30/60/90/180/360 days.
//
// SHIPS DORMANT: while the backend has no GROQ_API_KEY, `features.forecast` is false and the
// "Generate Forecast" button renders *disabled with an explanatory tooltip* rather than hidden
// (spec.md FR-33a) -- the feature is visibly on standby, and its blocker is obvious, not a
// mystery. The panel shows an explicit "not configured" state, never a spinner or blank box.
export function ForecastPanel({ ticker, coverageTier }: ForecastPanelProps) {
  const { data: status } = useStatus()
  const { data: forecasts, isLoading } = useForecasts(ticker)
  const generateMutation = useGenerateForecast(ticker)

  const forecastEnabled = status?.features.forecast ?? false
  const isWatchlist = coverageTier === 'watchlist'
  const latest = forecasts?.latest ?? null

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-100">Multi-Horizon Forecast</h2>
          <p className="text-xs text-slate-500">
            Second AI model (Groq) · expected price band at 30 / 60 / 90 / 180 / 360 days
          </p>
        </div>

        {/* Watchlist-only, exactly like "Get Second Opinion". When Groq is dormant the button is
            disabled with a "not configured" tooltip rather than hidden -- visibly on standby. */}
        {isWatchlist && (
          <button
            onClick={() => generateMutation.mutate()}
            disabled={!forecastEnabled || generateMutation.isPending}
            title={forecastEnabled ? undefined : 'Groq API key not configured'}
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm font-medium text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {generateMutation.isPending ? 'Generating…' : 'Generate Forecast'}
          </button>
        )}
      </div>

      {generateMutation.isError && (
        <p className="mt-3 text-sm text-red-400">
          {generateMutation.error instanceof ApiError ? generateMutation.error.message : 'Something went wrong.'}
        </p>
      )}

      <div className="mt-4">
        {!forecastEnabled ? (
          <NotConfiguredState />
        ) : !isWatchlist ? (
          <p className="text-sm text-slate-500">
            Forecasts are only available for watchlist tickers. Add {ticker} to your watchlist to generate one.
          </p>
        ) : isLoading ? (
          <Skeleton className="h-40 w-full rounded-xl" />
        ) : latest ? (
          <ForecastBands generation={latest} />
        ) : (
          <p className="text-sm text-slate-500">No forecast generated yet — use “Generate Forecast” above.</p>
        )}
      </div>
    </div>
  )
}

// The explicit standby state (spec.md FR-33a) -- honest about *why* the feature is off, not an
// empty box that reads as broken.
function NotConfiguredState() {
  return (
    <div className="rounded-xl border border-dashed border-slate-800 bg-slate-950/40 p-5 text-sm">
      <p className="font-medium text-slate-300">Forecasts are on standby.</p>
      <p className="mt-1 text-slate-500">
        The second AI model (Groq) is not configured. Set a <code className="text-slate-400">GROQ_API_KEY</code> on the
        backend to enable multi-horizon price forecasts. Nothing else about the app is affected while it's off.
      </p>
    </div>
  )
}

// A single-series range display (dataviz: magnitude/range -> horizontal range bars on one
// shared price axis). One hue (the app's sky accent), direct low/high labels, confidence as a
// secondary label, recessive baseline -- no legend needed for one series.
function ForecastBands({ generation }: { generation: ForecastGeneration }) {
  const lows = generation.forecasts.map((f) => f.expected_low)
  const highs = generation.forecasts.map((f) => f.expected_high)
  const min = Math.min(...lows)
  const max = Math.max(...highs)
  const span = max - min || 1 // guard against a degenerate all-equal set

  return (
    <div>
      <div className="space-y-3">
        {generation.forecasts.map((f) => {
          const leftPct = ((f.expected_low - min) / span) * 100
          const widthPct = Math.max(((f.expected_high - f.expected_low) / span) * 100, 1.5)
          return (
            <div key={f.horizon_days} className="grid grid-cols-[3rem_1fr_4rem] items-center gap-3">
              <span className="text-xs font-medium text-slate-400">{f.horizon_days}d</span>
              <div className="relative h-6 rounded bg-slate-800/50" title={f.rationale}>
                <div
                  className="absolute top-0 flex h-6 items-center justify-between rounded bg-sky-500/70 px-1.5"
                  style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                >
                  <span className="text-[10px] font-medium text-white/90">${f.expected_low.toFixed(0)}</span>
                  <span className="text-[10px] font-medium text-white/90">${f.expected_high.toFixed(0)}</span>
                </div>
              </div>
              <span className="text-right text-xs text-slate-500">{Math.round(f.confidence * 100)}%</span>
            </div>
          )
        })}
      </div>

      <div className="mt-3 flex items-center justify-between text-[11px] text-slate-600">
        <span>${min.toFixed(2)}</span>
        <span>confidence →</span>
        <span>${max.toFixed(2)}</span>
      </div>

      <p className="mt-3 text-xs text-slate-600">
        {generation.model} · {new Date(generation.generated_at).toLocaleString()}
      </p>
    </div>
  )
}

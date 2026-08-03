import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useRemoveFromWatchlist, useWatchlist } from '../api/hooks'
import { FreshnessIndicator } from '../components/FreshnessIndicator'
import { Skeleton } from '../components/Skeleton'
import { VerdictBadge } from '../components/VerdictBadge'

const ALL_CATEGORIES = 'All'

// Static grid only (FR-21, T5.3) -- portfolio allocation donut and recent-verdict-change feed
// from plan.md's dashboard design are chart-driven and land in Phase 6.
export function DashboardPage() {
  const { data: watchlist, isLoading, isFetching } = useWatchlist()
  const removeMutation = useRemoveFromWatchlist()
  const [activeCategory, setActiveCategory] = useState(ALL_CATEGORIES)

  const categories = useMemo(() => {
    if (!watchlist) return []
    return Array.from(new Set(watchlist.map((entry) => entry.category))).sort()
  }, [watchlist])

  const visibleEntries = useMemo(() => {
    if (!watchlist) return []
    if (activeCategory === ALL_CATEGORIES) return watchlist
    return watchlist.filter((entry) => entry.category === activeCategory)
  }, [watchlist, activeCategory])

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-100">Watchlist</h1>
        <Link to="/search" className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-400">
          + Add ticker
        </Link>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : !watchlist || watchlist.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-800 p-12 text-center">
          <p className="text-slate-400">Nothing on your watchlist yet.</p>
          <Link to="/search" className="mt-3 inline-block text-sm font-medium text-sky-400 hover:text-sky-300">
            Search for a company to add one →
          </Link>
        </div>
      ) : (
        <>
          {categories.length > 1 && (
            <div className="mb-5 flex flex-wrap gap-2">
              {[ALL_CATEGORIES, ...categories].map((category) => (
                <button
                  key={category}
                  onClick={() => setActiveCategory(category)}
                  className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                    activeCategory === category
                      ? 'bg-sky-500 text-white'
                      : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                  }`}
                >
                  {category}
                </button>
              ))}
            </div>
          )}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {visibleEntries.map((entry) => (
              <div key={entry.ticker} className="group relative rounded-2xl border border-slate-800 bg-slate-900/40 p-5">
                <button
                  onClick={(event) => {
                    event.preventDefault()
                    removeMutation.mutate(entry.ticker)
                  }}
                  title="Remove from watchlist"
                  className="absolute right-3 top-3 text-slate-600 opacity-0 transition-opacity hover:text-red-400 group-hover:opacity-100"
                >
                  ✕
                </button>
                <Link to={`/company/${entry.ticker}`} className="block">
                  <div className="flex items-start justify-between pr-6">
                    <div>
                      <div className="text-lg font-semibold text-slate-100">{entry.ticker}</div>
                      <div className="truncate text-sm text-slate-400">{entry.name ?? 'Unknown company'}</div>
                      <div className="mt-1 text-xs text-slate-500">{entry.category}</div>
                    </div>
                    {entry.latest_verdict && <VerdictBadge verdict={entry.latest_verdict.verdict} size="sm" />}
                  </div>
                  <div className="mt-4 flex items-end justify-between">
                    <div className="text-xl font-semibold text-slate-100">
                      {entry.latest_price?.close != null ? `$${entry.latest_price.close.toFixed(2)}` : '—'}
                    </div>
                    <FreshnessIndicator lastUpdated={entry.last_updated} isFetching={isFetching} />
                  </div>
                </Link>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

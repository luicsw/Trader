import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useSearch } from '../api/hooks'
import { Skeleton } from '../components/Skeleton'

// Debounced so search-as-you-type doesn't spend Finnhub's shared rate-limit budget on every
// keystroke -- the backend has no per-endpoint budget carve-out for search specifically.
const DEBOUNCE_MS = 350

export function SearchPage() {
  const [input, setInput] = useState('')
  const [debounced, setDebounced] = useState('')

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(input), DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [input])

  const { data: results, isLoading, isFetching } = useSearch(debounced)

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <h1 className="mb-4 text-2xl font-semibold text-slate-100">Search</h1>
      <input
        autoFocus
        value={input}
        onChange={(event) => setInput(event.target.value)}
        placeholder="Search any company by name or ticker…"
        className="w-full rounded-lg border border-slate-700 bg-slate-950 px-4 py-3 text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none"
      />

      <div className="mt-4 space-y-2">
        {debounced.trim().length === 0 ? (
          <p className="text-sm text-slate-500">
            Look up any company on demand — it doesn't need to be on your watchlist to view it.
          </p>
        ) : isLoading || (isFetching && !results) ? (
          Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-14" />)
        ) : !results || results.length === 0 ? (
          <p className="text-sm text-slate-500">No matches for “{debounced}”.</p>
        ) : (
          results.map((result) => (
            <Link
              key={result.symbol}
              to={`/company/${result.symbol}`}
              className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3 hover:border-slate-700 hover:bg-slate-900"
            >
              <div>
                <div className="font-medium text-slate-100">{result.symbol}</div>
                <div className="text-sm text-slate-400">{result.name ?? 'Unknown'}</div>
              </div>
              {result.type && <span className="text-xs text-slate-600">{result.type}</span>}
            </Link>
          ))
        )}
      </div>
    </div>
  )
}

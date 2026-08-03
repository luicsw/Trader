// FR-24: "Live" / "Updated Xm ago" / "Stale", derived from last_updated + query state --
// staleness thresholds loosely mirror the backend's own lookup_stale_after_minutes (60min)
// so the indicator agrees with when the backend would actually refetch.
interface FreshnessIndicatorProps {
  lastUpdated: string | null
  isFetching?: boolean
}

export function FreshnessIndicator({ lastUpdated, isFetching }: FreshnessIndicatorProps) {
  if (isFetching) {
    return <Dot label="Refreshing…" colorClass="text-sky-400" pulse />
  }
  if (!lastUpdated) {
    return <Dot label="No data yet" colorClass="text-slate-500" />
  }

  const minutesAgo = Math.max(0, Math.round((Date.now() - new Date(lastUpdated).getTime()) / 60_000))

  if (minutesAgo < 1) return <Dot label="Live" colorClass="text-emerald-400" />
  if (minutesAgo < 60) return <Dot label={`Updated ${minutesAgo}m ago`} colorClass="text-slate-400" />
  if (minutesAgo < 24 * 60) return <Dot label={`Updated ${Math.round(minutesAgo / 60)}h ago`} colorClass="text-amber-400" />
  return <Dot label="Stale" colorClass="text-red-400" />
}

function Dot({ label, colorClass, pulse }: { label: string; colorClass: string; pulse?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${colorClass}`}>
      <span className={`h-1.5 w-1.5 rounded-full bg-current ${pulse ? 'animate-pulse' : ''}`} />
      {label}
    </span>
  )
}

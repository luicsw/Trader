import type { Verdict } from '../api/types'

const STYLES: Record<Verdict, string> = {
  buy: 'bg-emerald-500/15 text-emerald-400 ring-emerald-500/30',
  hold: 'bg-amber-500/15 text-amber-400 ring-amber-500/30',
  sell: 'bg-red-500/15 text-red-400 ring-red-500/30',
}

export function VerdictBadge({ verdict, size = 'md' }: { verdict: Verdict; size?: 'sm' | 'md' | 'lg' }) {
  const sizeClass = size === 'lg' ? 'px-4 py-1.5 text-base' : size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm'
  return (
    <span
      className={`inline-flex items-center rounded-full font-semibold uppercase tracking-wide ring-1 ${STYLES[verdict]} ${sizeClass}`}
    >
      {verdict}
    </span>
  )
}

import { useEffect, useRef, useState } from 'react'
import { useTickerSearch } from '../api/hooks'

// Add Holding type-ahead (spec.md FR-34/FR-35). Backed by the local /tickers/search endpoint
// (reads the cached ticker_directory, zero live provider calls, so it's safe on every
// keystroke) -- but never a hard gate: whatever the user types IS the value, so a symbol
// absent from the directory (newly listed, OTC) can still be entered manually and submitted.
const DEBOUNCE_MS = 200

interface Props {
  value: string
  onChange: (symbol: string) => void
  className?: string
}

export function TickerCombobox({ value, onChange, className }: Props) {
  const [open, setOpen] = useState(false)
  const [debounced, setDebounced] = useState(value)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [value])

  const { data: suggestions } = useTickerSearch(debounced)

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const showDropdown = open && !!suggestions && suggestions.length > 0

  return (
    <div ref={containerRef} className={`relative ${className ?? ''}`}>
      <input
        value={value}
        onChange={(event) => {
          onChange(event.target.value.toUpperCase())
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        placeholder="Ticker"
        className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none"
      />
      {showDropdown && (
        <ul className="absolute z-20 mt-1 max-h-60 w-full overflow-auto rounded-lg border border-slate-700 bg-slate-900 shadow-lg">
          {suggestions.map((suggestion) => (
            <li key={suggestion.symbol}>
              <button
                type="button"
                onClick={() => {
                  onChange(suggestion.symbol)
                  setOpen(false)
                }}
                className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-slate-800"
              >
                <span className="font-medium text-slate-100">{suggestion.symbol}</span>
                <span className="truncate text-xs text-slate-400">{suggestion.name ?? ''}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

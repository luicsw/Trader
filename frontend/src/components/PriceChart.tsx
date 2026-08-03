import { useEffect, useRef, useState } from 'react'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts'
import { api } from '../api/client'
import { usePriceHistory } from '../api/hooks'
import type { PriceBar } from '../api/types'
import { Skeleton } from './Skeleton'

// Near-live chart (Post-Phase-5 addition). Finnhub's free tier has no intraday candle
// endpoint (confirmed live), so this shows real daily bars for history plus a live-polled
// bar for "right now" -- polling only happens while this component is mounted (i.e. while
// the company page is actually open), not in the background, to stay within free-tier quote
// call budgets.
const POLL_INTERVAL_MS = 20_000

function toCandle(bar: PriceBar) {
  const close = bar.close ?? 0
  return {
    time: (new Date(bar.ts).getTime() / 1000) as UTCTimestamp,
    open: bar.open ?? close,
    high: bar.high ?? close,
    low: bar.low ?? close,
    close,
  }
}

export function PriceChart({ ticker }: { ticker: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const { data: history, isLoading } = usePriceHistory(ticker, '1d', 180)
  const [liveUnavailable, setLiveUnavailable] = useState(false)

  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
      height: 320,
      timeScale: { timeVisible: true, secondsVisible: false },
    })
    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#34d399',
      downColor: '#f87171',
      borderVisible: false,
      wickUpColor: '#34d399',
      wickDownColor: '#f87171',
    })
    chartRef.current = chart
    seriesRef.current = series

    const resizeObserver = new ResizeObserver((entries) => {
      const { width } = entries[0].contentRect
      chart.applyOptions({ width })
    })
    resizeObserver.observe(containerRef.current)

    return () => {
      resizeObserver.disconnect()
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!seriesRef.current || !history) return
    seriesRef.current.setData(history.filter((bar) => bar.close != null).map(toCandle))
    chartRef.current?.timeScale().fitContent()
  }, [history])

  useEffect(() => {
    if (ticker.length === 0) return
    let cancelled = false

    async function poll() {
      try {
        const bar = await api.pollLiveQuote(ticker)
        if (cancelled) return
        setLiveUnavailable(false)
        seriesRef.current?.update(toCandle(bar))
      } catch {
        if (!cancelled) setLiveUnavailable(true)
      }
    }

    poll()
    const interval = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [ticker])

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-6">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-100">Price Chart</h2>
        {liveUnavailable && <span className="text-xs text-slate-500">Live price temporarily unavailable</span>}
      </div>
      {isLoading ? <Skeleton className="h-80" /> : <div ref={containerRef} className="h-80 w-full" />}
    </div>
  )
}

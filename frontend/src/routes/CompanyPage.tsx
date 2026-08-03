import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAnalyses, usePromote, useRemoveFromWatchlist, useWiki } from '../api/hooks'
import type { Holding, WikiSectionKey } from '../api/types'
import { FreshnessIndicator } from '../components/FreshnessIndicator'
import { PriceChart } from '../components/PriceChart'
import { Skeleton } from '../components/Skeleton'
import { VerdictBadge } from '../components/VerdictBadge'
import { VerdictBanner } from '../components/VerdictBanner'

const SECTION_TITLES: Record<WikiSectionKey, string> = {
  overview: 'Overview',
  key_metrics: 'Key Metrics',
  financials_summary: 'Financials',
  news_digest: 'News Digest',
  risks_notes: 'Risks / Notes',
}

// Company wiki page (FR-22) -- infobox → AI verdict banner → price chart → your position →
// overview → key metrics → financials → recent news → AI analysis history → risks/notes.
//
// FR-23 ("each section fetches independently") maps onto the backend's actual endpoint
// granularity: wiki data (overview/key_metrics/financials/risks, all assembled server-side
// in one call) is one query, AI analyses history is a separate query -- so a slow AI history
// fetch never blocks the wiki sections from rendering, and vice versa.
export function CompanyPage() {
  const { ticker = '' } = useParams<{ ticker: string }>()
  const { data: wiki, isLoading: wikiLoading, isFetching: wikiFetching } = useWiki(ticker)
  const { data: analyses, isLoading: analysesLoading } = useAnalyses(ticker)
  const promoteMutation = usePromote()
  const removeMutation = useRemoveFromWatchlist()
  const [showFullHistory, setShowFullHistory] = useState(false)

  if (wikiLoading) {
    return (
      <div className="mx-auto max-w-4xl space-y-4 px-4 py-8">
        <Skeleton className="h-24" />
        <Skeleton className="h-40" />
        <Skeleton className="h-64" />
      </div>
    )
  }

  if (!wiki) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-16 text-center text-slate-400">
        Couldn't load {ticker} -- it may not be a real ticker, or a provider is temporarily unavailable.
      </div>
    )
  }

  const latestAnalysis = analyses?.[0]
  const history = showFullHistory ? analyses : analyses?.slice(0, 3)

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-8">
      {/* Infobox header */}
      <div className="flex flex-wrap items-start justify-between gap-4 rounded-2xl border border-slate-800 bg-slate-900/40 p-6">
        <div className="flex items-start gap-4">
          {wiki.logo_url && <img src={wiki.logo_url} alt="" className="h-12 w-12 rounded-lg bg-white/5 object-contain" />}
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-semibold text-slate-100">{wiki.ticker}</h1>
              {wiki.coverage_tier === 'watchlist' && (
                <span className="rounded-full bg-sky-500/15 px-2 py-0.5 text-xs font-medium text-sky-400">Watchlist</span>
              )}
            </div>
            <p className="text-slate-400">{wiki.name ?? 'Unknown company'}</p>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
              {wiki.exchange && <span>{wiki.exchange}</span>}
              {wiki.sector && <span>· {wiki.sector}</span>}
              <span className="rounded-full bg-slate-800 px-2 py-0.5 font-medium text-slate-300">{wiki.category}</span>
            </div>
          </div>
        </div>

        <div className="flex flex-col items-end gap-2">
          <div className="text-2xl font-semibold text-slate-100">
            {wiki.latest_price?.close != null ? `$${wiki.latest_price.close.toFixed(2)}` : '—'}
          </div>
          <FreshnessIndicator lastUpdated={wiki.last_updated} isFetching={wikiFetching} />
          <ActionButton
            isWatchlisted={wiki.coverage_tier === 'watchlist'}
            onPromote={() => promoteMutation.mutate(ticker)}
            onRemove={() => removeMutation.mutate(ticker)}
            isPending={promoteMutation.isPending || removeMutation.isPending}
          />
        </div>
      </div>

      <VerdictBanner
        ticker={wiki.ticker}
        coverageTier={wiki.coverage_tier}
        latest={latestAnalysis}
        isLoading={analysesLoading}
      />

      <PriceChart ticker={wiki.ticker} />

      <PositionPanel holding={wiki.holding} ticker={wiki.ticker} />

      <Section title={SECTION_TITLES.overview} section={wiki.sections.overview} />
      <Section title={SECTION_TITLES.key_metrics} section={wiki.sections.key_metrics} />
      <Section title={SECTION_TITLES.financials_summary} section={wiki.sections.financials_summary} />

      <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-6">
        <h2 className="mb-3 text-lg font-semibold text-slate-100">Recent News</h2>
        {wiki.recent_news.length === 0 ? (
          <p className="text-sm text-slate-500">No news has been ingested for this company yet.</p>
        ) : (
          <ul className="space-y-3">
            {wiki.recent_news.map((article) => (
              <li key={article.url} className="border-b border-slate-800 pb-3 last:border-0 last:pb-0">
                <a href={article.url} target="_blank" rel="noreferrer" className="font-medium text-slate-200 hover:text-sky-400">
                  {article.headline}
                </a>
                <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
                  {article.source && <span>{article.source}</span>}
                  {article.published_at && <span>· {new Date(article.published_at).toLocaleDateString()}</span>}
                  {article.sentiment && <SentimentTag sentiment={article.sentiment} />}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-6">
        <h2 className="mb-3 text-lg font-semibold text-slate-100">AI Analysis History</h2>
        {analysesLoading ? (
          <Skeleton className="h-24" />
        ) : !history || history.length === 0 ? (
          <p className="text-sm text-slate-500">No analyses yet.</p>
        ) : (
          <>
            <ul className="space-y-3">
              {history.map((analysis) => (
                <li key={analysis.id} className="flex items-center justify-between gap-3 border-b border-slate-800 pb-3 last:border-0 last:pb-0">
                  <div className="flex items-center gap-3">
                    <VerdictBadge verdict={analysis.verdict} size="sm" />
                    <span className="text-sm text-slate-400">{Math.round(analysis.confidence * 100)}% confidence</span>
                  </div>
                  <span className="text-xs text-slate-600">{new Date(analysis.generated_at).toLocaleString()}</span>
                </li>
              ))}
            </ul>
            {analyses && analyses.length > 3 && (
              <button
                onClick={() => setShowFullHistory((prev) => !prev)}
                className="mt-3 text-xs font-medium text-sky-400 hover:text-sky-300"
              >
                {showFullHistory ? 'Show less' : `Show all ${analyses.length} analyses`}
              </button>
            )}
          </>
        )}
      </div>

      <Section title={SECTION_TITLES.risks_notes} section={wiki.sections.risks_notes} />
    </div>
  )
}

function PositionPanel({ holding, ticker }: { holding: Holding | null; ticker: string }) {
  if (holding === null) {
    return (
      <div className="flex items-center justify-between rounded-2xl border border-dashed border-slate-800 p-4 text-sm">
        <span className="text-slate-500">You don't hold a position in {ticker}.</span>
        <Link to="/portfolio" className="font-medium text-sky-400 hover:text-sky-300">
          + Add position
        </Link>
      </div>
    )
  }

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Your Position</h2>
        <Link to="/portfolio" className="text-xs font-medium text-sky-400 hover:text-sky-300">
          Edit
        </Link>
      </div>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="text-sm text-slate-300">
          {holding.shares} shares @ ${holding.cost_basis_per_share.toFixed(2)} cost basis
          {holding.notes && <div className="mt-1 text-xs text-slate-500">{holding.notes}</div>}
        </div>
        {holding.unrealized_gain != null && (
          <div className="text-right">
            <div className={`text-lg font-semibold ${holding.unrealized_gain >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {holding.unrealized_gain >= 0 ? '+' : ''}
              ${holding.unrealized_gain.toFixed(2)}
            </div>
            <div className="text-xs text-slate-500">{holding.unrealized_gain_pct?.toFixed(1)}%</div>
          </div>
        )}
      </div>
    </div>
  )
}

function Section({ title, section }: { title: string; section?: { body: string; generated_at: string } }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-6">
      <h2 className="mb-3 text-lg font-semibold text-slate-100">{title}</h2>
      <p className="whitespace-pre-line text-sm text-slate-300">{section?.body ?? 'Not available yet.'}</p>
    </div>
  )
}

function SentimentTag({ sentiment }: { sentiment: 'positive' | 'neutral' | 'negative' }) {
  const colorClass =
    sentiment === 'positive' ? 'text-emerald-400' : sentiment === 'negative' ? 'text-red-400' : 'text-slate-500'
  return <span className={colorClass}>· {sentiment}</span>
}

function ActionButton({
  isWatchlisted,
  onPromote,
  onRemove,
  isPending,
}: {
  isWatchlisted: boolean
  onPromote: () => void
  onRemove: () => void
  isPending: boolean
}) {
  if (isWatchlisted) {
    return (
      <button
        onClick={onRemove}
        disabled={isPending}
        className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm font-medium text-slate-300 hover:bg-slate-800 disabled:opacity-50"
      >
        Remove from Watchlist
      </button>
    )
  }
  return (
    <button
      onClick={onPromote}
      disabled={isPending}
      className="rounded-lg bg-sky-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-sky-400 disabled:opacity-50"
    >
      {isPending ? 'Adding…' : '+ Add to Watchlist'}
    </button>
  )
}

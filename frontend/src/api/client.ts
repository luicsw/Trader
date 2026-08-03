import { getStoredCredential } from '../auth/AuthContext'
import type {
  Analysis,
  AnalysisWithCritiques,
  ApiErrorBody,
  ChatMessage,
  Critique,
  Holding,
  PriceBar,
  PromoteResult,
  SearchResult,
  Wiki,
  WatchlistSummary,
} from './types'

export interface HoldingInput {
  shares: number
  cost_basis_per_share: number
  acquired_at?: string | null
  notes?: string | null
}

export class ApiError extends Error {
  status: number
  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
  }
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const credential = getStoredCredential()
  const headers = new Headers(options?.headers)
  headers.set('Content-Type', 'application/json')
  if (credential) headers.set('Authorization', `Bearer ${credential}`)

  const response = await fetch(`/api${path}`, { ...options, headers })

  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = (await response.json()) as ApiErrorBody
      if (body?.detail) detail = body.detail
    } catch {
      // non-JSON error body -- keep statusText
    }
    throw new ApiError(response.status, detail)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  getWiki: (ticker: string) => apiFetch<Wiki>(`/companies/${encodeURIComponent(ticker)}/wiki`),

  getWatchlist: () => apiFetch<WatchlistSummary[]>('/watchlist'),

  search: (query: string) => apiFetch<SearchResult[]>(`/companies/search?q=${encodeURIComponent(query)}`),

  promote: (ticker: string) =>
    apiFetch<PromoteResult>(`/watchlist/${encodeURIComponent(ticker)}/promote`, { method: 'POST' }),

  removeFromWatchlist: (ticker: string) =>
    apiFetch<{ ticker: string; removed: boolean }>(`/watchlist/${encodeURIComponent(ticker)}`, {
      method: 'DELETE',
    }),

  analyze: (ticker: string) =>
    apiFetch<Analysis>(`/companies/${encodeURIComponent(ticker)}/analyze`, { method: 'POST' }),

  critique: (ticker: string, analysisId: number) =>
    apiFetch<Critique>(`/companies/${encodeURIComponent(ticker)}/critique?analysis_id=${analysisId}`, {
      method: 'POST',
    }),

  getAnalyses: (ticker: string) =>
    apiFetch<AnalysisWithCritiques[]>(`/companies/${encodeURIComponent(ticker)}/analyses`),

  getHoldings: () => apiFetch<Holding[]>('/holdings'),

  upsertHolding: (ticker: string, input: HoldingInput) =>
    apiFetch<Holding>(`/holdings/${encodeURIComponent(ticker)}`, {
      method: 'POST',
      body: JSON.stringify(input),
    }),

  removeHolding: (ticker: string) =>
    apiFetch<{ ticker: string; removed: boolean }>(`/holdings/${encodeURIComponent(ticker)}`, {
      method: 'DELETE',
    }),

  getPriceHistory: (ticker: string, interval: string, limit: number) =>
    apiFetch<PriceBar[]>(
      `/companies/${encodeURIComponent(ticker)}/price-history?interval=${interval}&limit=${limit}`,
    ),

  pollLiveQuote: (ticker: string) =>
    apiFetch<PriceBar>(`/companies/${encodeURIComponent(ticker)}/live-quote`, { method: 'POST' }),

  getChatMessages: () => apiFetch<ChatMessage[]>('/chat/messages'),

  sendChatMessage: (message: string) =>
    apiFetch<ChatMessage>('/chat', { method: 'POST', body: JSON.stringify({ message }) }),
}

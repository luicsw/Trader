import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { HoldingInput } from './client'

// One query key per resource (FR-23) so each wiki-page section loads/caches independently --
// a slow section (e.g. news) never blocks a fast one (e.g. overview) from rendering.
export const queryKeys = {
  wiki: (ticker: string) => ['wiki', ticker.toUpperCase()] as const,
  watchlist: () => ['watchlist'] as const,
  search: (query: string) => ['search', query] as const,
  analyses: (ticker: string) => ['analyses', ticker.toUpperCase()] as const,
  holdings: () => ['holdings'] as const,
  priceHistory: (ticker: string, interval: string) => ['price-history', ticker.toUpperCase(), interval] as const,
  chatMessages: () => ['chat-messages'] as const,
}

export function useWiki(ticker: string) {
  return useQuery({
    queryKey: queryKeys.wiki(ticker),
    queryFn: () => api.getWiki(ticker),
    enabled: ticker.length > 0,
  })
}

export function useWatchlist() {
  return useQuery({ queryKey: queryKeys.watchlist(), queryFn: api.getWatchlist })
}

export function useSearch(query: string) {
  return useQuery({
    queryKey: queryKeys.search(query),
    queryFn: () => api.search(query),
    enabled: query.trim().length > 0,
  })
}

export function useAnalyses(ticker: string) {
  return useQuery({
    queryKey: queryKeys.analyses(ticker),
    queryFn: () => api.getAnalyses(ticker),
    enabled: ticker.length > 0,
  })
}

export function usePromote() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ticker: string) => api.promote(ticker),
    onSuccess: (_data, ticker) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.watchlist() })
      queryClient.invalidateQueries({ queryKey: queryKeys.wiki(ticker) })
    },
  })
}

export function useRemoveFromWatchlist() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ticker: string) => api.removeFromWatchlist(ticker),
    onSuccess: (_data, ticker) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.watchlist() })
      queryClient.invalidateQueries({ queryKey: queryKeys.wiki(ticker) })
    },
  })
}

export function useAnalyze(ticker: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.analyze(ticker),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.analyses(ticker) })
      queryClient.invalidateQueries({ queryKey: queryKeys.watchlist() })
    },
  })
}

export function useCritique(ticker: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (analysisId: number) => api.critique(ticker, analysisId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.analyses(ticker) })
    },
  })
}

export function usePriceHistory(ticker: string, interval = '1d', limit = 180) {
  return useQuery({
    queryKey: queryKeys.priceHistory(ticker, interval),
    queryFn: () => api.getPriceHistory(ticker, interval, limit),
    enabled: ticker.length > 0,
  })
}

export function useHoldings() {
  return useQuery({ queryKey: queryKeys.holdings(), queryFn: api.getHoldings })
}

export function useUpsertHolding() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ ticker, input }: { ticker: string; input: HoldingInput }) => api.upsertHolding(ticker, input),
    onSuccess: (_data, { ticker }) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.holdings() })
      queryClient.invalidateQueries({ queryKey: queryKeys.watchlist() })
      queryClient.invalidateQueries({ queryKey: queryKeys.wiki(ticker) })
    },
  })
}

export function useRemoveHolding() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ticker: string) => api.removeHolding(ticker),
    onSuccess: (_data, ticker) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.holdings() })
      queryClient.invalidateQueries({ queryKey: queryKeys.wiki(ticker) })
    },
  })
}

export function useChatMessages() {
  return useQuery({ queryKey: queryKeys.chatMessages(), queryFn: api.getChatMessages })
}

export function useSendChatMessage() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (message: string) => api.sendChatMessage(message),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.chatMessages() })
    },
  })
}

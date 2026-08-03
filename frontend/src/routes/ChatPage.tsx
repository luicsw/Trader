import { useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import { useChatMessages, useSendChatMessage } from '../api/hooks'
import { Skeleton } from '../components/Skeleton'

// Grounded AI chat (Post-Phase-5 addition, per the user's explicit decision): the assistant
// only ever discusses companies already tracked in this app (watchlist/holdings/lookups),
// never a live market-wide scan -- see prompts/chat_prompt_v1.md for the full grounding
// contract. Linear, single-user history -- no multi-conversation concept.
export function ChatPage() {
  const { data: messages, isLoading } = useChatMessages()
  const sendMutation = useSendChatMessage()
  const [input, setInput] = useState('')
  const [pendingMessage, setPendingMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, pendingMessage])

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    const trimmed = input.trim()
    if (!trimmed || sendMutation.isPending) return

    setError(null)
    setPendingMessage(trimmed)
    setInput('')

    sendMutation.mutate(trimmed, {
      onSuccess: () => setPendingMessage(null),
      onError: (err) => {
        setPendingMessage(null)
        setInput(trimmed)
        setError(err instanceof ApiError ? err.message : 'Failed to send message.')
      },
    })
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-1px)] max-w-3xl flex-col px-4 py-8 md:h-screen">
      <h1 className="mb-4 text-2xl font-semibold text-slate-100">Chat</h1>
      <p className="mb-4 text-sm text-slate-500">
        Ask about companies you're already tracking (watchlist, holdings, or anything you've looked up) — the AI
        only reasons over that data, not the broader market.
      </p>

      <div className="flex-1 space-y-3 overflow-y-auto pb-4">
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-14" />
            ))}
          </div>
        ) : !messages || messages.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-800 p-8 text-center text-sm text-slate-500">
            No messages yet — ask something like "what's the best tech stock I'm tracking?"
          </div>
        ) : (
          messages.map((message) => <ChatBubble key={message.id} role={message.role} content={message.content} />)
        )}
        {pendingMessage && <ChatBubble role="user" content={pendingMessage} />}
        {sendMutation.isPending && (
          <div className="flex justify-start">
            <div className="rounded-2xl bg-slate-800 px-4 py-2 text-sm text-slate-400">Thinking…</div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {error && <p className="mb-2 text-sm text-red-400">{error}</p>}

      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Ask about a company you're tracking…"
          className="flex-1 rounded-lg border border-slate-700 bg-slate-950 px-4 py-3 text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none"
        />
        <button
          type="submit"
          disabled={sendMutation.isPending || input.trim().length === 0}
          className="rounded-lg bg-sky-500 px-4 py-3 text-sm font-semibold text-white hover:bg-sky-400 disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </div>
  )
}

function ChatBubble({ role, content }: { role: 'user' | 'assistant'; content: string }) {
  const isUser = role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] whitespace-pre-line rounded-2xl px-4 py-2 text-sm ${
          isUser ? 'bg-sky-500 text-white' : 'bg-slate-800 text-slate-200'
        }`}
      >
        {content}
      </div>
    </div>
  )
}

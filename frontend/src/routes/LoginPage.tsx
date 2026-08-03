import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export function LoginPage() {
  const { credential, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [value, setValue] = useState('')

  if (credential) {
    const redirectTo = (location.state as { from?: string } | null)?.from ?? '/'
    return <Navigate to={redirectTo} replace />
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!value.trim()) return
    login(value.trim())
    navigate('/', { replace: true })
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4 rounded-2xl border border-slate-800 bg-slate-900/50 p-8">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Personal Investment Research</h1>
          <p className="mt-1 text-sm text-slate-400">Enter your shared access credential to continue.</p>
        </div>
        <input
          type="password"
          autoFocus
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Access credential"
          className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none"
        />
        <button
          type="submit"
          className="w-full rounded-lg bg-sky-500 px-3 py-2 text-sm font-semibold text-white hover:bg-sky-400"
        >
          Continue
        </button>
      </form>
    </div>
  )
}

import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

// Shared bearer credential, stored client-side (spec.md T5.2). The backend doesn't enforce
// it yet -- that's deferred to Phase 8 deploy, per spec.md's task breakdown -- but every
// request already sends it (see api/client.ts), so nothing on the frontend needs to change
// once enforcement lands.
const STORAGE_KEY = 'trader_credential'

interface AuthContextValue {
  credential: string | null
  login: (credential: string) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function getStoredCredential(): string | null {
  return localStorage.getItem(STORAGE_KEY)
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [credential, setCredential] = useState<string | null>(() => getStoredCredential())

  const login = useCallback((value: string) => {
    localStorage.setItem(STORAGE_KEY, value)
    setCredential(value)
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY)
    setCredential(null)
  }, [])

  return <AuthContext.Provider value={{ credential, login, logout }}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { credential } = useAuth()
  if (!credential) return <Navigate to="/login" replace />
  return <>{children}</>
}

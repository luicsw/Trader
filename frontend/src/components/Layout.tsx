import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

// Nav rail (desktop) / bottom tab bar (mobile), per plan.md's frontend design. Full PWA/mobile
// polish (touch target sizing audit, install prompt, etc.) is Phase 7 -- this is a functional
// responsive shell, not the final visual pass.
const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: '⌂' },
  { to: '/search', label: 'Search', icon: '⌕' },
]

export function Layout() {
  const { logout } = useAuth()

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <nav className="hidden w-56 shrink-0 flex-col border-r border-slate-800 bg-slate-950/80 p-4 md:flex">
        <span className="mb-6 px-2 text-lg font-semibold text-slate-100">Trader</span>
        <div className="flex flex-1 flex-col gap-1">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  isActive ? 'bg-slate-800 text-slate-100' : 'text-slate-400 hover:bg-slate-900 hover:text-slate-200'
                }`
              }
            >
              <span aria-hidden>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </div>
        <button
          onClick={logout}
          className="rounded-lg px-3 py-2 text-left text-sm font-medium text-slate-500 hover:bg-slate-900 hover:text-slate-300"
        >
          Log out
        </button>
      </nav>

      <main className="flex-1 pb-20 md:pb-0">
        <Outlet />
      </main>

      <nav className="fixed inset-x-0 bottom-0 flex border-t border-slate-800 bg-slate-950/95 backdrop-blur md:hidden">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              `flex flex-1 flex-col items-center gap-0.5 py-3 text-xs font-medium ${
                isActive ? 'text-slate-100' : 'text-slate-500'
              }`
            }
          >
            <span className="text-lg" aria-hidden>
              {item.icon}
            </span>
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}

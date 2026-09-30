import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api, Summary, WellRow } from './lib/api'
import { Icon, ModeToggle, Spinner } from './components/common'
import { UiModeProvider } from './lib/uiMode'
import ImpactPage from './pages/ImpactPage'
import MapPage from './pages/MapPage'
import CorrelationPage from './pages/CorrelationPage'
import KnowledgePage from './pages/KnowledgePage'
import LivePage from './pages/LivePage'
import DocumentsPage from './pages/DocumentsPage'
import ReviewPage from './pages/ReviewPage'
import StartPage from './pages/StartPage'
import RigPage from './pages/RigPage'

export type PageId = 'start' | 'impact' | 'map' | 'correlation' | 'knowledge' | 'live' | 'rig' | 'documents' | 'review'

interface Ctx {
  wells: WellRow[]
  summary: Summary | null
  selectedId: number | null
  setSelectedId: (id: number) => void
  radius: number
  setRadius: (r: number) => void
  go: (p: PageId) => void
  refresh: () => Promise<void>
  activeWell: WellRow | undefined
}
const AppCtx = createContext<Ctx>(null as unknown as Ctx)
export const useApp = () => useContext(AppCtx)

const NAV: { id: PageId; label: string; icon: string }[] = [
  { id: 'start', label: 'Start', icon: 'layers' },
  { id: 'impact', label: 'Why it matters', icon: 'alert' },
  { id: 'map', label: 'Nearby wells', icon: 'map' },
  { id: 'correlation', label: 'Correlation', icon: 'layers' },
  { id: 'knowledge', label: 'Knowledge base', icon: 'search' },
  { id: 'live', label: 'Live monitor', icon: 'activity' },
  { id: 'rig', label: 'Rig view', icon: 'alert' },
  { id: 'documents', label: 'Documents & model', icon: 'file' },
  { id: 'review', label: 'Review queue', icon: 'check' },
]

const TITLES: Record<PageId, string> = {
  start: 'eRTMAC-NWIS · Nearby Wells Intelligence',
  impact: 'What this solves, measured on the fleet',
  map: 'Wells near the one being drilled',
  correlation: 'Compare this well with the wells around it',
  knowledge: 'Search past drilling problems and what worked',
  live: 'Live monitor: warnings from nearby wells while drilling',
  rig: 'Rig floor: what to watch next, at a glance',
  documents: 'Upload a report and see what the system finds',
  review: 'Engineer review: confirm or reject uncertain extractions',
}

export default function App() {
  const initial = (location.hash.replace('#', '') as PageId) || 'start'
  const [page, setPage] = useState<PageId>(NAV.some((n) => n.id === initial) ? initial : 'start')
  const [wells, setWells] = useState<WellRow[]>([])
  const [summary, setSummary] = useState<Summary | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [radius, setRadius] = useState(6)
  const [loadErr, setLoadErr] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  const refresh = useCallback(async () => {
    try {
      // A sleeping backend can hold the request open for a minute; give up after 15 s so the retry loop kicks in.
      const timeout = new Promise<never>((_, rej) => setTimeout(() => rej(new Error('server is still starting')), 15000))
      const [w, s] = await Promise.race([Promise.all([api.wells(), api.summary()]), timeout])
      setWells(w)
      setSummary(s)
      setLoadErr(null)
      setAttempt(0)
      setSelectedId((cur) => cur ?? w.find((x) => x.status === 'ACTIVE')?.id ?? w[0]?.id ?? null)
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : String(e))
      setAttempt((n) => n + 1)
    }
  }, [])
  useEffect(() => { refresh() }, [refresh])
  // The free-tier backend sleeps when idle; keep retrying until it wakes instead of showing an error.
  useEffect(() => {
    if (!loadErr || wells.length > 0) return
    const t = setTimeout(refresh, 4000)
    return () => clearTimeout(t)
  }, [loadErr, attempt, wells.length, refresh])

  const go = useCallback((p: PageId) => { setPage(p); location.hash = p }, [])
  useEffect(() => {
    const h = () => { const p = location.hash.replace('#', '') as PageId; if (NAV.some((n) => n.id === p)) setPage(p) }
    window.addEventListener('hashchange', h)
    return () => window.removeEventListener('hashchange', h)
  }, [])

  const activeWell = wells.find((w) => w.status === 'ACTIVE')
  const ctx = useMemo<Ctx>(() => ({ wells, summary, selectedId, setSelectedId, radius, setRadius, go, refresh, activeWell }), [wells, summary, selectedId, radius, go, refresh, activeWell])
  const sel = wells.find((w) => w.id === selectedId)

  return (
    <UiModeProvider>
      <AppCtx.Provider value={ctx}>
        <div className="shell">
          <nav className="nav" aria-label="Main">
            <div className="brand">
              <div className="brand-mark">
                <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden><path d="M16 4l5 10-5 3-5-3z" fill="#f59e0b" /><rect x="14.3" y="16" width="3.4" height="12" rx="1.7" fill="#38bdf8" /></svg>
              </div>
              <div><div className="brand-name">eRTMAC-NWIS</div><div className="brand-sub">Nearby Wells Intelligence</div></div>
            </div>
            {NAV.map((n) => (
              <button key={n.id} className="nav-item" aria-current={page === n.id ? 'page' : undefined} onClick={() => go(n.id)}>
                <Icon name={n.icon} /> {n.label}
              </button>
            ))}
            <div className="nav-foot">SIH 2026 · PS 26121<br />Oil India Limited</div>
          </nav>
          <div className="main">
            <div className="topbar">
              <h1>{TITLES[page]}</h1>
              <span className="spacer" />
              <ModeToggle />
              {page !== 'impact' && page !== 'start' && wells.length > 0 && (
                <label className="row muted small" style={{ gap: 8 }}>
                  Well
                  <select className="select" value={selectedId ?? ''} onChange={(e) => setSelectedId(Number(e.target.value))} aria-label="Select well">
                    {wells.map((w) => <option key={w.id} value={w.id}>{w.name}{w.status === 'ACTIVE' ? ' (active)' : ''}</option>)}
                  </select>
                </label>
              )}
              {page !== 'impact' && page !== 'start' && sel && <span className="chip">{sel.field}</span>}
            </div>
            <div className="banner" role="note">
              Demonstration dataset: all wells, reports and drilling logs are <b>synthetic</b> (no Oil India data was used). The pipeline ingests real WCR/DDR PDFs and eRTMAC-style feeds without change.
            </div>
            <div className="page">
              {wells.length === 0 && (
                <div className="card" role="status">
                  <span className="row"><Spinner />
                    <b>Waking up the analysis server…</b></span>
                  <p className="muted small" style={{ marginTop: 8 }}>
                    The demo backend sleeps when idle and takes up to a minute to start. This page will load by itself
                    {attempt > 0 ? ` (attempt ${attempt + 1})` : ''}.
                  </p>
                </div>
              )}
              {wells.length > 0 && (
                <>
                  {page === 'start' && <StartPage />}
                  {page === 'impact' && <ImpactPage />}
                  {page === 'map' && <MapPage />}
                  {page === 'correlation' && <CorrelationPage />}
                  {page === 'knowledge' && <KnowledgePage />}
                  {page === 'live' && <LivePage />}
                  {page === 'rig' && <RigPage />}
                  {page === 'documents' && <DocumentsPage />}
                  {page === 'review' && <ReviewPage />}
                </>
              )}
            </div>
          </div>
        </div>
      </AppCtx.Provider>
    </UiModeProvider>
  )
}

import { ReactNode, useEffect, useState } from 'react'
import { COLORS, EventType, LABELS } from '../lib/api'
import { useUiMode } from '../lib/uiMode'

const ICONS: Record<string, string> = {
  map: 'M9 4 3 6.5v13L9 17l6 2.5 6-2.5v-13L15 6.5 9 4Zm0 0v13m6-10.5v13',
  layers: 'm12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5m-18 4 9 5 9-5',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm10 17-5-5',
  activity: 'M3 12h4l3-8 4 16 3-8h4',
  file: 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Zm0 0v5h5M9 13h6M9 17h6',
  close: 'M6 6l12 12M18 6 6 18',
  play: 'M7 4v16l13-8L7 4Z',
  pause: 'M8 4v16M16 4v16',
  reset: 'M4 12a8 8 0 1 0 3-6.2M4 4v5h5',
  upload: 'M12 16V4m0 0-4 4m4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3',
  alert: 'M12 4 2.5 20h19L12 4Zm0 6v5m0 3v.5',
  check: 'm5 12 5 5 9-10',
  chevronDown: 'm6 9 6 6 6-6',
  chevronUp: 'm6 15 6-6 6 6',
  info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-9v5m0-8.5v.5',
}

export function Icon({ name, size = 18 }: { name: keyof typeof ICONS | string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={ICONS[name] ?? ''} />
    </svg>
  )
}

export function Spinner() {
  return <span className="spinner" role="status" aria-label="Loading" />
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null
  return <div className="err" role="alert">{error instanceof Error ? error.message : String(error)}</div>
}

export function Kpi({ value, label, hint }: { value: ReactNode; label: ReactNode; hint?: string }) {
  return (
    <div className="kpi" title={hint}>
      <div className="v">{value}</div>
      <div className="l">{label}</div>
    </div>
  )
}

export function TypeChip({ type, count }: { type: EventType; count?: number }) {
  return (
    <span className="chip" title={LABELS[type]}>
      <span className="dot" style={{ background: COLORS[type] }} />
      {LABELS[type]}
      {count !== undefined && <b style={{ color: 'var(--text)' }}>{count}</b>}
    </span>
  )
}

export function SeverityChip({ severity }: { severity: string }) {
  const cls = severity === 'critical' ? 'badge-crit' : severity === 'high' ? 'badge-warn' : severity === 'medium' ? 'badge-info' : ''
  return <span className={`chip ${cls}`}>{severity}</span>
}

export function LevelChip({ level }: { level: string }) {
  const cls = level === 'critical' || level === 'high' ? 'badge-crit' : level === 'warning' || level === 'medium' ? 'badge-warn' : level === 'info' ? 'badge-info' : ''
  return <span className={`chip ${cls}`}>{level}</span>
}

const GLOSSARY: Record<string, string> = {
  MD: 'Measured depth: the length of pipe run into the well, following its path. In an angled well this is more than the straight-down depth.',
  TVD: 'True vertical depth: how far straight down you are, regardless of how much the well bends sideways.',
  SG: "Specific gravity: how heavy the drilling fluid is. Heavier fluid pushes back harder against pressure from the rock, which is why it's raised as a precaution.",
  NPT: 'Non-productive time: hours lost to a problem (fixing a stuck pipe, waiting on cement, etc.) instead of drilling ahead.',
  kNm: 'Kilonewton-metres: a unit of twisting force (torque) on the drill string.',
  bar: 'A unit of pressure, roughly atmospheric pressure at sea level.',
  prevalence: 'How many of the nearby wells actually had this problem, out of all the nearby wells that drilled deep enough to reach it.',
  offsets: 'Offset wells: wells already drilled near the one being planned or drilled now.',
  'offset well': 'A well already drilled near the one being planned or drilled now.',
  'offset wells': 'Wells already drilled near the one being planned or drilled now.',
  'hazard zone': 'A depth range where nearby wells had a specific problem, projected onto the well being drilled now.',
  corroborated: 'This incident was reported in two separate documents (a daily report and a completion report), not just one, so it is more likely accurate.',
  OCR: 'Optical character recognition: software that reads text out of a scanned image, the way you would read a photocopy.',
  overpull: 'Extra pulling force needed to move the pipe, beyond its own weight; a sign it may be stuck or dragging.',
  'pit gain': 'The drilling-fluid tank got fuller than expected: an early warning sign that gas or fluid entered the well unexpectedly (a "kick").',
  formation: 'A layer of rock the well passes through on its way down. Different layers behave differently and carry different risks.',
  WCR: 'Well Completion Report: the summary document written once a well is finished, covering its depth, layers, and any major problems.',
  DDR: "Daily Drilling Report: the day-by-day logbook written while a well is being drilled.",
  backtest: "A check that replays history: hide a well's own report, predict its problems from neighbouring wells only, then see how many of its real problems would have been caught.",
  AUC: 'A 0-1 score for how well the model ranks risky moments above safe ones: 0.5 is no better than guessing, 1.0 is perfect.',
  MSE: 'Mechanical Specific Energy: the effort spent per unit of rock actually drilled. It rises when a lot of torque and weight produce little progress — a real drilling-engineering warning sign for bit wear, a formation change, or the early stage of getting stuck.',
}

export function Term({ children, term }: { children: ReactNode; term: string }) {
  const def = GLOSSARY[term]
  if (!def) return <>{children}</>
  return (
    <span className="term" tabIndex={0} title={def}>
      {children}
    </span>
  )
}

export function Intro({ children }: { children: ReactNode }) {
  return (
    <div className="intro-line row">
      <Icon name="info" size={16} />
      <span>{children}</span>
    </div>
  )
}

export function Advanced({ title, summary, children, defaultOpen = false }: {
  title: string; summary?: ReactNode; children: ReactNode; defaultOpen?: boolean
}) {
  const { simple } = useUiMode()
  const [open, setOpen] = useState(defaultOpen)
  if (!simple) return <div className="card">{children}</div>
  return (
    <div className="card advanced">
      <button className="advanced-toggle" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="row" style={{ gap: 8 }}>
          <Icon name={open ? 'chevronUp' : 'chevronDown'} size={16} />
          <b>{title}</b>
        </span>
        {!open && summary && <span className="muted small">{summary}</span>}
      </button>
      {open && <div style={{ marginTop: 12 }}>{children}</div>}
    </div>
  )
}

export function ModeToggle() {
  const { simple, setSimple } = useUiMode()
  return (
    <div className="mode-toggle" role="group" aria-label="Page detail level">
      <button className={simple ? 'active' : ''} aria-pressed={simple} onClick={() => setSimple(true)}>Simple</button>
      <button className={!simple ? 'active' : ''} aria-pressed={!simple} onClick={() => setSimple(false)}>Technical</button>
    </div>
  )
}

export function Drawer({ title, onClose, children, sub }: { title: ReactNode; sub?: ReactNode; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Details">
        <div className="drawer-head">
          <div style={{ flex: 1, minWidth: 0 }}>
            <h2 style={{ fontSize: 16 }}>{title}</h2>
            {sub && <div className="muted small" style={{ marginTop: 3 }}>{sub}</div>}
          </div>
          <button className="btn small" onClick={onClose} aria-label="Close details"><Icon name="close" size={16} /></button>
        </div>
        <div className="drawer-body">{children}</div>
      </aside>
    </>
  )
}

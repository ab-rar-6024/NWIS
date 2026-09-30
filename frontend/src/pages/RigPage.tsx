import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, api, API_BASE, COLORS, LABELS, LiveSnapshot, LiveState } from '../lib/api'
import { useApp } from '../App'
import { Icon, Spinner } from '../components/common'
import { fmt, pct } from '../lib/format'

const LEVEL_RANK = { critical: 3, warning: 2, info: 1 } as const
const LEVEL_COLOR = { critical: 'var(--crit)', warning: 'var(--warn)', info: 'var(--accent-2)' } as const

// Alert-first screen for the rig floor: big type, few elements, one decision at a time.
export default function RigPage() {
  const { activeWell } = useApp()
  const id = activeWell?.id
  const [snap, setSnap] = useState<LiveSnapshot | null>(null)
  const [state, setState] = useState<LiveState | null>(null)
  const [md, setMd] = useState<number | null>(null)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!id) return
    try {
      const s = await api.liveSnapshot(id)
      setSnap(s); setState(s.state); setAlerts([...s.alerts].reverse())
      setMd(s.history.length ? s.history[s.history.length - 1].md : s.state.start_md)
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)) }
  }, [id])
  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (!id) return
    const es = new EventSource(`${API_BASE}/api/live/${id}/stream`)
    es.onmessage = (m) => {
      const msg = JSON.parse(m.data)
      if (msg.type === 'sample') setMd(msg.data.md)
      else if (msg.type === 'alert') setAlerts((a) => [msg.data, ...a].slice(0, 50))
      else if (msg.type === 'state') setState(msg.data)
      else if (msg.type === 'reset' || msg.type === 'hello') load()
    }
    return () => es.close()
  }, [id, load])

  const control = async (action: string) => {
    if (!id || !state) return
    try {
      setState(await api.liveControl(id, action === 'start' ? { action, speed: state.speed, start_md: state.start_md } : { action }))
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)) }
  }

  const current = md ?? 0
  const top = useMemo(() => alerts.slice(0, 8).sort((a, b) => LEVEL_RANK[b.level] - LEVEL_RANK[a.level])[0], [alerts])
  const next = useMemo(
    () => (snap ? snap.zones.filter((z) => z.md_to > current && z.level !== 'low').sort((a, b) => a.md_from - b.md_from).slice(0, 3) : []),
    [snap, current],
  )

  if (!activeWell) return <div className="empty">No active well is registered.</div>
  if (!snap) return err ? <div className="err">{err}</div> : <Spinner />

  const running = !!state?.running
  return (
    <div className="col" style={{ gap: 16, maxWidth: 900, margin: '0 auto' }}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div>
          <div className="muted small">{activeWell.name} · bit depth</div>
          <div className="mono" style={{ fontSize: 56, fontWeight: 750, lineHeight: 1 }}>{fmt(current)} <span style={{ fontSize: 22 }} className="muted">m</span></div>
        </div>
        <button className={running ? 'btn' : 'btn primary'} style={{ fontSize: 18, padding: '14px 24px' }} onClick={() => control(running ? 'pause' : 'start')}>
          <Icon name={running ? 'pause' : 'play'} size={20} /> {running ? 'Pause' : 'Start'}
        </button>
      </div>

      {top ? (
        <div className="card" style={{ borderColor: LEVEL_COLOR[top.level], borderWidth: 2 }}>
          <div className="row" style={{ gap: 10 }}>
            <span className="chip" style={{ background: LEVEL_COLOR[top.level], color: '#0a1120' }}>{top.level.toUpperCase()}</span>
            <span className="chip"><span className="dot" style={{ background: COLORS[top.hazard] }} />{LABELS[top.hazard]}</span>
            <span className="mono muted right">{top.ahead_m ? `${fmt(top.ahead_m)} m ahead` : `at ${fmt(top.md)} m`}</span>
          </div>
          <div style={{ fontSize: 26, fontWeight: 700, marginTop: 10 }}>{top.title}</div>
          {top.recommendation && <div style={{ fontSize: 20, marginTop: 8, color: '#cbd8ee' }}>→ {top.recommendation}</div>}
        </div>
      ) : (
        <div className="card" style={{ fontSize: 20, padding: 24 }}>
          <b style={{ color: 'var(--ok)' }}>No active alerts.</b>{' '}
          <span className="muted">{running ? 'Watching the offset wells ahead of the bit.' : 'Press Start to begin the replay.'}</span>
        </div>
      )}

      <div className="card">
        <h3>Next hazards ahead</h3>
        {next.length === 0 && <div className="faint">Nothing flagged by the offset wells for the rest of the hole.</div>}
        {next.map((z) => (
          <div key={z.id} className="row" style={{ fontSize: 20, padding: '8px 0', borderTop: '1px solid var(--line-soft)' }}>
            <span className="dot" style={{ background: COLORS[z.type], width: 14, height: 14 }} />
            <b>{z.label}</b>
            <span className="muted">in</span>
            <span className="mono"><b>{fmt(Math.max(0, z.md_from - current))} m</b></span>
            <span className="muted right">{pct(z.prevalence)} of offsets</span>
          </div>
        ))}
      </div>
      <div className="faint small">Same session as the Live monitor page. Advisory only; it does not control the rig.</div>
    </div>
  )
}

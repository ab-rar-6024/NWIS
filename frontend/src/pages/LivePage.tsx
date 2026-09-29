import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Alert, api, API_BASE, COLORS, EventType, FeedbackStats, LABELS, LiveSample, LiveSnapshot, LiveState, RISK_TYPES, Zone } from '../lib/api'
import { useApp } from '../App'
import { Advanced, Drawer, ErrorBox, Icon, Intro, Kpi, LevelChip, Spinner, Term } from '../components/common'
import { fmt, formationColor, pct } from '../lib/format'

const KIND_LABEL: Record<Alert['kind'], string> = { lookahead: 'AHEAD', formation: 'FORMATION', realtime: 'LIVE SIGNAL', model: 'MODEL' }
const MAX_POINTS = 1500

interface SeriesDef { key: keyof LiveSample; color: string; name: string }

function LiveChart({ title, unit, data, series, domain, alerts, refs }: {
  title: string; unit: string; data: LiveSample[]; series: SeriesDef[]; domain: [number, number]; alerts: Alert[]; refs?: number[]
}) {
  const last = data[data.length - 1]
  return (
    <div className="chart-card">
      <div className="chart-title">
        <span>{title} <span className="faint">{unit}</span></span>
        <span className="mono" style={{ color: 'var(--text)' }}>{last ? series.map((s) => fmt(last[s.key] as number, 1)).join(' / ') : ''}</span>
      </div>
      <ResponsiveContainer width="100%" height={150}>
        <LineChart data={data} syncId="live" margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#1a2a47" vertical={false} />
          <XAxis dataKey="md" type="number" domain={domain} tick={{ fill: '#7f93b6', fontSize: 10 }} tickCount={6} allowDataOverflow />
          <YAxis tick={{ fill: '#7f93b6', fontSize: 10 }} width={38} domain={['auto', 'auto']} />
          <Tooltip contentStyle={{ background: '#0f1a30', border: '1px solid #24365a', borderRadius: 8, fontSize: 12 }} labelFormatter={(v) => `${v} m MD`} formatter={(v) => fmt(typeof v === 'number' ? v : Number(v), 2)} />
          {refs?.map((r) => <ReferenceLine key={r} y={r} stroke="#f8717188" strokeDasharray="4 3" />)}
          {alerts.map((a, i) => <ReferenceLine key={`${a.md}-${i}`} x={a.md} stroke={COLORS[a.hazard]} strokeOpacity={0.55} />)}
          {series.map((s) => <Line key={String(s.key)} dataKey={s.key as string} name={s.name} stroke={s.color} dot={false} strokeWidth={1.6} isAnimationActive={false} />)}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function AheadStrip({ md, tops, zones, td }: { md: number; tops: LiveSnapshot['tops']; zones: Zone[]; td: number }) {
  const W = 1000
  const from = md - 120
  const to = md + 620
  const x = (m: number) => ((m - from) / (to - from)) * W
  const rows = RISK_TYPES
  const H = 58 + rows.length * 24 + 24
  const bands = tops.map((t, i) => ({ f: t.formation, a: t.md, b: tops[i + 1]?.md ?? td, sigma: t.sigma_m }))
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Look-ahead strip: predicted formations and hazard zones ahead of the bit" style={{ display: 'block' }}>
      {bands.map((b) => {
        const a = Math.max(x(b.a), 0)
        const e = Math.min(x(b.b), W)
        if (e <= a) return null
        return (
          <g key={b.f}>
            <rect x={a} y={6} width={e - a} height={26} fill={formationColor(b.f)} opacity={0.85} />
            <rect x={x(b.a) - (b.sigma / (to - from)) * W} y={6} width={(2 * b.sigma / (to - from)) * W} height={26} fill="#fff" opacity={0.18} />
            {e - a > 70 && <text x={a + 6} y={24} fontSize={12} fontWeight={650} fill="#0b1424">{b.f}</text>}
          </g>
        )
      })}
      {Array.from({ length: Math.ceil((to - from) / 100) + 1 }, (_, i) => {
        const m = Math.ceil(from / 100) * 100 + i * 100
        if (m > to) return null
        return (
          <g key={m}>
            <line x1={x(m)} x2={x(m)} y1={36} y2={H - 22} stroke="#1a2a47" />
            <text x={x(m)} y={H - 8} fontSize={11} fill="#7f93b6" textAnchor="middle" className="mono">{m}</text>
          </g>
        )
      })}
      {rows.map((t, i) => (
        <g key={t}>
          <text x={4} y={56 + i * 24} fontSize={11} fill={COLORS[t]}>{LABELS[t]}</text>
          {zones.filter((z) => z.type === t && z.md_to >= from && z.md_from <= to).map((z) => (
            <g key={z.id}>
              <rect x={Math.max(x(z.md_from), 0)} y={44 + i * 24} width={Math.max(x(z.md_to) - Math.max(x(z.md_from), 0), 5)} height={14} rx={4} fill={COLORS[t]} opacity={z.level === 'high' ? 0.85 : z.level === 'medium' ? 0.5 : 0.22}>
                <title>{`${z.label} zone ${fmt(z.md_from)}-${fmt(z.md_to)} m · ${z.n_wells} offset wells · prevalence ${pct(z.prevalence)}`}</title>
              </rect>
            </g>
          ))}
        </g>
      ))}
      <line x1={x(md)} x2={x(md)} y1={0} y2={H - 20} stroke="#f43f5e" strokeWidth={2} />
      <polygon points={`${x(md) - 6},0 ${x(md) + 6},0 ${x(md)},9`} fill="#f43f5e" />
      <text x={x(md) + 8} y={H - 26} fontSize={11} fill="#f43f5e" fontWeight={700}>bit {fmt(md)} m</text>
    </svg>
  )
}

function FeedbackButtons({ a, onSubmit, size = 'normal' }: { a: Alert; onSubmit: (status: 'confirmed' | 'dismissed') => void; size?: 'small' | 'normal' }) {
  const cls = size === 'small' ? 'chip btn-chip' : 'btn small'
  if (a.id === undefined) return null
  return (
    <div className="row" style={{ gap: 6 }} onClick={(e) => e.stopPropagation()}>
      <span className="faint small">Was this useful?</span>
      <button className={cls} aria-pressed={a.feedback === 'confirmed'} style={a.feedback === 'confirmed' ? { color: 'var(--ok)', borderColor: 'var(--ok)' } : undefined} onClick={() => onSubmit('confirmed')}>
        <Icon name="check" size={13} /> Accurate
      </button>
      <button className={cls} aria-pressed={a.feedback === 'dismissed'} style={a.feedback === 'dismissed' ? { color: 'var(--crit)', borderColor: 'var(--crit)' } : undefined} onClick={() => onSubmit('dismissed')}>
        <Icon name="close" size={13} /> False alarm
      </button>
    </div>
  )
}

function AlertDrawer({ a, onClose, onFeedback }: { a: Alert; onClose: () => void; onFeedback: (alertId: number, status: 'confirmed' | 'dismissed') => void }) {
  const z: Zone | undefined = a.evidence.zone
  const sig = a.kind === 'realtime' ? (a.evidence as Record<string, number>) : null
  return (
    <Drawer onClose={onClose} title={a.title} sub={`${a.well} · ${fmt(a.md)} m MD · ${a.formation ?? ''}`}>
      <div className="row"><LevelChip level={a.level} /><span className="chip">{KIND_LABEL[a.kind]}</span><span className="chip"><span className="dot" style={{ background: COLORS[a.hazard] }} />{LABELS[a.hazard]}</span></div>
      <div>{a.message}</div>
      {a.recommendation && <div className="quote">{a.recommendation}</div>}
      {z && (
        <div className="kv">
          <div><div className="k">Zone (MD)</div><div className="val">{fmt(z.md_from)}–{fmt(z.md_to)} m</div></div>
          <div><div className="k">Offset wells</div><div className="val">{z.n_wells} ({z.n_events} events)</div></div>
          <div><div className="k">Prevalence</div><div className="val">{pct(z.prevalence)}</div></div>
          <div><div className="k">Mean NPT</div><div className="val">{z.mean_npt_h !== null ? `${fmt(z.mean_npt_h, 1)} h` : '–'}</div></div>
          <div style={{ gridColumn: '1 / -1' }}><div className="k">Evidence wells</div><div className="val" style={{ fontWeight: 500 }}>{z.wells.join(', ')}</div></div>
        </div>
      )}
      {sig && (
        <div className="kv">
          {Object.entries(sig).map(([k, v]) => <div key={k}><div className="k">{k.replace(/_/g, ' ')}</div><div className="val">{typeof v === 'number' ? fmt(v, 2) : String(v)}</div></div>)}
        </div>
      )}
      {a.kind === 'model' && (
        <div className="kv">
          <div><div className="k">Probability</div><div className="val">{pct(a.evidence.probability)}</div></div>
          <div><div className="k">Alert threshold</div><div className="val">{pct(a.evidence.threshold)}</div></div>
          {a.evidence.wells && <div style={{ gridColumn: '1 / -1' }}><div className="k">Evidence wells</div><div className="val" style={{ fontWeight: 500 }}>{a.evidence.wells.join(', ')}</div></div>}
        </div>
      )}
      {a.kind === 'formation' && a.evidence.formation && (
        <div className="small muted">Expected NPT in this formation from offsets: <b>{fmt(a.evidence.formation.expected_npt_h, 1)} h</b> across {a.evidence.formation.n_offsets} wells.</div>
      )}
      {a.id !== undefined && (
        <div style={{ borderTop: '1px solid var(--line-soft)', paddingTop: 12 }}>
          <FeedbackButtons a={a} onSubmit={(status) => onFeedback(a.id as number, status)} />
        </div>
      )}
    </Drawer>
  )
}

export default function LivePage() {
  const { activeWell, radius } = useApp()
  const id = activeWell?.id
  const [snap, setSnap] = useState<LiveSnapshot | null>(null)
  const [history, setHistory] = useState<LiveSample[]>([])
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [state, setState] = useState<LiveState | null>(null)
  const [speed, setSpeed] = useState(10)
  const [startMd, setStartMd] = useState(1300)
  const [err, setErr] = useState<unknown>(null)
  const [openAlert, setOpenAlert] = useState<Alert | null>(null)
  const [filter, setFilter] = useState<'all' | Alert['kind']>('all')
  const [feedbackStats, setFeedbackStats] = useState<FeedbackStats | null>(null)
  const sbuf = useRef<LiveSample[]>([])
  const abuf = useRef<Alert[]>([])

  const load = useCallback(async () => {
    if (!id) return
    try {
      const [s, fs] = await Promise.all([api.liveSnapshot(id), api.feedbackStats(id)])
      setSnap(s); setHistory(s.history.slice(-MAX_POINTS)); setAlerts([...s.alerts].reverse()); setState(s.state); setSpeed(s.state.speed); setStartMd(s.state.start_md); setFeedbackStats(fs)
      sbuf.current = []; abuf.current = []
    } catch (e) { setErr(e) }
  }, [id])
  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (!id) return
    const es = new EventSource(`${API_BASE}/api/live/${id}/stream`)
    es.onmessage = (m) => {
      const msg = JSON.parse(m.data)
      if (msg.type === 'sample') sbuf.current.push(msg.data)
      else if (msg.type === 'alert') abuf.current.push(msg.data)
      else if (msg.type === 'state') setState(msg.data)
      else if (msg.type === 'feedback') {
        setFeedbackStats(msg.data.stats)
        setAlerts((cur) => cur.map((a) => (a.id === msg.data.alert_id ? { ...a, feedback: msg.data.status } : a)))
      } else if (msg.type === 'reset' || msg.type === 'hello') load()
    }
    const flush = setInterval(() => {
      if (sbuf.current.length) { const b = sbuf.current.splice(0); setHistory((h) => [...h, ...b].slice(-MAX_POINTS)) }
      if (abuf.current.length) { const b = abuf.current.splice(0); setAlerts((a) => [...b.reverse(), ...a]) }
    }, 250)
    return () => { es.close(); clearInterval(flush) }
  }, [id, load])

  const submitFeedback = useCallback(async (alertId: number, status: 'confirmed' | 'dismissed') => {
    if (!id) return
    setAlerts((cur) => cur.map((a) => (a.id === alertId ? { ...a, feedback: status } : a)))
    setOpenAlert((cur) => (cur && cur.id === alertId ? { ...cur, feedback: status } : cur))
    try {
      const r = await api.alertFeedback(id, alertId, status)
      setFeedbackStats(r.stats)
    } catch (e) { setErr(e) }
  }, [id])

  const control = async (action: string, extra: Record<string, number> = {}) => {
    if (!id) return
    try { setState(await api.liveControl(id, { action, ...extra })); setErr(null) } catch (e) { setErr(e) }
  }

  const last = history[history.length - 1]
  const md = last?.md ?? startMd
  const curFm = useMemo(() => {
    if (!snap) return null
    let f: string | null = null
    snap.tops.forEach((t) => { if (md >= t.md) f = t.formation })
    return f
  }, [snap, md])
  const domain: [number, number] = [state?.start_md ?? startMd, state?.planned_td_md ?? 3900]
  const realtime = alerts.filter((a) => a.kind === 'realtime' || (a.kind === 'model' && a.level === 'critical'))
  const shown = alerts.filter((a) => filter === 'all' || a.kind === filter)
  const ahead = useMemo(() => (snap ? snap.zones.filter((z) => z.md_to > md && z.level !== 'low').slice().sort((a, b) => a.md_from - b.md_from).slice(0, 4) : []), [snap, md])
  const progress = state ? Math.min(1, (md - domain[0]) / Math.max(1, domain[1] - domain[0])) : 0

  if (!activeWell) return <div className="empty">No active well is registered.</div>

  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="card">
        <div className="row">
          <h2 style={{ fontSize: 18 }}>{activeWell.name}</h2>
          <span className={`chip ${state?.running ? 'badge-ok' : ''}`}>{state?.running ? '● streaming' : state && state.idx >= state.n ? 'finished' : 'paused'}</span>
          {feedbackStats && feedbackStats.rated > 0 && (
            <span className="chip badge-info" title="Alerts the operator has marked accurate or a false alarm">
              operator feedback: {feedbackStats.confirmed} accurate, {feedbackStats.dismissed} false alarm{feedbackStats.dismissed === 1 ? '' : 's'} ({pct(feedbackStats.agreement)} agreement)
            </span>
          )}
          <span className="muted small">Replaying a recorded drilling feed, depth by depth, as if it were happening live.</span>
          <span className="right row">
            <label className="row muted small" style={{ gap: 6 }}>From
              <input className="input" type="number" style={{ width: 84 }} value={startMd} min={0} step={100} onChange={(e) => setStartMd(Number(e.target.value))} aria-label="Start depth" disabled={history.length > 0 && !!state?.running} />
              m
            </label>
            <label className="row muted small" style={{ gap: 6 }}>Speed
              <input type="range" min={1} max={30} value={speed} onChange={(e) => { const v = Number(e.target.value); setSpeed(v); control('speed', { speed: v }) }} aria-label="Replay speed" />
              <b className="mono" style={{ color: 'var(--text)', width: 42 }}>{speed}/s</b>
            </label>
            {state?.running ? (
              <button className="btn" onClick={() => control('pause')}><Icon name="pause" size={15} /> Pause</button>
            ) : (
              <button className="btn primary" onClick={() => control('start', { speed, start_md: startMd })}><Icon name="play" size={15} /> {history.length ? 'Resume' : 'Start replay'}</button>
            )}
            <button className="btn" onClick={() => control('reset', { start_md: startMd })}><Icon name="reset" size={15} /> Reset</button>
          </span>
        </div>
        <div className="bar" style={{ marginTop: 12 }}><i style={{ width: `${progress * 100}%`, background: 'var(--accent)' }} /></div>
      </div>
      <ErrorBox error={err} />

      <div className="kpis" style={{ marginBottom: 0 }}>
        <Kpi value={`${fmt(md)} m`} label="Current depth" hint="Measured depth (MD): distance drilled along the well's path" />
        <Kpi value={curFm ?? '–'} label="Rock layer (estimated)" />
        <Kpi value={last ? fmt(last.rop, 1) : '–'} label="Drilling speed (m/h)" />
        <Kpi value={last ? fmt(last.mw, 2) : '–'} label={<>Fluid weight (<Term term="SG">SG</Term>)</>} />
        <Kpi value={alerts.length} label="Alerts raised" />
      </div>

      <Intro>
        The strip below shows what's coming up: it takes what happened in nearby wells and lines it up against
        the depth this well is about to reach. The alerts list on the right explains each warning in plain
        language, and the buttons on it let you mark whether it was actually useful.
      </Intro>

      <div className="card">
        <h3>Look-ahead: what offset wells say lies ahead of the bit</h3>
        {snap ? <AheadStrip md={md} tops={snap.tops} zones={snap.zones} td={domain[1]} /> : <Spinner />}
        <div className="row" style={{ marginTop: 6 }}>
          {ahead.map((z) => (
            <span key={z.id} className="chip" style={{ borderColor: COLORS[z.type] + '88', border: '1px solid' }}>
              <span className="dot" style={{ background: COLORS[z.type] }} />{z.label} in {fmt(Math.max(0, z.md_from - md))} m · {pct(z.prevalence)} of offsets
            </span>
          ))}
          {snap && ahead.length === 0 && <span className="faint small">No medium/high offset hazards ahead.</span>}
          <span className="faint small right">Predicted tops carry a ±uncertainty band (white haze).</span>
        </div>
      </div>

      <div className="live-grid">
        <Advanced title="Live sensor charts" summary="7 drilling parameters, charted against depth" defaultOpen={false}>
          <div className="charts">
            <LiveChart title="Rate of penetration" unit="m/h" data={history} domain={domain} alerts={realtime} series={[{ key: 'rop', color: '#38bdf8', name: 'ROP' }]} />
            <LiveChart title="Torque / overpull" unit="kNm / t" data={history} domain={domain} alerts={realtime} series={[{ key: 'torque', color: '#facc15', name: 'Torque' }, { key: 'overpull', color: '#a78bfa', name: 'Overpull' }]} />
            <LiveChart title="Mechanical specific energy" unit="MPa" data={history} domain={domain} alerts={realtime} series={[{ key: 'mse', color: '#fb7185', name: 'MSE' }]} />
            <LiveChart title="Flow-out vs flow-in" unit="%" data={history} domain={domain} alerts={realtime} refs={[2, -2]} series={[{ key: 'flow_diff_pct', color: '#fb923c', name: 'Δ flow' }]} />
            <LiveChart title="Pit volume change" unit="m³" data={history} domain={domain} alerts={realtime} series={[{ key: 'pit_delta', color: '#4ade80', name: 'Pit' }]} />
            <LiveChart title="Gas" unit="units" data={history} domain={domain} alerts={realtime} series={[{ key: 'gas', color: '#f87171', name: 'Gas' }]} />
            <LiveChart title="Mud weight" unit="SG" data={history} domain={domain} alerts={realtime} series={[{ key: 'mw', color: '#94a3b8', name: 'MW' }]} />
          </div>
          <div className="faint small" style={{ marginTop: 8 }}>
            Vertical lines mark real-time and critical model alerts, coloured by hazard. <Term term="MSE">Mechanical specific energy</Term> is
            the effort spent per metre actually drilled — the same real diagnostic a rig floor watches for bit wear and inefficient drilling.
          </div>
        </Advanced>

        <div className="col" style={{ gap: 14 }}>
          <Advanced title="AI risk model" summary="probability of each problem in the next 50 m" defaultOpen={false}>
            <h3 style={{ marginTop: 0 }}>Model risk — next 50 m</h3>
            {RISK_TYPES.map((t: EventType) => {
              const p = last?.probs?.[t] ?? state?.probs?.[t] ?? 0
              return (
                <div key={t} className="gauge">
                  <span><span className="dot" style={{ background: COLORS[t], marginRight: 6 }} />{LABELS[t]}</span>
                  <div className="bar"><i style={{ width: `${Math.min(100, p * 100)}%`, background: COLORS[t] }} /></div>
                  <span className="mono">{pct(p)}</span>
                </div>
              )
            })}
            <div className="faint small">Gradient-boosted model on live signals + offset knowledge; alerts fire above a per-hazard threshold tuned by cross-validation.</div>
          </Advanced>
          <div className="card">
            <div className="row" style={{ marginBottom: 8 }}>
              <h3 style={{ margin: 0 }}>Alerts</h3>
              <span className="right row" style={{ gap: 5 }}>
                {(['all', 'lookahead', 'formation', 'realtime', 'model'] as const).map((k) => (
                  <button key={k} className="chip btn-chip" aria-pressed={filter === k} onClick={() => setFilter(k)}>{k === 'all' ? 'All' : KIND_LABEL[k]}</button>
                ))}
              </span>
            </div>
            {shown.length === 0 && <div className="faint small" style={{ padding: 14 }}>{alerts.length ? 'No alerts of this kind.' : 'Start the replay: alerts appear here as the bit approaches offset-reported hazards.'}</div>}
            <div className="alert-list">
              {shown.map((a, i) => (
                <div key={`${a.id ?? i}`} className={`alert ${a.level}`} onClick={() => setOpenAlert(a)} role="button" tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && setOpenAlert(a)}>
                  <div className="row" style={{ gap: 6 }}>
                    <span className="chip">{KIND_LABEL[a.kind]}</span>
                    <LevelChip level={a.level} />
                    <span className="mono muted small right">{fmt(a.md)} m{a.ahead_m ? ` · ${fmt(a.ahead_m)} m ahead` : ''}</span>
                  </div>
                  <div style={{ fontWeight: 650, marginTop: 5 }}>{a.title}</div>
                  <div className="muted small" style={{ marginTop: 2 }}>{a.message}</div>
                  {a.recommendation && <div className="small" style={{ marginTop: 4, color: '#cbd8ee' }}>→ {a.recommendation}</div>}
                  {a.id !== undefined && (
                    <div style={{ marginTop: 7 }}><FeedbackButtons a={a} size="small" onSubmit={(status) => submitFeedback(a.id as number, status)} /></div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      {openAlert && <AlertDrawer a={openAlert} onClose={() => setOpenAlert(null)} onFeedback={submitFeedback} />}
    </div>
  )
}

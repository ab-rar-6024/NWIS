import { ReactNode, useEffect, useMemo, useState } from 'react'
import { api, COLORS, Correlation, CorrWell, EVENT_TYPES, EventType, LABELS, Lookahead, RiskRow, RISK_TYPES, Zone } from '../lib/api'
import { useApp } from '../App'
import { EventDrawer } from '../components/EventDrawer'
import { Advanced, ErrorBox, Intro, Spinner, Term } from '../components/common'
import { fmt, formationColor, pct, SEV_SIZE } from '../lib/format'

const BAR_W = 44
const LANE = 9
const TRACK_W = BAR_W + 12 + EVENT_TYPES.length * LANE
const GAP = 58
const LEFT = 170
const TOP = 62
const PLOT_H = 700

function Marker({ type, x, y, r, onClick, onEnter, onLeave }: { type: EventType; x: number; y: number; r: number; onClick: () => void; onEnter: (e: React.MouseEvent) => void; onLeave: () => void }) {
  const c = COLORS[type]
  const common = { onClick, onMouseEnter: onEnter, onMouseMove: onEnter, onMouseLeave: onLeave, style: { cursor: 'pointer' }, stroke: '#0b1424', strokeWidth: 0.8 }
  switch (type) {
    case 'mud_loss': return <circle cx={x} cy={y} r={r} fill={c} {...common} />
    case 'kick': return <polygon points={`${x},${y - r * 1.2} ${x + r * 1.15},${y + r * 0.9} ${x - r * 1.15},${y + r * 0.9}`} fill={c} {...common} />
    case 'stuck_pipe': return <rect x={x - r} y={y - r} width={r * 2} height={r * 2} fill={c} {...common} />
    case 'overpressure': return <polygon points={`${x},${y - r * 1.3} ${x + r * 1.3},${y} ${x},${y + r * 1.3} ${x - r * 1.3},${y}`} fill={c} {...common} />
    case 'torque_spike': return <polygon points={`${x - r * 1.15},${y - r * 0.9} ${x + r * 1.15},${y - r * 0.9} ${x},${y + r * 1.2}`} fill={c} {...common} />
    case 'cementing_issue': return <circle cx={x} cy={y} r={r} fill="none" stroke={c} strokeWidth={1.6} onClick={onClick} onMouseEnter={onEnter} onMouseMove={onEnter} onMouseLeave={onLeave} style={{ cursor: 'pointer' }} />
    default: return <rect x={x - r} y={y - r} width={r * 2} height={r * 2} fill="none" stroke={c} strokeWidth={1.6} onClick={onClick} onMouseEnter={onEnter} onMouseMove={onEnter} onMouseLeave={onLeave} style={{ cursor: 'pointer' }} />
  }
}

export default function CorrelationPage() {
  const { selectedId, radius, setRadius } = useApp()
  const [limit, setLimit] = useState(7)
  const [datum, setDatum] = useState<string>('tvd')
  const [showZones, setShowZones] = useState(true)
  const [data, setData] = useState<Correlation | null>(null)
  const [look, setLook] = useState<Lookahead | null>(null)
  const [risk, setRisk] = useState<RiskRow[]>([])
  const [err, setErr] = useState<unknown>(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState<number | null>(null)
  const [tip, setTip] = useState<{ x: number; y: number; body: ReactNode } | null>(null)

  useEffect(() => {
    if (!selectedId) return
    let live = true
    setLoading(true)
    const t = setTimeout(() => {
      Promise.all([api.correlation(selectedId, radius, limit), api.lookahead(selectedId, 0, 6000, radius), api.riskProfile(selectedId, radius)])
        .then(([c, l, r]) => { if (live) { setData(c); setLook(l); setRisk(r.profile); setErr(null) } })
        .catch((e) => live && setErr(e))
        .finally(() => live && setLoading(false))
    }, 150)
    return () => { live = false; clearTimeout(t) }
  }, [selectedId, radius, limit])

  const layout = useMemo(() => {
    if (!data) return null
    const all: CorrWell[] = [data.target, ...data.offsets]
    const topOf = (w: CorrWell) => (datum === 'tvd' ? 0 : w.tops.find((t) => t.formation === datum)?.tvd)
    const shown = all.filter((w) => topOf(w) !== undefined)
    const hidden = all.length - shown.length
    let dmin = 0
    let dmax = 0
    if (datum === 'tvd') {
      dmax = Math.max(...shown.map((w) => w.td_tvd))
    } else {
      dmin = Math.max(-700, Math.min(...shown.map((w) => -(topOf(w) as number))))
      dmax = Math.min(900, Math.max(...shown.map((w) => w.td_tvd - (topOf(w) as number))))
    }
    const y = (w: CorrWell, tvd: number) => {
      const d = tvd - (topOf(w) as number)
      return TOP + ((d - dmin) / (dmax - dmin)) * PLOT_H
    }
    return { shown, hidden, dmin, dmax, y, topOf }
  }, [data, datum])

  if (!selectedId) return null
  const width = layout ? LEFT + layout.shown.length * (TRACK_W + GAP) + 30 : 600
  const height = TOP + PLOT_H + 30
  const step = datum === 'tvd' ? 250 : 100

  const zonesTarget: Zone[] = look ? look.zones.filter((z) => showZones && z.level !== 'low') : []

  const plainSummary = useMemo(() => {
    if (!data) return null
    const offs = data.offsets
    const totalEvents = offs.reduce((a, w) => a + w.events.length, 0)
    const totalNpt = offs.reduce((a, w) => a + w.events.reduce((s, e) => s + (e.npt_h || 0), 0), 0)
    const counts: Partial<Record<EventType, number>> = {}
    offs.forEach((w) => w.events.forEach((e) => { counts[e.type] = (counts[e.type] ?? 0) + 1 }))
    const topType = (Object.entries(counts) as [EventType, number][]).sort((a, b) => b[1] - a[1])[0]
    const risks: { formation: string; hazard: EventType; prevalence: number }[] = []
    risk.forEach((r) => RISK_TYPES.forEach((t) => {
      const c = r.risk[t]
      if (c.events) risks.push({ formation: r.formation, hazard: t, prevalence: c.prevalence })
    }))
    const topRisk = risks.sort((a, b) => b.prevalence - a.prevalence)[0] ?? null
    return { closest: offs[0], count: offs.length, totalEvents, totalNpt, topType, topRisk }
  }, [data, risk])

  return (
    <>
      <Intro>
        This page lines up the well you picked next to the wells around it, so you can see whether they hit
        the same rock layers at the same problem spots.
      </Intro>

      {plainSummary && (
        <div className="card" style={{ marginBottom: 12 }}>
          <h3>In plain terms</h3>
          <p style={{ margin: 0 }}>
            There {plainSummary.count === 1 ? 'is' : 'are'} <b>{plainSummary.count}</b> well{plainSummary.count === 1 ? '' : 's'} near{' '}
            <b>{data?.target.name}</b> within {radius.toFixed(1)} km.
            {plainSummary.closest && <> The closest, <b>{plainSummary.closest.name}</b>, is {plainSummary.closest.distance_km} km away.</>}{' '}
            Together they report <b>{plainSummary.totalEvents}</b> problems, totalling <b>{fmt(plainSummary.totalNpt)}</b> <Term term="NPT">downtime</Term> hours.
            {plainSummary.topType && <> The most common problem nearby is <b>{LABELS[plainSummary.topType[0]]}</b> ({plainSummary.topType[1]} times).</>}
            {plainSummary.topRisk && (
              <> The biggest risk ahead is <b>{LABELS[plainSummary.topRisk.hazard]}</b> in the <b>{plainSummary.topRisk.formation}</b> layer — it happened in{' '}
                <b>{pct(plainSummary.topRisk.prevalence)}</b> of nearby wells that drilled through it.</>
            )}
          </p>
          <div className="row" style={{ marginTop: 12 }}>
            <span className="small muted">Search radius</span>
            <input type="range" min={1} max={20} step={0.5} value={radius} onChange={(e) => setRadius(Number(e.target.value))} style={{ flex: 1, maxWidth: 260 }} aria-label="Search radius" />
            <b className="mono">{radius.toFixed(1)} km</b>
            {loading && <Spinner />}
          </div>
        </div>
      )}
      <ErrorBox error={err} />

      <Advanced title="Detailed well-log chart" summary="line up formations depth-by-depth, well by well" defaultOpen={false}>
      <div className="corr-controls" style={{ marginBottom: 12 }}>
          <label>Offset wells
            <select className="select" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              {[3, 5, 7, 9, 12].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <label>Depth datum
            <select className="select" value={datum} onChange={(e) => setDatum(e.target.value)}>
              <option value="tvd">True vertical depth</option>
              {data?.formations.filter((f) => f !== 'Alluvium').map((f) => <option key={f} value={f}>Flatten on top of {f}</option>)}
            </select>
          </label>
          <label><input type="checkbox" checked={showZones} onChange={(e) => setShowZones(e.target.checked)} /> Forecast hazard zones on target</label>
        </div>
        <div className="legend" style={{ marginBottom: 10 }}>
          {EVENT_TYPES.map((t) => (
            <span key={t} className="row" style={{ gap: 5 }}>
              <svg width="14" height="14"><Marker type={t} x={7} y={7} r={4} onClick={() => undefined} onEnter={() => undefined} onLeave={() => undefined} /></svg>{LABELS[t]}
            </span>
          ))}
          <span className="faint">· marker size = severity · shaded bars on the target = forecast from offsets · dashed tops = predicted</span>
        </div>

      <div className="svg-wrap" style={{ minHeight: 420 }}>
        {layout && data && (
          <svg width={width} height={height} role="img" aria-label="Well correlation panel">
            {/* depth grid + axis */}
            {Array.from({ length: Math.floor((layout.dmax - layout.dmin) / step) + 1 }, (_, i) => {
              const d = Math.ceil(layout.dmin / step) * step + i * step
              if (d > layout.dmax) return null
              const yy = TOP + ((d - layout.dmin) / (layout.dmax - layout.dmin)) * PLOT_H
              return (
                <g key={d}>
                  <line x1={48} x2={width - 10} y1={yy} y2={yy} stroke="#1a2a47" strokeWidth={1} />
                  <text x={44} y={yy + 3.5} textAnchor="end" fontSize={10.5} fill="#7f93b6" className="mono">{d}</text>
                </g>
              )
            })}
            <text x={44} y={TOP - 14} textAnchor="end" fontSize={10.5} fill="#90a4c6">{datum === 'tvd' ? 'TVD m' : `m vs ${datum.split(' ')[0]}`}</text>

            {/* correlation polygons */}
            {layout.shown.slice(0, -1).map((a, i) => {
              const b = layout.shown[i + 1]
              const ax = LEFT + i * (TRACK_W + GAP) + BAR_W
              const bx = LEFT + (i + 1) * (TRACK_W + GAP)
              return a.tops.map((ta, k) => {
                const tb = b.tops.find((t) => t.formation === ta.formation)
                if (!tb) return null
                const na = a.tops[k + 1]
                const nb = b.tops.find((t) => t.formation === na?.formation)
                const yA0 = layout.y(a, ta.tvd)
                const yB0 = layout.y(b, tb.tvd)
                const yA1 = na ? layout.y(a, na.tvd) : layout.y(a, a.td_tvd)
                const yB1 = nb ? layout.y(b, nb.tvd) : layout.y(b, b.td_tvd)
                return <polygon key={`${a.id}-${b.id}-${ta.formation}`} points={`${ax},${yA0} ${bx},${yB0} ${bx},${yB1} ${ax},${yA1}`} fill={formationColor(ta.formation)} opacity={0.17} />
              })
            })}

            {layout.shown.map((w, i) => {
              const x0 = LEFT + i * (TRACK_W + GAP)
              const isTarget = i === 0
              const yTd = layout.y(w, w.td_tvd)
              return (
                <g key={w.id}>
                  <text x={x0 + BAR_W / 2} y={TOP - 30} textAnchor="middle" fontSize={12.5} fontWeight={700} fill={isTarget ? '#f5a524' : '#e7eefb'}>{w.name}</text>
                  <text x={x0 + BAR_W / 2} y={TOP - 16} textAnchor="middle" fontSize={10.5} fill="#90a4c6">{isTarget ? (w.predicted ? 'target · predicted' : 'target') : `${w.distance_km?.toFixed(1)} km`}</text>
                  {w.tops.map((t, k) => {
                    const y0 = layout.y(w, t.tvd)
                    const y1 = w.tops[k + 1] ? layout.y(w, w.tops[k + 1].tvd) : yTd
                    const c0 = Math.max(TOP, y0)
                    const c1 = Math.min(TOP + PLOT_H, y1)
                    if (c1 <= c0) return null
                    return (
                      <g key={t.formation}>
                        <rect x={x0} y={c0} width={BAR_W} height={c1 - c0} fill={formationColor(t.formation)} opacity={w.predicted ? 0.6 : 0.9} />
                        {w.predicted && (t as { sigma_m?: number }).sigma_m ? (
                          <rect x={x0 - 3} y={y0 - ((t as { sigma_m?: number }).sigma_m as number) / (layout.dmax - layout.dmin) * PLOT_H} width={BAR_W + 6} height={2 * ((t as { sigma_m?: number }).sigma_m as number) / (layout.dmax - layout.dmin) * PLOT_H} fill="#fff" opacity={0.16} />
                        ) : null}
                        <line x1={x0 - 2} x2={x0 + BAR_W + 2} y1={y0} y2={y0} stroke="#0b1424" strokeWidth={1.4} strokeDasharray={w.predicted ? '4 3' : undefined} />
                        {isTarget && y0 >= TOP && y0 <= TOP + PLOT_H && (
                          <text x={x0 - 8} y={Math.min(y0 + 12, c1 - 3)} textAnchor="end" fontSize={10.5} fill={formationColor(t.formation)} fontWeight={600}>{t.formation}</text>
                        )}
                      </g>
                    )
                  })}
                  <line x1={x0 - 2} x2={x0 + BAR_W + 2} y1={yTd} y2={yTd} stroke="#e7eefb" strokeWidth={1.6} />
                  <text x={x0 + BAR_W / 2} y={yTd + 14} textAnchor="middle" fontSize={10} fill="#90a4c6">TD</text>

                  {/* forecast zones on the target */}
                  {isTarget && zonesTarget.map((z) => {
                    const laneX = x0 + BAR_W + 8 + EVENT_TYPES.indexOf(z.type) * LANE
                    const ya = layout.y(w, z.tvd_from)
                    const yb = layout.y(w, z.tvd_to)
                    if (yb < TOP || ya > TOP + PLOT_H) return null
                    return (
                      <rect key={z.id} x={laneX - 3.5} y={ya} width={7} height={Math.max(yb - ya, 5)} rx={2} fill={COLORS[z.type]} opacity={z.level === 'high' ? 0.6 : 0.34} stroke={COLORS[z.type]} strokeDasharray="2 2"
                        onMouseMove={(e) => setTip({ x: e.clientX, y: e.clientY, body: (
                          <>
                            <b>Forecast: {z.label}</b> <span className="muted">({z.level})</span>
                            <div className="small">{fmt(z.md_from)}–{fmt(z.md_to)} m MD · {z.formation}</div>
                            <div className="small">{z.n_wells} offsets · prevalence {pct(z.prevalence)}{z.mean_npt_h !== null ? ` · NPT ${fmt(z.mean_npt_h)} h` : ''}</div>
                          </>) })}
                        onMouseLeave={() => setTip(null)} />
                    )
                  })}
                  {/* events */}
                  {w.events.map((e) => {
                    const yy = layout.y(w, e.tvd)
                    if (yy < TOP || yy > TOP + PLOT_H) return null
                    const xx = x0 + BAR_W + 8 + EVENT_TYPES.indexOf(e.type) * LANE
                    return (
                      <Marker key={e.id} type={e.type} x={xx} y={yy} r={SEV_SIZE[e.severity] ?? 4}
                        onClick={() => setOpen(e.id)}
                        onEnter={(ev) => setTip({ x: ev.clientX, y: ev.clientY, body: (
                          <>
                            <b>{w.name}</b> · {LABELS[e.type]} <span className="muted">({e.severity})</span>
                            <div className="small">{e.summary}</div>
                            <div className="small faint">click for source text</div>
                          </>) })}
                        onLeave={() => setTip(null)} />
                    )
                  })}
                </g>
              )
            })}
          </svg>
        )}
        {!layout && !err && <div className="empty"><Spinner /></div>}
      </div>
      {layout && layout.hidden > 0 && <div className="faint small" style={{ marginTop: 6 }}>{layout.hidden} well(s) hidden: they did not reach the selected datum.</div>}
      </Advanced>

      <Advanced title="Formation-by-formation risk table" summary="exact percentages per rock layer" defaultOpen={false}>
        <h3 style={{ marginTop: 0 }}>Formation risk table — from offsets within {radius.toFixed(1)} km</h3>
        <div style={{ overflow: 'auto' }}>
          <table>
            <thead>
              <tr>
                <th>Formation</th><th>Predicted top (MD)</th><th>Offsets through it</th>
                {RISK_TYPES.map((t) => <th key={t}>{LABELS[t]}</th>)}
                <th>Expected NPT</th>
              </tr>
            </thead>
            <tbody>
              {risk.map((r) => (
                <tr key={r.formation}>
                  <td><span className="dot" style={{ background: formationColor(r.formation), marginRight: 8 }} /><b>{r.formation}</b></td>
                  <td className="mono">{fmt(r.top_md)} m{r.sigma_m > 0 && <span className="faint"> ±{fmt(r.sigma_m)}</span>}</td>
                  <td className="mono">{r.n_offsets}</td>
                  {RISK_TYPES.map((t) => {
                    const c = r.risk[t]
                    const a = Math.min(c.prevalence, 0.9)
                    return (
                      <td key={t} title={c.events ? `${c.events} events, mean NPT ${fmt(c.mean_npt_h)} h` : 'none recorded'}
                        style={{ background: c.events ? `rgba(${t === 'kick' || t === 'overpressure' ? '248,113,113' : '56,189,248'},${a * 0.55})` : undefined }}>
                        <span className="mono">{c.events ? pct(c.prevalence) : '–'}</span>
                      </td>
                    )
                  })}
                  <td className="mono"><b>{fmt(r.expected_npt_h, 1)} h</b></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="faint small" style={{ marginTop: 8 }}><Term term="prevalence">Prevalence</Term> = distance-weighted share of offsets that penetrated the formation and reported the hazard in it. Expected <Term term="NPT">NPT</Term> = Σ prevalence × mean NPT across hazards.</div>
      </Advanced>

      {tip && (
        <div className="tip" style={{ left: Math.min(tip.x + 14, window.innerWidth - 340), top: tip.y + 14 }}>{tip.body}</div>
      )}
      {open !== null && <EventDrawer id={open} onClose={() => setOpen(null)} onOpen={setOpen} />}
    </>
  )
}

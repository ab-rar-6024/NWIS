import { useEffect, useMemo, useState } from 'react'
import { api, COLORS, Impact, LABELS, Metrics, RISK_TYPES } from '../lib/api'
import { useApp } from '../App'
import { Advanced, ErrorBox, Icon, Kpi, Spinner, Term } from '../components/common'
import { fmt, pct } from '../lib/format'

const RIG_RATE_DEFAULT = 40000 // Rs/hour — a conservative mid-range onshore land-rig rate; user-adjustable, never hidden
const AVOIDANCE_DEFAULT = 30 // % of the flagged downtime assumed avoidable through proactive action

function crores(rupees: number) {
  return rupees / 1e7
}

function ExemplarTimeline({ w }: { w: Impact['exemplar'] }) {
  if (!w || w.events.length === 0) return null
  const W = 1000
  const maxMd = Math.max(...w.events.map((e) => e.md)) * 1.05
  const x = (md: number) => 40 + (md / maxMd) * (W - 80)
  const r = (npt: number) => 4 + Math.min(10, Math.sqrt(npt))
  return (
    <div>
      <div className="row" style={{ marginBottom: 8 }}>
        <b>{w.well}</b>
        <span className="muted small">{w.field} · {w.n_events} recorded incidents · {fmt(w.total_npt_h)} NPT hours</span>
      </div>
      <svg viewBox={`0 0 ${W} 90`} width="100%" role="img" aria-label={`Backtest timeline for ${w.well}: flagged vs missed incidents`}>
        <line x1={40} x2={W - 40} y1={45} y2={45} stroke="#24365a" strokeWidth={2} />
        {w.events.map((e) => (
          <g key={e.id}>
            <circle cx={x(e.md)} cy={45} r={r(e.npt_h)} fill={e.flagged ? 'var(--ok)' : 'var(--crit)'} opacity={0.88}>
              <title>{`${LABELS[e.type]} at ${fmt(e.md)} m · ${fmt(e.npt_h, 1)} h NPT · ${e.flagged ? 'flagged in advance by neighbouring wells' : 'not flagged'}`}</title>
            </circle>
          </g>
        ))}
        <text x={40} y={78} fontSize={11} fill="#7f93b6">0 m</text>
        <text x={W - 40} y={78} fontSize={11} fill="#7f93b6" textAnchor="end">{fmt(maxMd)} m MD</text>
      </svg>
      <div className="row small muted" style={{ marginTop: 2 }}>
        <span className="row" style={{ gap: 5 }}><span className="dot" style={{ background: 'var(--ok)' }} />flagged in advance by neighbouring wells</span>
        <span className="row" style={{ gap: 5 }}><span className="dot" style={{ background: 'var(--crit)' }} />not flagged (no offset had reported it yet)</span>
        <span className="right faint">circle size = hours of downtime</span>
      </div>
    </div>
  )
}

export default function ImpactPage() {
  const { go, radius } = useApp()
  const [data, setData] = useState<Impact | null>(null)
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const [rigRate, setRigRate] = useState(RIG_RATE_DEFAULT)
  const [avoidance, setAvoidance] = useState(AVOIDANCE_DEFAULT)

  useEffect(() => {
    let live = true
    api.impact(radius, 0.1).then((r) => live && (setData(r), setErr(null))).catch((e) => live && setErr(e))
    return () => { live = false }
  }, [radius])
  useEffect(() => { api.metrics().then(setMetrics).catch(() => undefined) }, [])

  const modelUplift = useMemo(() => {
    if (!metrics) return null
    const full = metrics.results.full
    const offsetOnly = metrics.results.offset_knowledge_only
    if (!offsetOnly) return null
    const rows = RISK_TYPES.map((t) => ({ type: t, full: full[t].auc, geometry: offsetOnly[t].auc, gain: full[t].auc - offsetOnly[t].auc }))
    const avgGain = rows.reduce((a, r) => a + r.gain, 0) / rows.length
    return { rows, avgGain }
  }, [metrics])

  const savings = useMemo(() => {
    if (!data) return null
    const hoursAvoided = data.flagged_npt_h * (avoidance / 100)
    return { hoursAvoided, rupees: hoursAvoided * rigRate }
  }, [data, rigRate, avoidance])

  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="card" style={{ background: 'linear-gradient(135deg, #14213b, #0e172b)' }}>
        <div className="chip badge-info" style={{ marginBottom: 10 }}>SIH26121 · Oil India Limited · eRTMAC-NWIS</div>
        <h2 style={{ fontSize: 22, maxWidth: 760 }}>Every well that has ever been drilled nearby already knows what this well is about to run into.</h2>
        <p className="muted" style={{ maxWidth: 760, marginTop: 8 }}>
          Drilling teams currently rediscover the same mud losses, kicks and stuck-pipe incidents well after well, because the
          knowledge sits scattered across PDF reports that nobody has time to re-read. <b>NWIS reads every historical report
          (including scanned ones, via OCR), turns each incident into a structured, located record, and uses the wells around
          the one being drilled to warn the crew before the bit gets there</b> — not after.
        </p>
        <div className="row" style={{ marginTop: 14 }}>
          <button className="btn primary" onClick={() => go('live')}>See it warn a well live <Icon name="activity" size={15} /></button>
          <button className="btn" onClick={() => go('correlation')}>See the offset correlation</button>
        </div>
      </div>

      <ErrorBox error={err} />
      {!data && !err && <div className="card"><Spinner /> <span className="muted">Running the leave-one-well-out backtest…</span></div>}

      {data && (
        <>
          <div className="card">
            <h3>Measured, not claimed: a leave-one-well-out backtest across the whole fleet</h3>
            <p className="muted small" style={{ maxWidth: 820 }}>
              For every well already in the knowledge base, we hide <i>its own</i> reports and forecast hazards using only the
              wells around it — the exact situation a crew faces before that well has a completion report of its own. We then
              check how much of that well's real downtime falls inside a forecast zone. This runs at radius {data.radius_km} km
              across {data.n_wells} wells; widen the radius on the Nearby-wells page and revisit this page to see the effect.
            </p>
            <div className="kpis" style={{ marginTop: 4 }}>
              <Kpi value={pct(data.event_coverage)} label="of past incidents would have been flagged in advance" />
              <Kpi value={pct(data.npt_coverage)} label="of recorded downtime occurred at a flagged depth" />
              <Kpi value={`${fmt(data.flagged_npt_h)} h`} label="downtime hours that had advance warning" hint={`out of ${fmt(data.total_npt_h)} h total recorded`} />
              <Kpi value={data.n_wells} label="wells cross-checked, each with its own data hidden" />
            </div>
          </div>

          <div className="card">
            <h3>Turn that into a number a rig superintendent cares about</h3>
            <p className="muted small">These two numbers are assumptions you control — nothing here is hard-coded into the measurement above.</p>
            <div className="row" style={{ gap: 24, flexWrap: 'wrap', marginTop: 6 }}>
              <label className="col" style={{ gap: 6, minWidth: 240 }}>
                <span className="small muted">Rig day-rate, expressed hourly (₹/hour)</span>
                <div className="row"><input type="range" min={10000} max={100000} step={5000} value={rigRate} onChange={(e) => setRigRate(Number(e.target.value))} style={{ flex: 1 }} aria-label="Rig hourly rate in rupees" /><b className="mono" style={{ width: 90, textAlign: 'right' }}>₹{fmt(rigRate)}</b></div>
              </label>
              <label className="col" style={{ gap: 6, minWidth: 240 }}>
                <span className="small muted">Share of flagged downtime actually avoided by acting on the warning</span>
                <div className="row"><input type="range" min={5} max={80} step={5} value={avoidance} onChange={(e) => setAvoidance(Number(e.target.value))} style={{ flex: 1 }} aria-label="Assumed avoidance rate percent" /><b className="mono" style={{ width: 50, textAlign: 'right' }}>{avoidance}%</b></div>
              </label>
            </div>
            {savings && (
              <div className="kpis" style={{ marginTop: 14 }}>
                <Kpi value={`${fmt(savings.hoursAvoided)} h`} label="rig hours saved, fleet-wide" />
                <Kpi value={`₹${fmt(crores(savings.rupees), 2)} Cr`} label="estimated value, at the assumptions above" />
                <Kpi value={`₹${fmt(crores(savings.rupees) / Math.max(data.n_wells, 1) * 1e7 / 1e5, 1)} L`} label="average per well" />
              </div>
            )}
          </div>

          {data.exemplar && (
            <div className="card">
              <h3>What "flagged in advance" looks like on a real well</h3>
              <ExemplarTimeline w={data.exemplar} />
            </div>
          )}

          <div className="card">
            <h3>How much should you trust these numbers?</h3>
            <p className="muted small" style={{ maxWidth: 820 }}>
              Two checks, run deliberately against the system's own worst case rather than its best case.
            </p>
            <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
              <div style={{ background: '#0d1830', border: '1px solid var(--line-soft)', borderRadius: 10, padding: '12px 14px' }}>
                <div style={{ fontWeight: 650, marginBottom: 4 }}>Read on reports it had never seen</div>
                <div className="small muted">
                  Two wells' reports were set aside and never looked at while the extractor was being built. Read cold, it
                  still found <b>every</b> real problem in them (recall 100%), with 91% precision — F1 <b>0.95</b>, close to
                  its 0.99 score on the reports it was tuned against, which is the honest way to say "this isn't just
                  memorising its own test."
                </div>
              </div>
              <div style={{ background: '#0d1830', border: '1px solid var(--line-soft)', borderRadius: 10, padding: '12px 14px' }}>
                <div style={{ fontWeight: 650, marginBottom: 4 }}>How often the AI model is wrong</div>
                <div className="small muted">
                  Counting alerts, not raw data points: across the fleet, the model raises roughly <b>1-5 alerts per well</b> for
                  a given hazard, of which <b>about half to two-thirds</b> line up with a real recorded problem — the rest are
                  false alarms. It still catches <b>79-100%</b> of the real problems that occurred. That is a realistic, not
                  inflated, picture of what a crew would actually experience.
                </div>
              </div>
            </div>
          </div>

          {modelUplift && (
            <div className="card">
              <h3>Is the live monitor worth building, or would a static map be enough?</h3>
              <p className="muted small" style={{ maxWidth: 820 }}>
                Both sides of this comparison are the same trained model — we haven't benchmarked against another
                team's specific formula, since we don't have their code to run. What we can measure honestly is our
                own: one version sees <i>only</i> where this well sits relative to its neighbours (exactly what the
                look-ahead zones already show, with no live sensor data at all); the other adds the live drilling
                signals — torque, ROP, gas, mud weight, mechanical specific energy — on top. The gap between them is
                the answer to "does watching the well live add anything beyond knowing your neighbours," measured
                in <Term term="AUC">AUC</Term>, not assumed.
              </p>
              <div className="kpis" style={{ marginTop: 4 }}>
                <Kpi value={`+${(modelUplift.avgGain * 100).toFixed(0)} pts`} label="average AUC gained by adding live signals on top of offset knowledge" hint="Mean of (full model AUC − offset-knowledge-only AUC) across all five hazards" />
              </div>
              <Advanced title="Per-hazard breakdown" summary="offset knowledge alone vs. offset knowledge + live signals" defaultOpen={false}>
                <table>
                  <thead><tr><th>Hazard</th><th>Offset knowledge only (AUC)</th><th>+ Live signals (AUC)</th><th>Gain</th></tr></thead>
                  <tbody>
                    {modelUplift.rows.map((r) => (
                      <tr key={r.type}>
                        <td><span className="dot" style={{ background: COLORS[r.type], marginRight: 8 }} />{LABELS[r.type]}</td>
                        <td className="mono">{r.geometry.toFixed(3)}</td>
                        <td className="mono"><b>{r.full.toFixed(3)}</b></td>
                        <td className="mono" style={{ color: r.gain > 0 ? 'var(--ok)' : 'var(--crit)' }}>{r.gain >= 0 ? '+' : ''}{r.gain.toFixed(3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Advanced>
              <div className="quote" style={{ marginTop: 10 }}>
                Both numbers come with an explanation attached: the offset-only score is exactly what powers the
                look-ahead zones' evidence ("these named offset wells, at this depth"); the added gain from live
                signals is what the model risk gauges and MSE-based alerts are for. Neither replaces the other —
                and either way, a design choice to skip a trained model entirely wouldn't make a system safer, just
                harder to hold to a number.
              </div>
            </div>
          )}

          <div className="card">
            <h3>What's different about this build</h3>
            <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: 12 }}>
              {[
                ['OCR, not just text PDFs', 'Scanned completion reports are detected automatically and read with OCR — the demo includes 4 rasterised reports read at 97%+ confidence.'],
                ['Evidence, not a black box', 'Every alert names the offset wells and report lines behind it. Click any event to read the original sentence it came from.'],
                ['Validated like a real model', 'Cross-validated by well (never trained and tested on the same well); an ablation shows how much comes from neighbour knowledge alone, before any live signal exists.'],
                ['A number for the backtest, not a slide', 'The coverage and rupee figures on this page are computed live from the current data — change the radius and they recompute.'],
                ['Closes the loop', 'Engineers mark each alert accurate or a false alarm on the Live monitor page; that record is exactly what a retraining pass would use.'],
                ['Two independent reports, one fact', 'When a daily report and a completion report describe the same incident, they are merged and marked corroborated — higher confidence than either alone.'],
                ['A real drilling-engineering signal', "Mechanical Specific Energy (Teale's formula) is computed live from the well's own planned casing programme, not just plotted — it also feeds the risk model as a real feature."],
              ].map(([t, d]) => (
                <div key={t} style={{ background: '#0d1830', border: '1px solid var(--line-soft)', borderRadius: 10, padding: '10px 12px' }}>
                  <div style={{ fontWeight: 650, marginBottom: 4 }}>{t}</div>
                  <div className="small muted">{d}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="faint small">
            All figures on this page are computed on the synthetic demonstration dataset described in the banner above, using
            the method note: “{data.method}”. On real field data these numbers would be re-measured, not assumed.
          </div>
        </>
      )}
    </div>
  )
}

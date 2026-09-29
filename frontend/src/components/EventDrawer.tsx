import { useEffect, useState } from 'react'
import { api, COLORS, EventDetail } from '../lib/api'
import { actionText, fmt, fmtMd, pct } from '../lib/format'
import { Drawer, ErrorBox, SeverityChip, Spinner, TypeChip } from './common'

const DETAIL_LABELS: Record<string, string> = {
  rate_m3h: 'Loss rate (m³/h)', residual_m3h: 'Residual loss (m³/h)', severity: 'Loss class', lcm_vol_m3: 'LCM volume (m³)', lcm_ppb: 'LCM conc. (ppb)',
  lcm_type: 'LCM type', gain_m3: 'Pit gain (m³)', sidpp_bar: 'SIDPP (bar)', sicp_bar: 'SICP (bar)', mw0: 'MW before (SG)', mw1: 'MW after (SG)',
  method: 'Kill method', overpull_t: 'Overpull (t)', mechanism: 'Mechanism', gas_units: 'Gas (units)', pp_sg: 'Pore pressure (SG)',
  peak_knm: 'Peak torque (kNm)', baseline_knm: 'Baseline torque (kNm)', squeeze_vol_m3: 'Squeeze volume (m³)', kind: 'Issue', casing: 'Casing',
  tool: 'Lost tool', recovered: 'Recovered',
}

export function EventDrawer({ id, onClose, onOpen }: { id: number; onClose: () => void; onOpen?: (id: number) => void }) {
  const [ev, setEv] = useState<EventDetail | null>(null)
  const [err, setErr] = useState<unknown>(null)
  useEffect(() => {
    setEv(null)
    setErr(null)
    api.event(id).then(setEv).catch(setErr)
  }, [id])

  return (
    <Drawer
      onClose={onClose}
      title={ev ? ev.summary.split(':')[0] : 'Event'}
      sub={ev ? `${ev.well} · ${ev.formation ?? 'formation n/a'}` : undefined}
    >
      <ErrorBox error={err} />
      {!ev && !err && <Spinner />}
      {ev && (
        <>
          <div className="row">
            <TypeChip type={ev.type} />
            <SeverityChip severity={ev.severity} />
            {ev.corroborated && <span className="chip badge-ok" title="Reported in both the daily and the completion report">corroborated</span>}
            <span className="chip" title="Extraction confidence">confidence {pct(ev.confidence)}</span>
            {ev.depth_source !== 'explicit' && <span className="chip badge-warn" title="Depth not stated in the text; taken from the report day">approx. depth</span>}
          </div>
          <div className="kv">
            <div><div className="k">Depth MD</div><div className="val">{fmtMd(ev.md)}</div></div>
            <div><div className="k">Depth TVD</div><div className="val">{fmtMd(ev.tvd)}</div></div>
            <div><div className="k">NPT</div><div className="val">{ev.npt_h !== null ? `${fmt(ev.npt_h, 1)} h` : '–'}</div></div>
            <div><div className="k">Date</div><div className="val">{ev.date ?? '–'}</div></div>
            <div><div className="k">Outcome</div><div className="val">{ev.outcome ? actionText(ev.outcome) : '–'}</div></div>
            <div><div className="k">Actions taken</div><div className="val">{ev.mitigations.length ? ev.mitigations.map(actionText).join(', ') : '–'}</div></div>
            {Object.entries(ev.details).filter(([k]) => DETAIL_LABELS[k]).map(([k, v]) => (
              <div key={k}><div className="k">{DETAIL_LABELS[k]}</div><div className="val">{typeof v === 'boolean' ? (v ? 'yes' : 'no') : String(v)}</div></div>
            ))}
          </div>
          <div>
            <div className="muted small" style={{ marginBottom: 6 }}>Source text (as extracted from the reports)</div>
            <div className="quote">{ev.description}</div>
            <div className="muted small" style={{ marginTop: 6 }}>
              {ev.sources.map((s, i) => <span key={i} className="chip" style={{ marginRight: 6 }}>{s.kind}{s.page ? ` p.${s.page}` : ''}{s.filename ? ` · ${s.filename}` : ''}</span>)}
            </div>
          </div>
          <div>
            <div className="muted small" style={{ marginBottom: 6 }}>Same hazard, same formation in nearby wells</div>
            {ev.similar.length === 0 && <div className="faint small">No comparable events within 8 km.</div>}
            <div className="col" style={{ gap: 6 }}>
              {ev.similar.map((s) => (
                <button key={s.id} className="result" style={{ textAlign: 'left' }} onClick={() => onOpen?.(s.id)}>
                  <div className="row">
                    <span className="dot" style={{ background: COLORS[s.type] }} />
                    <b>{s.well}</b><span className="muted small">{s.distance_km} km away · {fmtMd(s.md)}</span>
                    <span className="right"><SeverityChip severity={s.severity} /></span>
                  </div>
                  <div className="small muted" style={{ marginTop: 4 }}>{s.summary}</div>
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </Drawer>
  )
}

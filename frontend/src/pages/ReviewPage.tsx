import { useCallback, useEffect, useState } from 'react'
import { api, ReviewEvent, ReviewQueue } from '../lib/api'
import { EventDrawer } from '../components/EventDrawer'
import { ErrorBox, Icon, Intro, Kpi, SeverityChip, Spinner, TypeChip } from '../components/common'
import { fmt, pct } from '../lib/format'

type Tab = 'pending' | 'confirmed' | 'rejected'

export default function ReviewPage() {
  const [tab, setTab] = useState<Tab>('pending')
  const [q, setQ] = useState<ReviewQueue | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const [open, setOpen] = useState<number | null>(null)

  const load = useCallback(() => {
    api.reviewQueue(tab).then((r) => { setQ(r); setErr(null) }).catch(setErr)
  }, [tab])
  useEffect(() => { setQ(null); load() }, [load])

  const decide = async (e: ReviewEvent, status: 'confirmed' | 'rejected' | 'pending') => {
    try { await api.reviewEvent(e.id, status); load() } catch (x) { setErr(x) }
  }

  const c = q?.counts
  return (
    <div className="col" style={{ gap: 14 }}>
      <Intro>
        Extraction is automatic, but not every event is equally trustworthy. This queue lists events read with low
        confidence, with a depth inferred from the report day, or reported in a single document only. An engineer
        confirms or rejects each one; the decisions are what a retraining pass would learn from.
      </Intro>
      <ErrorBox error={err} />
      {q && c && (
        <div className="kpis" style={{ marginBottom: 0 }}>
          <Kpi value={`${q.total_flagged} / ${q.total_events}`} label="events flagged for a second look" />
          <Kpi value={c.pending} label="waiting for review" />
          <Kpi value={c.confirmed} label="confirmed" />
          <Kpi value={c.rejected} label="rejected" />
        </div>
      )}
      <div className="row" style={{ gap: 6 }}>
        {(['pending', 'confirmed', 'rejected'] as Tab[]).map((t) => (
          <button key={t} className="chip btn-chip" aria-pressed={tab === t} onClick={() => setTab(t)}>{t[0].toUpperCase() + t.slice(1)}</button>
        ))}
      </div>
      <div className="card">
        {!q && !err && <Spinner />}
        {q && q.events.length === 0 && <div className="faint small" style={{ padding: 14 }}>Nothing here.</div>}
        {q && q.events.length > 0 && (
          <div style={{ overflow: 'auto', maxHeight: 620 }}>
            <table>
              <thead><tr><th>Hazard</th><th>Well</th><th>Depth</th><th>Severity</th><th>Conf.</th><th>Why flagged</th><th></th></tr></thead>
              <tbody>
                {q.events.map((e) => (
                  <tr key={e.id}>
                    <td className="click" onClick={() => setOpen(e.id)}><TypeChip type={e.type} /></td>
                    <td className="click" onClick={() => setOpen(e.id)}>{e.well}</td>
                    <td className="mono">{fmt(e.md)} m</td>
                    <td><SeverityChip severity={e.severity} /></td>
                    <td className="mono">{pct(e.confidence)}</td>
                    <td className="small muted">{e.reasons.join(' · ')}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      {tab === 'pending' ? (
                        <span className="row" style={{ gap: 6 }}>
                          <button className="btn small" onClick={() => decide(e, 'confirmed')}><Icon name="check" size={13} /> Confirm</button>
                          <button className="btn small danger" onClick={() => decide(e, 'rejected')}><Icon name="close" size={13} /> Reject</button>
                        </span>
                      ) : (
                        <button className="btn small" onClick={() => decide(e, 'pending')}>Undo</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {open !== null && <EventDrawer id={open} onClose={() => setOpen(null)} onOpen={setOpen} />}
    </div>
  )
}

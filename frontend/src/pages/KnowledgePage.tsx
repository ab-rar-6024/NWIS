import { useEffect, useState } from 'react'
import { api, AskResult, COLORS, EVENT_TYPES, EventType, Lesson, LABELS, SearchResult } from '../lib/api'
import { EventDrawer } from '../components/EventDrawer'
import { ErrorBox, Intro, SeverityChip, Spinner, TypeChip } from '../components/common'
import { actionText, fmt, formationColor, pct, snippetParts } from '../lib/format'

type Tab = 'search' | 'lessons' | 'ask'

function Snippet({ s }: { s: string }) {
  return <>{snippetParts(s).map((p, i) => (p.hit ? <mark key={i}>{p.text}</mark> : <span key={i}>{p.text}</span>))}</>
}

const KIND_LABEL = { event: 'Event', ddr: 'Daily report', lesson: 'Lesson' } as const

function SearchTab({ formations, onOpen }: { formations: string[]; onOpen: (id: number) => void }) {
  const [q, setQ] = useState('lost circulation')
  const [type, setType] = useState<EventType | ''>('')
  const [fm, setFm] = useState('')
  const [kinds, setKinds] = useState<string[]>(['event', 'ddr', 'lesson'])
  const [res, setRes] = useState<SearchResult[] | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (q.trim().length < 2) { setRes(null); return }
    let live = true
    setBusy(true)
    const t = setTimeout(() => {
      api.search({ q, type: type || undefined, formation: fm || undefined, kinds: kinds.join(','), limit: 40 })
        .then((r) => live && (setRes(r.results), setErr(null)))
        .catch((e) => live && setErr(e))
        .finally(() => live && setBusy(false))
    }, 250)
    return () => { live = false; clearTimeout(t) }
  }, [q, type, fm, kinds])

  const toggle = (k: string) => setKinds((cur) => (cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k]))

  return (
    <div className="col">
      <div className="card">
        <div className="row">
          <input className="input" style={{ flex: 1, minWidth: 220 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search events, daily reports and lessons - e.g. stuck pipe jars Barail" aria-label="Search" />
          <select className="select" value={fm} onChange={(e) => setFm(e.target.value)} aria-label="Formation filter">
            <option value="">All formations</option>
            {formations.map((f) => <option key={f}>{f}</option>)}
          </select>
          {busy && <Spinner />}
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <button className="chip btn-chip" aria-pressed={type === ''} onClick={() => setType('')}>All hazards</button>
          {EVENT_TYPES.map((t) => (
            <button key={t} className="chip btn-chip" aria-pressed={type === t} onClick={() => setType(type === t ? '' : t)}>
              <span className="dot" style={{ background: COLORS[t] }} />{LABELS[t]}
            </button>
          ))}
          <span className="right row" style={{ gap: 6 }}>
            {(['event', 'ddr', 'lesson'] as const).map((k) => (
              <button key={k} className="chip btn-chip" aria-pressed={kinds.includes(k)} onClick={() => toggle(k)}>{KIND_LABEL[k]}</button>
            ))}
          </span>
        </div>
        <div className="faint small" style={{ marginTop: 8 }}>Understands synonyms (loss / lost circulation, kick / influx, stuck / pack-off) and stems words. Hazard filter applies to structured events.</div>
      </div>
      <ErrorBox error={err} />
      {res && res.length === 0 && <div className="empty">No matches.</div>}
      <div className="col" style={{ gap: 8 }}>
        {res?.map((r) => (
          <div key={r.ref} className="result" onClick={() => r.kind === 'event' && onOpen(r.id)} style={{ cursor: r.kind === 'event' ? 'pointer' : 'default' }}>
            <div className="row">
              <span className="chip badge-info">{KIND_LABEL[r.kind]}</span>
              {r.etype && <TypeChip type={r.etype} />}
              <b>{r.well}</b>
              {r.formation && <span className="chip"><span className="dot" style={{ background: formationColor(r.formation) }} />{r.formation}</span>}
              {r.md !== null && <span className="mono muted small">{fmt(r.md)} m</span>}
              {r.kind === 'ddr' && <span className="muted small">report {r.report_no} · {r.date}</span>}
              <span className="right row" style={{ gap: 6 }}>
                {r.severity && <SeverityChip severity={r.severity} />}
                {r.corroborated && <span className="chip badge-ok">2 sources</span>}
              </span>
            </div>
            {r.summary && <div style={{ marginTop: 6, fontWeight: 600 }}>{r.summary}</div>}
            <div className="muted small" style={{ marginTop: 4 }}><Snippet s={r.snip} /></div>
          </div>
        ))}
      </div>
    </div>
  )
}

function LessonCard({ l, onOpen }: { l: Lesson; onOpen: (id: number) => void }) {
  return (
    <div className="card">
      <div className="row" style={{ marginBottom: 8 }}>
        <span className="dot" style={{ background: COLORS[l.hazard] }} />
        <h2 style={{ fontSize: 15 }}>{l.label}</h2>
        <span className="chip" style={{ color: formationColor(l.formation) }}>{l.formation}</span>
        <span className="right chip badge-warn" title="Total non-productive time recorded">{fmt(l.total_npt_h)} NPT h</span>
      </div>
      <div className="grid" style={{ gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
        <div className="kv" style={{ display: 'contents' }}>
          <div><div className="k muted small">Wells affected</div><b className="mono">{l.n_wells}/{l.n_wells_penetrating}</b> <span className="muted small">({pct(l.prevalence)})</span></div>
          <div><div className="k muted small">Events</div><b className="mono">{l.n_events}</b></div>
          <div><div className="k muted small">Mean NPT</div><b className="mono">{fmt(l.mean_npt_h, 1)} h</b></div>
        </div>
      </div>
      <div className="bar" style={{ margin: '10px 0' }}><i style={{ width: pct(l.prevalence ?? 0), background: COLORS[l.hazard] }} /></div>
      {l.depth_below_top_m && (
        <div className="small muted">Typically {fmt(l.depth_below_top_m.p10)}–{fmt(l.depth_below_top_m.p90)} m below the formation top (median {fmt(l.depth_below_top_m.median)} m).</div>
      )}
      {l.detail.loss_rate_m3h && <div className="small muted">Loss rates: median {fmt(l.detail.loss_rate_m3h.median, 1)}, max {fmt(l.detail.loss_rate_m3h.max, 1)} m³/h.</div>}
      {l.detail.mw_after_sg && <div className="small muted">Mud weight after event: {l.detail.mw_after_sg.min}–{l.detail.mw_after_sg.max} SG (median {fmt(l.detail.mw_after_sg.median, 2)}).</div>}
      {l.detail.mechanisms && <div className="small muted">Mechanisms: {Object.entries(l.detail.mechanisms).map(([k, v]) => `${k} (${v})`).join(', ')}.</div>}
      {l.actions.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div className="muted small" style={{ marginBottom: 4 }}>What worked (ranked by success, then downtime)</div>
          {l.actions.slice(0, 4).map((a) => (
            <div key={a.action} className="gauge" style={{ gridTemplateColumns: '150px 1fr 100px' }}>
              <span>{a.text}</span>
              <div className="bar"><i style={{ width: pct(a.success_rate), background: a.success_rate >= 0.7 ? 'var(--ok)' : a.success_rate >= 0.4 ? 'var(--warn)' : 'var(--crit)' }} /></div>
              <span className="mono small muted">{a.success}/{a.n}{a.mean_npt_h !== null ? ` · ${fmt(a.mean_npt_h)}h` : ''}</span>
            </div>
          ))}
        </div>
      )}
      <div className="quote" style={{ marginTop: 10 }}>{l.recommendation}</div>
      {l.documented_lessons.length > 0 && (
        <div className="small muted" style={{ marginTop: 8 }}>
          Lessons written in completion reports: {l.documented_lessons.map((d) => `“${d.text}” (${d.well})`).join(' ')}
        </div>
      )}
      <div className="row" style={{ marginTop: 10 }}>
        <span className="muted small">Worst cases:</span>
        {l.event_ids.slice(0, 4).map((id, i) => <button key={id} className="btn small" onClick={() => onOpen(id)}>#{i + 1}</button>)}
      </div>
    </div>
  )
}

function LessonsTab({ formations, onOpen }: { formations: string[]; onOpen: (id: number) => void }) {
  const [fm, setFm] = useState('Kopili Shale')
  const [hz, setHz] = useState<EventType | ''>('')
  const [lessons, setLessons] = useState<Lesson[] | null>(null)
  const [err, setErr] = useState<unknown>(null)
  useEffect(() => {
    let live = true
    api.lessons(fm || undefined, hz || undefined).then((r) => live && (setLessons(r.lessons), setErr(null))).catch((e) => live && setErr(e))
    return () => { live = false }
  }, [fm, hz])
  return (
    <div className="col">
      <div className="card row">
        <select className="select" value={fm} onChange={(e) => setFm(e.target.value)} aria-label="Formation">
          <option value="">All formations</option>
          {formations.map((f) => <option key={f}>{f}</option>)}
        </select>
        <select className="select" value={hz} onChange={(e) => setHz(e.target.value as EventType | '')} aria-label="Hazard">
          <option value="">All hazards</option>
          {EVENT_TYPES.map((t) => <option key={t} value={t}>{LABELS[t]}</option>)}
        </select>
        <span className="muted small">Lessons are aggregated from every structured event; ordered by total non-productive time.</span>
      </div>
      <ErrorBox error={err} />
      {!lessons && <Spinner />}
      {lessons && lessons.length === 0 && <div className="empty">No recorded events for this selection.</div>}
      <div className="lesson-grid">{lessons?.map((l) => <LessonCard key={`${l.formation}-${l.hazard}`} l={l} onOpen={onOpen} />)}</div>
    </div>
  )
}

function AskTab({ onOpen }: { onOpen: (id: number) => void }) {
  const [q, setQ] = useState('What problems should we expect in the Sylhet Limestone?')
  const [res, setRes] = useState<AskResult | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const run = () => {
    setBusy(true)
    api.ask(q).then((r) => (setRes(r), setErr(null))).catch(setErr).finally(() => setBusy(false))
  }
  const examples = ['What happens when drilling the Kopili shale?', 'How were kicks handled in the Kopili?', 'Stuck pipe in the Barail coal: what worked?', 'What mud losses occur in the Tipam sandstone?']
  return (
    <div className="col">
      <div className="card">
        <div className="row">
          <input className="input" style={{ flex: 1, minWidth: 240 }} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && run()} aria-label="Question" />
          <button className="btn primary" onClick={run} disabled={busy || q.trim().length < 3}>Ask</button>
          {busy && <Spinner />}
        </div>
        <div className="row" style={{ marginTop: 10 }}>{examples.map((e) => <button key={e} className="chip btn-chip" onClick={() => setQ(e)}>{e}</button>)}</div>
        <div className="faint small" style={{ marginTop: 8 }}>Answers are assembled only from recorded offset events (no generative guessing): each statement traces back to real reports.</div>
      </div>
      <ErrorBox error={err} />
      {res && (
        <div className="col">
          <div className="card">
            <h3>Answer {res.formation && <span className="chip" style={{ marginLeft: 8 }}>{res.formation}</span>}</h3>
            <div className="col" style={{ gap: 8 }}>{res.answer.map((a, i) => <div key={i} className="quote">{a}</div>)}</div>
          </div>
          {res.lessons.length > 0 && <div className="lesson-grid">{res.lessons.map((l) => <LessonCard key={`${l.formation}-${l.hazard}`} l={l} onOpen={onOpen} />)}</div>}
        </div>
      )}
    </div>
  )
}

export default function KnowledgePage() {
  const [tab, setTab] = useState<Tab>('search')
  const [formations, setFormations] = useState<string[]>([])
  const [open, setOpen] = useState<number | null>(null)
  useEffect(() => { api.lessons().then((r) => setFormations(r.formations)).catch(() => undefined) }, [])
  return (
    <div className="col" style={{ gap: 14 }}>
      <Intro>
        Three ways to use what every well has learned: search for a specific problem, browse what usually
        works for a given rock layer, or just type a question in your own words.
      </Intro>
      <div className="tabs" role="tablist">
        {([['search', 'Search'], ['lessons', 'Lessons learned'], ['ask', 'Ask the knowledge base']] as [Tab, string][]).map(([id, label]) => (
          <button key={id} className="tab" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>{label}</button>
        ))}
      </div>
      {tab === 'search' && <SearchTab formations={formations} onOpen={setOpen} />}
      {tab === 'lessons' && <LessonsTab formations={formations} onOpen={setOpen} />}
      {tab === 'ask' && <AskTab onOpen={setOpen} />}
      {open !== null && <EventDrawer id={open} onClose={() => setOpen(null)} onOpen={setOpen} />}
    </div>
  )
}

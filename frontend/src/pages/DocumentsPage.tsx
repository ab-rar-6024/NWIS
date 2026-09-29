import { useCallback, useEffect, useRef, useState } from 'react'
import { api, DocRow, IngestResult, LABELS, Metrics, RISK_TYPES } from '../lib/api'
import { useApp } from '../App'
import { EventDrawer } from '../components/EventDrawer'
import { Advanced, ErrorBox, Icon, Intro, SeverityChip, Spinner, Term, TypeChip } from '../components/common'
import { fmt, pct } from '../lib/format'

function Result({ r, onOpen }: { r: IngestResult; onOpen: (id: number) => void }) {
  return (
    <div className="card" style={{ borderColor: 'rgba(52,211,153,.4)' }}>
      <div className="row" style={{ marginBottom: 8 }}>
        <Icon name="check" size={18} />
        <h2 style={{ fontSize: 16 }}>{r.kind} for {r.well} processed</h2>
        {r.ocr_pages.length > 0 && <span className="chip badge-info">OCR on {r.ocr_pages.length} page(s) · confidence {pct(r.ocr_confidence ?? 0)}</span>}
        <span className="chip">{r.events} mentions → {r.consolidated} consolidated events for this well</span>
      </div>
      <div style={{ overflow: 'auto', maxHeight: 340 }}>
        <table>
          <thead><tr><th>Hazard</th><th>Depth</th><th>Formation</th><th>Severity</th><th>NPT</th><th>Conf.</th><th>Summary</th></tr></thead>
          <tbody>
            {r.events_detail.map((e) => (
              <tr key={e.id} className="click" onClick={() => onOpen(e.id)}>
                <td><TypeChip type={e.type} /></td>
                <td className="mono">{fmt(e.md)} m</td>
                <td>{e.formation ?? '–'}</td>
                <td><SeverityChip severity={e.severity} /></td>
                <td className="mono">{e.npt_h !== null ? `${fmt(e.npt_h, 1)} h` : '–'}</td>
                <td className="mono">{pct(e.confidence)}{e.corroborated ? ' ✓✓' : ''}</td>
                <td className="small muted">{e.summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="faint small" style={{ marginTop: 6 }}>The well now appears on the map and joins offset analytics. ✓✓ = confirmed by two documents.</div>
    </div>
  )
}

function ModelCard({ m }: { m: Metrics }) {
  const full = m.results.full
  const off = m.results.offset_knowledge_only
  const live = m.results.live_signals_only
  return (
    <>
      <h3 style={{ marginTop: 0 }}>Predictive model card</h3>
      <div className="muted small" style={{ marginBottom: 10 }}>
        One gradient-boosted classifier per hazard predicts the chance of an event within the next {m.horizon_m} m. Trained on {fmt(m.n_samples)} depth samples from {m.n_wells} wells.
        Validation: {m.cv}.
      </div>
      <div style={{ overflow: 'auto' }}>
        <table>
          <thead><tr><th>Hazard</th><th>Base rate</th><th><Term term="AUC">AUC</Term> (all features)</th><th>Avg precision</th><th>AUC offsets only</th><th>AUC live signals only</th><th>Alert threshold</th></tr></thead>
          <tbody>
            {RISK_TYPES.map((t) => (
              <tr key={t}>
                <td><b>{LABELS[t]}</b></td>
                <td className="mono">{pct(full[t].base_rate, 1)}</td>
                <td className="mono"><b>{full[t].auc.toFixed(3)}</b></td>
                <td className="mono">{full[t].ap.toFixed(2)}</td>
                <td className="mono">{off?.[t]?.auc.toFixed(3) ?? '–'}</td>
                <td className="mono">{live?.[t]?.auc.toFixed(3) ?? '–'}</td>
                <td className="mono">{pct(m.thresholds[t])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="quote" style={{ marginTop: 10, borderLeftColor: 'var(--warn)' }}>{m.data_note} “Offsets only” shows what the model knows purely from neighbouring wells before any live signal appears, which is what powers the long-range look-ahead alerts.</div>
    </>
  )
}

export default function DocumentsPage() {
  const { refresh } = useApp()
  const [docs, setDocs] = useState<DocRow[]>([])
  const [samples, setSamples] = useState<{ name: string; size_kb: number }[]>([])
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [result, setResult] = useState<IngestResult | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const [over, setOver] = useState(false)
  const [open, setOpen] = useState<number | null>(null)
  const input = useRef<HTMLInputElement>(null)

  const reload = useCallback(() => {
    api.documents().then(setDocs).catch(setErr)
    api.samples().then(setSamples).catch(() => undefined)
  }, [])
  useEffect(() => { reload(); api.metrics().then(setMetrics).catch(() => undefined) }, [reload])

  const run = async (label: string, fn: () => Promise<IngestResult>) => {
    setBusy(label); setErr(null)
    try { setResult(await fn()); await refresh(); reload() } catch (e) { setErr(e) } finally { setBusy(null) }
  }

  const ingested = new Set(docs.map((d) => d.filename))
  const ocrDocs = docs.filter((d) => d.ocr_used)

  return (
    <div className="col" style={{ gap: 14 }}>
      <Intro>
        Drop in a real drilling report and watch the system read it: it works out which well it's about, pulls
        out every problem mentioned, and adds it to the map — the same thing it already did for the 44 wells
        already loaded.
      </Intro>
      <div className="card">
        <h3>Ingest a report</h3>
        <div
          className={`drop ${over ? 'over' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setOver(true) }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) run(f.name, () => api.upload(f)) }}
          onClick={() => input.current?.click()}
          role="button" tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && input.current?.click()}
        >
          <Icon name="upload" size={26} />
          <div style={{ marginTop: 6 }}>Drop a Well Completion Report or Daily Drilling Report (PDF) here, or click to browse</div>
          <div className="faint small">Text PDFs are parsed directly; scanned pages are detected automatically and read with OCR. Max 50 MB.</div>
          <input ref={input} type="file" accept="application/pdf" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) run(f.name, () => api.upload(f)); e.target.value = '' }} />
        </div>
        {samples.length > 0 && (
          <div className="row" style={{ marginTop: 12 }}>
            <span className="muted small">Demo reports (↻ = already ingested; re-ingesting is safe):</span>
            {samples.map((s) => (
              <button key={s.name} className="btn small" disabled={!!busy} onClick={() => run(s.name, () => api.ingestSample(s.name))}>
                {ingested.has(s.name) ? '↻ ' : ''}{s.name} <span className="faint">{s.size_kb} KB</span>
              </button>
            ))}
          </div>
        )}
        {busy && <div className="row" style={{ marginTop: 12 }}><Spinner /><span className="muted">Reading {busy}… extracting text, events and formation tops</span></div>}
      </div>
      <ErrorBox error={err} />
      {result && <Result r={result} onOpen={setOpen} />}

      <div className="card">
        <h3>Processed documents ({docs.length})</h3>
        <div className="faint small" style={{ marginBottom: 8 }}>{ocrDocs.length} scanned document(s) were read with OCR: {ocrDocs.map((d) => d.well).join(', ') || 'none'}.</div>
        <div style={{ overflow: 'auto', maxHeight: 420 }}>
          <table>
            <thead><tr><th>Well</th><th>Type</th><th>File</th><th>Pages</th><th>Read by</th><th>Problems found</th></tr></thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td><b>{d.well}</b></td>
                  <td>{d.kind}</td>
                  <td className="small muted">{d.filename}</td>
                  <td className="mono">{d.pages}</td>
                  <td>{d.ocr_used ? <span className="chip badge-info">OCR · {pct(d.mean_conf ?? 0)}</span> : <span className="chip">text layer</span>}</td>
                  <td className="mono">{d.n_events}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {metrics && (
        <Advanced title="Predictive model performance" summary="accuracy numbers behind the AI risk model" defaultOpen={false}>
          <ModelCard m={metrics} />
        </Advanced>
      )}
      {open !== null && <EventDrawer id={open} onClose={() => setOpen(null)} onOpen={setOpen} />}
    </div>
  )
}

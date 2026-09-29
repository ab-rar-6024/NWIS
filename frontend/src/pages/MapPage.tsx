import { useEffect, useMemo, useState } from 'react'
import { Circle, CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap } from 'react-leaflet'
import { api, EVENT_TYPES, OffsetRow } from '../lib/api'
import { useApp } from '../App'
import { ErrorBox, Intro, Kpi, Term, TypeChip } from '../components/common'
import { fieldColor, fmt } from '../lib/format'

function Recenter({ lat, lon }: { lat: number; lon: number }) {
  const map = useMap()
  useEffect(() => { map.flyTo([lat, lon], Math.max(map.getZoom(), 11), { duration: 0.6 }) }, [lat, lon, map])
  return null
}

export default function MapPage() {
  const { wells, summary, selectedId, setSelectedId, radius, setRadius, go } = useApp()
  const sel = wells.find((w) => w.id === selectedId)
  const [offsets, setOffsets] = useState<OffsetRow[]>([])
  const [path, setPath] = useState<[number, number][]>([])
  const [err, setErr] = useState<unknown>(null)

  useEffect(() => {
    if (!selectedId) return
    let live = true
    const t = setTimeout(() => {
      api.offsets(selectedId, radius).then((r) => live && (setOffsets(r.offsets), setErr(null))).catch((e) => live && setErr(e))
    }, 120)
    api.trajectory(selectedId).then((r) => live && setPath(r.path)).catch(() => undefined)
    return () => { live = false; clearTimeout(t) }
  }, [selectedId, radius])

  const offsetIds = useMemo(() => new Set(offsets.map((o) => o.id)), [offsets])
  const offsetTotals = useMemo(() => {
    const c = Object.fromEntries(EVENT_TYPES.map((t) => [t, 0])) as Record<(typeof EVENT_TYPES)[number], number>
    offsets.forEach((o) => EVENT_TYPES.forEach((t) => (c[t] += o.event_counts[t])))
    return c
  }, [offsets])
  const offNpt = offsets.reduce((a, o) => a + o.npt_h, 0)

  const ocrPages = summary?.documents.reduce((a, d) => a + (d.ocr ?? 0), 0) ?? 0
  const center: [number, number] = sel ? [sel.lat, sel.lon] : [27.34, 95.37]

  return (
    <>
      <Intro>
        Pick a well on the right (or click one on the map). The dashed circle is your search radius — every
        well inside it is a neighbour whose past problems can warn you about this one. Drag the slider to
        widen or narrow that circle.
      </Intro>
      <div className="kpis">
        <Kpi value={summary?.wells ?? '–'} label="Wells the system knows about" hint="Historical wells built from completion/daily reports, plus the well currently drilling" />
        <Kpi value={fmt(summary?.events)} label="Problems it has found in reports" hint="Extracted automatically from daily and completion reports" />
        <Kpi value={fmt(summary?.total_npt_h)} label={<><Term term="NPT">Downtime</Term> hours recorded</>} />
        <Kpi value={fmt(summary?.corroborated)} label="Confirmed by two separate reports" hint="Same incident found in both a daily report and a completion report" />
        <Kpi value={ocrPages} label="Scanned (non-digital) reports read" />
      </div>
      <div className="map-layout">
        <div className="map-wrap">
          <MapContainer center={center} zoom={11} scrollWheelZoom style={{ height: '100%', width: '100%' }}>
            <TileLayer
              attribution='&copy; OpenStreetMap contributors'
              url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {sel && <Recenter lat={sel.lat} lon={sel.lon} />}
            {sel && <Circle center={[sel.lat, sel.lon]} radius={radius * 1000} pathOptions={{ color: '#f5a524', weight: 1.5, dashArray: '6 6', fillOpacity: 0.05 }} />}
            {path.length > 1 && <Polyline positions={path} pathOptions={{ color: '#f5a524', weight: 2.5, opacity: 0.9 }} />}
            {wells.map((w) => {
              const isSel = w.id === selectedId
              const inRadius = offsetIds.has(w.id)
              const active = w.status === 'ACTIVE'
              return (
                <CircleMarker
                  key={w.id}
                  center={[w.lat, w.lon]}
                  radius={active ? 10 : 5 + Math.sqrt(w.events) * 1.1}
                  pathOptions={{
                    color: isSel ? '#ffffff' : active ? '#f43f5e' : inRadius ? '#e2e8f0' : fieldColor(w.field),
                    weight: isSel ? 3 : inRadius || active ? 2 : 1,
                    fillColor: active ? '#f43f5e' : fieldColor(w.field),
                    fillOpacity: isSel || inRadius || active ? 0.85 : 0.35,
                    className: active ? 'pulse' : undefined,
                  }}
                  eventHandlers={{ click: () => setSelectedId(w.id) }}
                >
                  <Tooltip direction="top" offset={[0, -6]}>
                    <b>{w.name}</b> · {w.field}<br />{w.events} events · {fmt(w.npt_h)} NPT h{active ? ' · drilling now' : ''}
                  </Tooltip>
                </CircleMarker>
              )
            })}
          </MapContainer>
          <div className="map-legend" aria-label="Legend">
            <div className="row" style={{ gap: 12 }}>
              {['Digaru', 'Moranhat', 'Barsila'].map((f) => (
                <span key={f} className="row" style={{ gap: 5 }}><span className="dot" style={{ background: fieldColor(f) }} />{f}</span>
              ))}
              <span className="row" style={{ gap: 5 }}><span className="dot" style={{ background: '#f43f5e' }} />Active well</span>
            </div>
            <div className="faint" style={{ marginTop: 4 }}>Marker size = number of recorded events</div>
          </div>
        </div>

        <div className="side">
          <div className="card">
            <h3>Search radius</h3>
            <div className="row">
              <input type="range" min={1} max={20} step={0.5} value={radius} onChange={(e) => setRadius(Number(e.target.value))} style={{ flex: 1 }} aria-label="Search radius in kilometres" />
              <b className="mono" style={{ minWidth: 62, textAlign: 'right' }}>{radius.toFixed(1)} km</b>
            </div>
            <div className="muted small" style={{ marginTop: 6 }}>Distance is the closest horizontal approach between the two well paths over the depth they share, not just the surface spacing.</div>
          </div>

          {sel && (
            <div className="card">
              <div className="row" style={{ marginBottom: 6 }}>
                <h2 style={{ fontSize: 18 }}>{sel.name}</h2>
                <span className={`chip ${sel.status === 'ACTIVE' ? 'badge-crit' : ''}`}>{sel.status === 'ACTIVE' ? 'drilling' : sel.status.toLowerCase()}</span>
                <span className="chip">{sel.directional ? 'directional' : 'vertical'}</span>
              </div>
              <div className="muted small">{sel.field} field · rig {sel.rig ?? '–'} · TD {fmt(sel.td_md)} m MD · spud {sel.spud_date ?? '–'}</div>
              <div className="row" style={{ marginTop: 8 }}>
                <span className={`chip ${sel.documents.wcr ? 'badge-ok' : ''}`}><Term term="WCR">Completion report</Term> {sel.documents.wcr ? '✓' : '–'}</span>
                <span className={`chip ${sel.documents.ddr ? 'badge-ok' : ''}`}><Term term="DDR">Daily reports</Term> {sel.documents.ddr ? '✓' : '–'}</span>
                {sel.documents.ocr && <span className="chip badge-info"><Term term="OCR">Read by OCR</Term></span>}
              </div>
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn primary small" onClick={() => go('correlation')}>Compare with nearby wells</button>
                {sel.status === 'ACTIVE' && <button className="btn small" onClick={() => go('live')}>Open live monitor</button>}
              </div>
            </div>
          )}

          <div className="card">
            <h3>What happened nearby, within {radius.toFixed(1)} km</h3>
            <ErrorBox error={err} />
            {offsets.length === 0 ? (
              <div className="faint small">No neighbouring wells inside this radius. Try widening it.</div>
            ) : (
              <>
                <div className="row" style={{ marginBottom: 8 }}>
                  <b style={{ fontSize: 22 }}>{offsets.length}</b><span className="muted">wells · {fmt(offNpt)} <Term term="NPT">downtime</Term> hours recorded</span>
                </div>
                <div className="row" style={{ gap: 6 }}>
                  {EVENT_TYPES.filter((t) => offsetTotals[t] > 0).map((t) => <TypeChip key={t} type={t} count={offsetTotals[t]} />)}
                </div>
                <table style={{ marginTop: 10 }}>
                  <thead><tr><th>Well</th><th>Dist.</th><th>Problems</th><th><Term term="NPT">Downtime</Term> h</th></tr></thead>
                  <tbody>
                    {offsets.map((o) => (
                      <tr key={o.id} className="click" onClick={() => setSelectedId(o.id)}>
                        <td><b>{o.name}</b></td>
                        <td className="mono">{o.distance_km.toFixed(1)} km</td>
                        <td className="mono">{o.events}</td>
                        <td className="mono">{fmt(o.npt_h)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  )
}

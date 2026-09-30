import { useEffect, useState } from 'react'
import { api, Impact } from '../lib/api'
import { useApp } from '../App'
import { Icon } from '../components/common'
import { fmt, pct } from '../lib/format'

const ROLES = [
  {
    key: 'engineer',
    icon: 'activity',
    title: 'Drilling engineer',
    text: 'Live depth, look-ahead hazards and what nearby wells did at this depth.',
    cta: 'Open live monitor',
    to: 'live' as const,
  },
  {
    key: 'rig',
    icon: 'alert',
    title: 'Rig floor',
    text: 'One alert at a time, big type, with the action to take.',
    cta: 'Open rig view',
    to: 'rig' as const,
  },
  {
    key: 'analyst',
    icon: 'map',
    title: 'Office analyst',
    text: 'Offset map, depth correlation, searchable lessons, and the review queue.',
    cta: 'Open offset map',
    to: 'map' as const,
  },
]

export default function StartPage() {
  const { go, radius, summary } = useApp()
  const [impact, setImpact] = useState<Impact | null>(null)
  useEffect(() => { api.impact(radius, 0.1).then(setImpact).catch(() => undefined) }, [radius])

  return (
    <div className="col" style={{ gap: 28, maxWidth: 1000, margin: '0 auto', paddingTop: 12 }}>
      <div>
        <div className="chip badge-info" style={{ marginBottom: 14 }}>SIH26121 · Oil India Limited · eRTMAC-NWIS</div>
        <h2 style={{ fontSize: 44, lineHeight: 1.05, letterSpacing: '-0.03em', maxWidth: 760 }}>
          Know what&rsquo;s below<br /><span style={{ color: 'var(--accent)' }}>before you drill it.</span>
        </h2>
        <p className="muted" style={{ maxWidth: 620, fontSize: 16, marginTop: 14 }}>
          NWIS reads every past drilling report, locates each incident, and warns the crew from the wells around them
          before the bit gets there.
        </p>
      </div>

      <div className="kpis" style={{ marginBottom: 0 }}>
        <div className="kpi">
          <div className="v" style={{ color: 'var(--accent)' }}>{impact ? pct(impact.event_coverage) : '…'}</div>
          <div className="l">of past incidents would have been flagged in advance (each well tested with only its neighbours)</div>
        </div>
        <div className="kpi">
          <div className="v">{summary ? fmt(summary.events) : '…'}</div>
          <div className="l">incidents read from reports</div>
        </div>
        <div className="kpi">
          <div className="v">{summary ? fmt(summary.wells) : '…'}</div>
          <div className="l">wells in the knowledge base</div>
        </div>
      </div>

      <div>
        <div className="muted small" style={{ marginBottom: 10 }}>Choose how you work</div>
        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: 14 }}>
          {ROLES.map((r) => (
            <button key={r.key} className="card" onClick={() => go(r.to)} style={{ textAlign: 'left', cursor: 'pointer', padding: 18 }}>
              <div style={{ color: 'var(--accent)', marginBottom: 10 }}><Icon name={r.icon} size={24} /></div>
              <div style={{ fontSize: 18, fontWeight: 700 }}>{r.title}</div>
              <div className="muted small" style={{ margin: '6px 0 14px' }}>{r.text}</div>
              <span style={{ color: 'var(--accent-2)', fontWeight: 600 }}>{r.cta} →</span>
            </button>
          ))}
        </div>
        <div className="row" style={{ marginTop: 14 }}>
          <button className="btn" onClick={() => go('impact')}>See the evidence and the numbers behind it</button>
        </div>
      </div>
    </div>
  )
}

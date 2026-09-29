export const EVENT_TYPES = ['mud_loss', 'kick', 'stuck_pipe', 'overpressure', 'torque_spike', 'cementing_issue', 'fishing'] as const
export type EventType = (typeof EVENT_TYPES)[number]
export const RISK_TYPES: EventType[] = ['mud_loss', 'kick', 'stuck_pipe', 'overpressure', 'torque_spike']

export const LABELS: Record<EventType, string> = {
  mud_loss: 'Mud loss',
  kick: 'Kick',
  stuck_pipe: 'Stuck pipe',
  overpressure: 'Overpressure',
  torque_spike: 'Torque spike',
  cementing_issue: 'Cementing issue',
  fishing: 'Fishing',
}

export const COLORS: Record<EventType, string> = {
  mud_loss: '#38bdf8',
  kick: '#fb923c',
  stuck_pipe: '#a78bfa',
  overpressure: '#f87171',
  torque_spike: '#facc15',
  cementing_issue: '#94a3b8',
  fishing: '#4ade80',
}

export interface WellRow {
  id: number
  name: string
  field: string | null
  lat: number
  lon: number
  status: string
  td_md: number | null
  td_tvd: number | null
  spud_date: string | null
  rig: string | null
  directional: boolean
  events: number
  event_counts: Record<EventType, number>
  npt_h: number
  documents: { wcr: boolean; ddr: boolean; ocr: boolean }
}

export interface Summary {
  wells: number
  fields: number
  events: number
  events_by_type: Record<EventType, number>
  total_npt_h: number
  documents: { kind: string; n: number; ocr: number; pages: number }[]
  active_wells: { id: number; name: string }[]
  model: boolean
  corroborated: number
}

export interface OffsetRow {
  id: number
  name: string
  field: string | null
  lat: number
  lon: number
  distance_km: number
  surface_distance_km: number
  td_md: number
  td_tvd: number
  events: number
  event_counts: Record<EventType, number>
  npt_h: number
}

export interface Top {
  formation: string
  tvd: number
  md: number
  sigma_m?: number
  n_offsets?: number
}

export interface CorrEvent {
  id: number
  type: EventType
  md: number
  tvd: number
  severity: string
  npt_h: number | null
  summary: string
  formation: string | null
}

export interface CorrWell {
  id: number
  name: string
  distance_km: number | null
  td_md: number
  td_tvd: number
  status: string
  predicted: boolean
  tops: Top[]
  events: CorrEvent[]
}

export interface Correlation {
  radius_km: number
  formations: string[]
  target: CorrWell
  offsets: CorrWell[]
}

export interface ActionStat {
  action: string
  text: string
  n: number
  success: number
  success_rate: number
  mean_npt_h: number | null
}

export interface Zone {
  id: string
  type: EventType
  label: string
  md_from: number
  md_to: number
  md_center: number
  tvd_center: number
  tvd_from: number
  tvd_to: number
  formation: string | null
  n_events: number
  n_wells: number
  prevalence: number
  mean_npt_h: number | null
  score: number
  level: 'low' | 'medium' | 'high'
  wells: string[]
  event_ids: number[]
  recommendation: string
  sigma_m: number
}

export interface Lookahead {
  md: number
  window: number
  predicted_tops: boolean
  tops: Top[]
  zones: Zone[]
}

export interface RiskRow {
  formation: string
  top_tvd: number
  top_md: number
  thickness_m: number
  sigma_m: number
  n_offsets: number
  expected_npt_h: number
  risk: Record<EventType, { prevalence: number; events: number; mean_npt_h: number | null; typical_depth_below_top_m: number | null; level: string }>
}

export interface EventPublic {
  id: number
  well_id: number
  well: string
  type: EventType
  label: string
  md: number
  tvd: number | null
  formation: string | null
  severity: string
  npt_h: number | null
  confidence: number
  depth_source: string
  mitigations: string[]
  outcome: string | null
  details: Record<string, number | string | boolean>
  summary: string
  corroborated: boolean
  date: string | null
}

export interface EventDetail extends EventPublic {
  description: string
  sources: { doc_id: number; kind: string; page: number | null; filename: string | null }[]
  similar: (EventPublic & { distance_km: number })[]
}

export interface SearchResult {
  kind: 'event' | 'ddr' | 'lesson'
  well: string
  formation: string | null
  etype: EventType | null
  ref: string
  id: number
  md: number | null
  snip: string
  summary?: string
  severity?: string
  npt_h?: number | null
  confidence?: number
  corroborated?: boolean
  date?: string
  report_no?: number
  page?: number
}

export interface Lesson {
  formation: string
  hazard: EventType
  label: string
  n_events: number
  n_wells: number
  n_wells_penetrating: number
  prevalence: number | null
  total_npt_h: number
  mean_npt_h: number | null
  severity: Record<string, number>
  depth_below_top_m: { p10: number; median: number; p90: number } | null
  actions: ActionStat[]
  recommendation: string
  detail: Record<string, any>
  wells: string[]
  event_ids: number[]
  documented_lessons: { text: string; well: string }[]
}

export interface AskResult {
  question: string
  formation: string | null
  hazards: string[]
  answer: string[]
  lessons: Lesson[]
  evidence: SearchResult[]
}

export interface DocRow {
  id: number
  well: string
  kind: string
  filename: string
  pages: number
  ocr_used: number
  ocr_pages: string
  mean_conf: number | null
  n_events: number
  ingested_at: string
}

export interface IngestResult {
  well: string
  well_id: number
  kind: string
  events: number
  consolidated: number
  ocr_pages: number[]
  ocr_confidence: number | null
  events_detail: { id: number; type: EventType; md: number; formation: string | null; severity: string; npt_h: number | null; confidence: number; summary: string; corroborated: number }[]
}

export interface LiveSample {
  md: number
  tvd?: number
  elapsed_h?: number
  rop: number
  wob: number
  rpm: number
  torque: number
  spp: number
  flow_in: number
  flow_out: number
  pit_delta: number
  mw: number
  gas: number
  overpull: number
  flow_diff_pct?: number
  mse?: number
  probs?: Record<string, number>
}

export interface Alert {
  id?: number
  well: string
  md: number
  elapsed_h?: number
  kind: 'lookahead' | 'formation' | 'realtime' | 'model'
  level: 'info' | 'warning' | 'critical'
  hazard: EventType
  title: string
  message: string
  recommendation: string
  evidence: Record<string, any>
  ahead_m: number | null
  formation: string | null
  feedback?: 'confirmed' | 'dismissed' | null
}

export interface LiveState {
  running: boolean
  speed: number
  idx: number
  n: number
  md: number | null
  start_md: number
  well: string
  probs: Record<string, number>
  planned_td_md: number
}

export interface LiveSnapshot {
  state: LiveState
  history: LiveSample[]
  alerts: Alert[]
  zones: Zone[]
  tops: (Top & { sigma_m: number })[]
}

export interface ImpactEvent {
  id: number
  type: EventType
  md: number
  npt_h: number
  flagged: boolean
  zone_level: string | null
}

export interface ImpactWell {
  well_id: number
  well: string
  field: string | null
  n_events: number
  n_flagged: number
  total_npt_h: number
  flagged_npt_h: number
  n_offsets: number
  events: ImpactEvent[]
}

export interface Impact {
  radius_km: number
  min_prevalence: number
  n_wells: number
  total_events: number
  flagged_events: number
  total_npt_h: number
  flagged_npt_h: number
  event_coverage: number | null
  npt_coverage: number | null
  wells: ImpactWell[]
  exemplar: ImpactWell | null
  method: string
}

export interface FeedbackStats {
  confirmed: number
  dismissed: number
  rated: number
  total: number
  agreement: number | null
}

export interface Metrics {
  n_samples: number
  n_wells: number
  horizon_m: number
  cv: string
  data_note: string
  thresholds: Record<string, number>
  results: Record<string, Record<string, { auc: number; ap: number; base_rate: number; threshold: number }>>
}

// When the frontend and backend are deployed separately (e.g. frontend on Vercel, backend on Render),
// set VITE_API_BASE at build time to the backend's origin (no trailing slash). Left unset, paths stay
// relative — the local-dev and same-origin-deployment behaviour is unchanged.
export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/+$/, '') || ''

async function j<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(API_BASE + url, init)
  if (!r.ok) {
    let msg = r.statusText
    try {
      const b = await r.json()
      const d = b.detail
      msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map((x: { loc?: string[]; msg?: string }) => `${x.loc?.slice(-1)[0] ?? 'input'}: ${x.msg ?? 'invalid'}`).join('; ') : JSON.stringify(d)
    } catch {
      /* keep statusText */
    }
    throw new Error(msg)
  }
  return r.json() as Promise<T>
}

const q = (o: Record<string, string | number | undefined | null>) => {
  const p = new URLSearchParams()
  Object.entries(o).forEach(([k, v]) => v !== undefined && v !== null && v !== '' && p.set(k, String(v)))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const api = {
  summary: () => j<Summary>('/api/summary'),
  wells: () => j<WellRow[]>('/api/wells'),
  offsets: (id: number, radius: number) => j<{ offsets: OffsetRow[] }>(`/api/wells/${id}/offsets${q({ radius_km: radius })}`),
  trajectory: (id: number) => j<{ path: [number, number][] }>(`/api/wells/${id}/trajectory`),
  correlation: (id: number, radius: number, limit: number) => j<Correlation>(`/api/wells/${id}/correlation${q({ radius_km: radius, limit })}`),
  lookahead: (id: number, md: number, window: number, radius: number) =>
    j<Lookahead>(`/api/wells/${id}/lookahead${q({ md, window, radius_km: radius })}`),
  riskProfile: (id: number, radius: number) => j<{ predicted_tops: boolean; profile: RiskRow[]; n_offsets: number }>(`/api/wells/${id}/risk-profile${q({ radius_km: radius })}`),
  events: (p: Record<string, string | number | undefined>) => j<{ total: number; events: EventPublic[] }>(`/api/events${q(p)}`),
  event: (id: number) => j<EventDetail>(`/api/events/${id}`),
  search: (p: Record<string, string | number | undefined>) => j<{ results: SearchResult[] }>(`/api/search${q(p)}`),
  lessons: (formation?: string, hazard?: string) => j<{ formations: string[]; lessons: Lesson[] }>(`/api/lessons${q({ formation, hazard })}`),
  ask: (question: string) => j<AskResult>('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question }) }),
  documents: () => j<DocRow[]>('/api/documents'),
  samples: () => j<{ name: string; size_kb: number }[]>('/api/samples'),
  ingestSample: (name: string) => j<IngestResult>(`/api/documents/ingest-sample${q({ name })}`, { method: 'POST' }),
  upload: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return j<IngestResult>('/api/documents/upload', { method: 'POST', body: fd })
  },
  metrics: () => j<Metrics>('/api/model/metrics'),
  liveSnapshot: (id: number) => j<LiveSnapshot>(`/api/live/${id}/snapshot`),
  liveControl: (id: number, body: { action: string; speed?: number; start_md?: number }) =>
    j<LiveState>(`/api/live/${id}/control`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  impact: (radius: number, minPrevalence = 0.1) => j<Impact>(`/api/impact${q({ radius_km: radius, min_prevalence: minPrevalence })}`),
  alertFeedback: (wellId: number, alertId: number, status: 'confirmed' | 'dismissed') =>
    j<{ alert: Alert; stats: FeedbackStats }>(`/api/live/${wellId}/alerts/${alertId}/feedback`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }),
    }),
  feedbackStats: (wellId: number) => j<FeedbackStats>(`/api/live/${wellId}/feedback-stats`),
}

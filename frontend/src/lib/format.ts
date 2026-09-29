export const fmt = (v: number | null | undefined, d = 0) =>
  v === null || v === undefined || Number.isNaN(v) ? '–' : v.toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d })

export const fmtMd = (v: number | null | undefined) => (v === null || v === undefined ? '–' : `${fmt(v)} m`)
export const pct = (v: number | null | undefined, d = 0) => (v === null || v === undefined ? '–' : `${(v * 100).toFixed(d)}%`)

export const FORMATION_COLORS: Record<string, string> = {
  Alluvium: '#a3a380',
  Namsang: '#c9b28a',
  'Girujan Clay': '#a98d6b',
  'Tipam Sandstone': '#e0b96b',
  'Barail Coal Shale': '#5b6473',
  'Barail Sandstone': '#d6a35c',
  'Kopili Shale': '#7f8fa6',
  'Sylhet Limestone': '#8fb8c9',
  'Langpar-Lakadong': '#6fa3a0',
  Therria: '#8b6f9a',
}
export const formationColor = (f: string) => FORMATION_COLORS[f] ?? '#7c8aa5'

export const FIELD_COLORS: Record<string, string> = { Digaru: '#38bdf8', Moranhat: '#fbbf24', Barsila: '#4ade80' }
export const fieldColor = (f: string | null) => (f && FIELD_COLORS[f]) || '#94a3b8'

export const SEV_SIZE: Record<string, number> = { low: 3.6, medium: 4.8, high: 6, critical: 7.4 }

export const actionText = (a: string) => a.replace(/_/g, ' ')

/** Render an FTS snippet safely: only <mark> is honoured, everything else stays plain text. */
export function snippetParts(s: string): { text: string; hit: boolean }[] {
  const out: { text: string; hit: boolean }[] = []
  let hit = false
  for (const piece of s.split(/(<mark>|<\/mark>)/)) {
    if (piece === '<mark>') hit = true
    else if (piece === '</mark>') hit = false
    else if (piece) out.push({ text: piece, hit })
  }
  return out
}

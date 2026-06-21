const BASE = import.meta.env.VITE_API_URL ?? ''

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, options)
  if (!res.ok) throw new Error(`${options.method || 'GET'} ${path} → ${res.status}`)
  return res.json()
}

export const fetchScores = () => request('/api/scores')
export const fetchPool = () => request('/api/pool')
export const fetchAudit = () => request('/api/audit')
export const postOptimize = () => request('/api/optimize', { method: 'POST' })
export const postRollback = (runId) =>
  request('/api/rollback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ run_id: runId }),
  })

import { useState, useEffect, useCallback } from 'react'
import { fetchScores, fetchPool, fetchAudit, postRollback, postOptimize } from './api.js'
import ScoreChart from './components/ScoreChart.jsx'
import PoolList from './components/PoolList.jsx'
import AuditTable from './components/AuditTable.jsx'

const POLL_MS = 30_000

const headerStyle = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  padding: '16px 28px',
  borderBottom: '1px solid var(--border)',
  background: 'var(--surface)',
  marginBottom: '24px',
}

const titleStyle = {
  fontSize: '16px',
  fontWeight: 700,
  letterSpacing: '-0.01em',
}

const dotStyle = (cold) => ({
  display: 'inline-block',
  width: 8,
  height: 8,
  borderRadius: '50%',
  background: cold ? '#c89632' : '#1D9E75',
  marginRight: 8,
})

const btnStyle = {
  fontSize: '12px',
  fontWeight: 600,
  padding: '6px 14px',
  borderRadius: '6px',
  border: '1px solid var(--border)',
  background: 'transparent',
  color: 'var(--text-secondary)',
  cursor: 'pointer',
  marginLeft: '8px',
}

export default function App() {
  const [scores, setScores] = useState(null)
  const [pool, setPool] = useState(null)
  const [audit, setAudit] = useState(null)
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [optimizing, setOptimizing] = useState(false)

  const loadAll = useCallback(async () => {
    try {
      const [s, p, a, h] = await Promise.all([
        fetchScores(),
        fetchPool(),
        fetchAudit(),
        fetch('/api/health').then(r => r.json()),
      ])
      setScores(s)
      setPool(p)
      setAudit(a)
      setHealth(h)
      setLastUpdated(new Date())
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => {
    loadAll()
    const id = setInterval(loadAll, POLL_MS)
    return () => clearInterval(id)
  }, [loadAll])

  const handleRollback = async (runId) => {
    await postRollback(runId)
    await loadAll()
  }

  const handleOptimize = async () => {
    setOptimizing(true)
    try {
      await postOptimize()
      await loadAll()
    } finally {
      setOptimizing(false)
    }
  }

  return (
    <div>
      <header style={headerStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <span style={titleStyle}>MCPForge</span>
          {health && (
            <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              <span style={dotStyle(health.cold_start)} />
              {health.cold_start
                ? 'cold start'
                : `${health.pool_size} active tool${health.pool_size !== 1 ? 's' : ''}`}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {lastUpdated && (
            <span style={{ fontSize: '11px', color: 'var(--muted)' }}>
              updated {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button
            style={btnStyle}
            onClick={handleOptimize}
            disabled={optimizing}
          >
            {optimizing ? 'Optimizing…' : 'Run optimizer'}
          </button>
        </div>
      </header>

      {error && (
        <div style={{ margin: '0 28px 16px', padding: '10px 14px', borderRadius: '6px', background: 'rgba(224,82,82,0.1)', color: 'var(--danger)', fontSize: '13px' }}>
          Error: {error}
        </div>
      )}

      <div style={{ maxWidth: '1100px', margin: '0 auto', padding: '0 28px' }}>
        <ScoreChart scores={scores} />
        <PoolList pool={pool} />
        <AuditTable audit={audit} onRollback={handleRollback} />
      </div>
    </div>
  )
}

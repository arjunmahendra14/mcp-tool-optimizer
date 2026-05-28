import { useState } from 'react'

const cardStyle = {
  background: 'var(--surface)',
  border: '1px solid var(--border)',
  borderRadius: '8px',
  padding: '20px',
  marginBottom: '20px',
}

const headingStyle = {
  fontSize: '13px',
  fontWeight: 600,
  letterSpacing: '0.06em',
  textTransform: 'uppercase',
  color: 'var(--text-secondary)',
  marginBottom: '16px',
}

const thStyle = {
  textAlign: 'left',
  fontSize: '11px',
  fontWeight: 600,
  color: 'var(--text-secondary)',
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
  padding: '8px 12px',
  borderBottom: '1px solid var(--border)',
}

const tdStyle = {
  padding: '10px 12px',
  borderBottom: '1px solid var(--border)',
  verticalAlign: 'middle',
}

const triggerBadge = (trigger) => {
  const colors = {
    scheduled: { bg: 'rgba(90,100,180,0.15)', fg: '#8a96e0' },
    manual: { bg: 'rgba(200,140,50,0.15)', fg: '#c89632' },
    rollback: { bg: 'rgba(224,82,82,0.15)', fg: 'var(--danger)' },
    cli: { bg: 'rgba(100,180,90,0.15)', fg: '#64b45a' },
  }
  const c = colors[trigger] ?? { bg: 'rgba(138,138,154,0.15)', fg: 'var(--text-secondary)' }
  return (
    <span style={{
      fontSize: '11px',
      fontWeight: 600,
      padding: '2px 8px',
      borderRadius: '10px',
      background: c.bg,
      color: c.fg,
    }}>
      {trigger}
    </span>
  )
}

export default function AuditTable({ audit, onRollback }) {
  const [rollingBack, setRollingBack] = useState(null)
  const [error, setError] = useState(null)

  if (!audit) return <div style={cardStyle}><p style={{ color: 'var(--muted)' }}>Loading...</p></div>

  const handleRollback = async (id) => {
    setRollingBack(id)
    setError(null)
    try {
      await onRollback(id)
    } catch (e) {
      setError(`Rollback failed: ${e.message}`)
    } finally {
      setRollingBack(null)
    }
  }

  return (
    <div style={cardStyle}>
      <div style={headingStyle}>Audit Log</div>
      {error && (
        <div style={{ color: 'var(--danger)', fontSize: '13px', marginBottom: '12px' }}>
          {error}
        </div>
      )}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={thStyle}>ID</th>
              <th style={thStyle}>Time</th>
              <th style={thStyle}>Trigger</th>
              <th style={thStyle}>Changes</th>
              <th style={thStyle}>Pool Size</th>
              <th style={thStyle}></th>
            </tr>
          </thead>
          <tbody>
            {audit.map((row) => {
              const changes = JSON.parse(row.changes_json)
              const snapshot = JSON.parse(row.pool_snapshot_json)
              const changeCount = Object.keys(changes).length
              return (
                <tr key={row.id} style={{ transition: 'background 0.1s' }}>
                  <td style={{ ...tdStyle, color: 'var(--text-secondary)', fontVariantNumeric: 'tabular-nums' }}>
                    #{row.id}
                  </td>
                  <td style={{ ...tdStyle, color: 'var(--text-secondary)', fontSize: '12px', whiteSpace: 'nowrap' }}>
                    {new Date(row.ts * 1000).toLocaleString()}
                  </td>
                  <td style={tdStyle}>{triggerBadge(row.trigger)}</td>
                  <td style={{ ...tdStyle, color: changeCount > 0 ? 'var(--text)' : 'var(--muted)' }}>
                    {changeCount > 0 ? `${changeCount} change${changeCount !== 1 ? 's' : ''}` : '—'}
                  </td>
                  <td style={{ ...tdStyle, color: 'var(--text-secondary)' }}>
                    {snapshot.filter(t => t.status === 'active').length} active / {snapshot.length} total
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>
                    <button
                      onClick={() => handleRollback(row.id)}
                      disabled={rollingBack === row.id}
                      style={{
                        fontSize: '12px',
                        fontWeight: 600,
                        padding: '4px 12px',
                        borderRadius: '5px',
                        border: '1px solid var(--border)',
                        background: rollingBack === row.id ? 'var(--border)' : 'transparent',
                        color: rollingBack === row.id ? 'var(--muted)' : 'var(--text-secondary)',
                        cursor: rollingBack === row.id ? 'not-allowed' : 'pointer',
                        transition: 'all 0.15s',
                      }}
                    >
                      {rollingBack === row.id ? 'Rolling back…' : 'Rollback'}
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

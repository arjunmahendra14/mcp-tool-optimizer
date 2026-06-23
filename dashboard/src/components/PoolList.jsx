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

const colHeadStyle = {
  fontSize: '12px',
  fontWeight: 600,
  color: 'var(--text-secondary)',
  marginBottom: '10px',
}

const badgeStyle = (active) => ({
  display: 'inline-block',
  fontSize: '11px',
  fontWeight: 600,
  padding: '1px 8px',
  borderRadius: '10px',
  marginLeft: '8px',
  background: active ? 'rgba(29,158,117,0.15)' : 'rgba(180,178,169,0.12)',
  color: active ? '#1D9E75' : 'var(--text-secondary)',
})

const toolRowStyle = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  padding: '6px 0',
  borderBottom: '1px solid var(--border)',
}

export default function PoolList({ pool }) {
  if (!pool) return <div style={cardStyle}><p style={{ color: 'var(--muted)' }}>Loading...</p></div>

  return (
    <div style={cardStyle}>
      <div style={headingStyle}>Active Pool</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
        <div>
          <div style={colHeadStyle}>
            Active <span style={badgeStyle(true)}>{pool.active.length}</span>
          </div>
          {pool.active.length === 0 && (
            <p style={{ color: 'var(--muted)', fontSize: '12px' }}>No active tools</p>
          )}
          {pool.active.map((t, i) => (
            <div key={i} style={toolRowStyle}>
              <span style={{ fontWeight: 500 }}>{t.tool}</span>
              <span style={{ color: 'var(--text-secondary)', fontSize: '12px' }}>{t.server}</span>
            </div>
          ))}
        </div>
        <div>
          <div style={colHeadStyle}>
            Reserve <span style={badgeStyle(false)}>{pool.reserve.length}</span>
          </div>
          {pool.reserve.length === 0 && (
            <p style={{ color: 'var(--muted)', fontSize: '12px' }}>No pruned tools</p>
          )}
          {pool.reserve.map((t, i) => (
            <div key={i} style={{ ...toolRowStyle, opacity: 0.55 }}>
              <span>{t.tool}</span>
              <span style={{ color: 'var(--text-secondary)', fontSize: '12px' }}>{t.server}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

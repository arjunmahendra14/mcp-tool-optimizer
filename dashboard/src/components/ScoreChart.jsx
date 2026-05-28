import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
  ResponsiveContainer,
} from 'recharts'

// Only two hardcoded colors permitted per spec — chart data visualization
const ACTIVE_COLOR = '#1D9E75'
const PRUNED_COLOR = '#B4B2A9'

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

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div style={{
      background: 'var(--surface)',
      border: '1px solid var(--border)',
      borderRadius: '6px',
      padding: '10px 14px',
      fontSize: '13px',
    }}>
      <div style={{ fontWeight: 600 }}>{d.tool}</div>
      <div style={{ color: 'var(--text-secondary)' }}>{d.server}</div>
      <div style={{ marginTop: '4px' }}>
        score: <strong>{d.score.toFixed(3)}</strong>
      </div>
      <div style={{ color: d.status === 'active' ? ACTIVE_COLOR : PRUNED_COLOR }}>
        {d.status}
      </div>
    </div>
  )
}

export default function ScoreChart({ scores }) {
  if (!scores) return <div style={cardStyle}><p style={{ color: 'var(--muted)' }}>Loading...</p></div>

  const chartHeight = Math.max(200, scores.length * 28)

  return (
    <div style={cardStyle}>
      <div style={headingStyle}>Tool Scores</div>
      <ResponsiveContainer width="100%" height={chartHeight}>
        <BarChart
          data={scores}
          layout="vertical"
          margin={{ top: 0, right: 24, bottom: 0, left: 8 }}
        >
          <XAxis
            type="number"
            tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
            axisLine={{ stroke: 'var(--border)' }}
            tickLine={false}
          />
          <YAxis
            type="category"
            dataKey="tool"
            width={160}
            tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
          <Bar dataKey="score" radius={[0, 3, 3, 0]}>
            {scores.map((entry, i) => (
              <Cell
                key={i}
                fill={entry.status === 'active' ? ACTIVE_COLOR : PRUNED_COLOR}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div style={{ display: 'flex', gap: '16px', marginTop: '12px', fontSize: '12px', color: 'var(--text-secondary)' }}>
        <span><span style={{ display: 'inline-block', width: 10, height: 10, background: ACTIVE_COLOR, borderRadius: 2, marginRight: 5 }} />Active</span>
        <span><span style={{ display: 'inline-block', width: 10, height: 10, background: PRUNED_COLOR, borderRadius: 2, marginRight: 5 }} />Pruned</span>
      </div>
    </div>
  )
}

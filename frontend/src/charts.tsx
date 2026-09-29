import { useState } from 'react'
import { money } from './api'

export interface BarDatum { label: string; sub: string; value: number; count: number }

/** Single-series bar chart (gold). One axis, thin bars with 4px rounded data-ends,
 *  recessive grid, per-bar hover tooltip, and a hidden table for screen readers. */
export function BarChart({ data, height = 240, title }: { data: BarDatum[]; height?: number; title: string }) {
  const [hover, setHover] = useState<number | null>(null)
  const W = 640, H = height, padL = 52, padR = 12, padT = 16, padB = 36
  const max = Math.max(1, ...data.map((d) => d.value))
  const step = niceStep(max / 4)
  const top = Math.ceil(max / step) * step
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step)
  const plotW = W - padL - padR, plotH = H - padT - padB
  const band = plotW / data.length
  const barW = Math.min(36, band * 0.5)
  const y = (v: number) => padT + plotH - (v / top) * plotH

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={title}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - padR} y1={y(t)} y2={y(t)} stroke="rgb(247 244 232 / 0.08)" strokeDasharray={t === 0 ? undefined : '3 5'} />
            <text x={padL - 8} y={y(t) + 4} textAnchor="end" fontSize="11" fill="#96927D">{compact(t)}</text>
          </g>
        ))}
        {data.map((d, i) => {
          const x = padL + band * i + (band - barW) / 2
          const h = Math.max(0, y(0) - y(d.value))
          const r = Math.min(4, h / 2)
          return (
            <g key={d.label} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(i)} onBlur={() => setHover(null)} tabIndex={0}>
              <rect x={padL + band * i} y={padT} width={band} height={plotH} fill={hover === i ? 'rgb(247 244 232 / 0.04)' : 'transparent'} />
              {h > 0 && (
                <path d={`M${x},${y(0)} V${y(d.value) + r} Q${x},${y(d.value)} ${x + r},${y(d.value)} H${x + barW - r} Q${x + barW},${y(d.value)} ${x + barW},${y(d.value) + r} V${y(0)} Z`}
                  fill={hover === null || hover === i ? '#FFD100' : 'rgb(255 209 0 / 0.45)'} />
              )}
              <text x={padL + band * i + band / 2} y={H - 14} textAnchor="middle" fontSize="11" fill={hover === i ? '#F7F4E8' : '#96927D'}>{d.label}</text>
            </g>
          )
        })}
      </svg>
      {hover !== null && (
        <div className="pointer-events-none absolute top-2 rounded-xl border border-line bg-bg/95 px-3 py-2 text-xs shadow-lg"
          style={{ left: `clamp(0px, calc(${((padL + (hover + 0.5) * band) / W) * 100}% - 70px), calc(100% - 150px))` }}>
          <div className="font-semibold text-ink">{data[hover].sub}</div>
          <div className="num text-ink-2">{money(data[hover].value)} · {data[hover].count} bill{data[hover].count === 1 ? '' : 's'}</div>
        </div>
      )}
      <table className="sr-only">
        <caption>{title}</caption>
        <thead><tr><th>Week</th><th>Amount due</th><th>Bills</th></tr></thead>
        <tbody>{data.map((d) => <tr key={d.label}><td>{d.sub}</td><td>{money(d.value)}</td><td>{d.count}</td></tr>)}</tbody>
      </table>
    </div>
  )
}

function niceStep(raw: number) {
  const p = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1))))
  const n = raw / p
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p
}

function compact(v: number) {
  if (v >= 100000) return `₹${(v / 100000).toFixed(v % 100000 ? 1 : 0)}L`
  if (v >= 1000) return `₹${(v / 1000).toFixed(v % 1000 ? 1 : 0)}k`
  return `₹${v}`
}

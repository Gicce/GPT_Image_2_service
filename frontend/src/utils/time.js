export function formatTime(iso) {
  if (!iso) return '-'
  try {
    const date = new Date(iso)
    if (isNaN(date.getTime())) return iso.replace('T', ' ').slice(0, 19)
    // 后端存储UTC时间，前端统一显示UTC+8
    const utcMs = date.getTime() + date.getTimezoneOffset() * 60 * 1000
    const china = new Date(utcMs + 8 * 60 * 60 * 1000)
    const y = china.getFullYear()
    const m = String(china.getMonth() + 1).padStart(2, '0')
    const d = String(china.getDate()).padStart(2, '0')
    const h = String(china.getHours()).padStart(2, '0')
    const min = String(china.getMinutes()).padStart(2, '0')
    const s = String(china.getSeconds()).padStart(2, '0')
    return `${y}-${m}-${d} ${h}:${min}:${s}`
  } catch {
    return iso.replace('T', ' ').slice(0, 19)
  }
}

export function getTodayChina() {
  const now = new Date()
  const utcMs = now.getTime() + now.getTimezoneOffset() * 60 * 1000
  const china = new Date(utcMs + 8 * 60 * 60 * 1000)
  return china.toISOString().slice(0, 10)
}

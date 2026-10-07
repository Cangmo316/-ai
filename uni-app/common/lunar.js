/**
 * 公历 → 农历（自算天文数据，无 200 年硬编码表）
 *
 * 为什么不用常见的 lunarInfo 表：那种表动辄 200 行十六进制，转录一处错就会
 * 静默给出错误日期（本项目开发中已实际踩过：2025 年整年差 33 天）。
 * 改用 Meeus《Astronomical Algorithms》第 49 章的朔望月公式 + 太阳黄经，
 * 有标准答案可核对，且支持范围不受表限制。
 *
 * 算法要点：
 *   · 农历月首 = 朔（新月）所在的那一天（北京时间，东经 120°）
 *   · 冬至所在月为十一月；两个冬至之间若有 13 个朔望月，则第一个不含中气的月为闰月
 *   · 中气 = 太阳黄经为 30° 整数倍的时刻
 *
 * 精度：朔时刻误差约数分钟（低精度版），判定「哪一天」完全够用。
 * 已用 2023–2030 年春节官方日期逐条核对，全部一致。
 */

const RAD = Math.PI / 180
const sin = (x) => Math.sin(x * RAD)
const cos = (x) => Math.cos(x * RAD)
const mod = (a, n) => ((a % n) + n) % n

/* ------------------------------------------------------------ 儒略日 ↔ 日期 */

/** 儒略日 → 公历（Meeus 第 7 章） */
function jdToDate(jd) {
  const z = Math.floor(jd + 0.5)
  const f = jd + 0.5 - z
  let a = z
  if (z >= 2299161) {
    const alpha = Math.floor((z - 1867216.25) / 36524.25)
    a = z + 1 + alpha - Math.floor(alpha / 4)
  }
  const b = a + 1524
  const c = Math.floor((b - 122.1) / 365.25)
  const d = Math.floor(365.25 * c)
  const e = Math.floor((b - d) / 30.6001)
  const dayFrac = b - d - Math.floor(30.6001 * e) + f
  const day = Math.floor(dayFrac)
  const month = e < 14 ? e - 1 : e - 13
  const year = month > 2 ? c - 4716 : c - 4715
  const hours = (dayFrac - day) * 24
  return new Date(Date.UTC(year, month - 1, day, Math.floor(hours), Math.round((hours % 1) * 60)))
}

/** 公历 → 儒略日 */
function dateToJD(date) {
  const y = date.getUTCFullYear()
  const m = date.getUTCMonth() + 1
  const d = date.getUTCDate() + (date.getUTCHours() * 3600 + date.getUTCMinutes() * 60) / 86400
  let yy = y
  let mm = m
  if (mm <= 2) { yy -= 1; mm += 12 }
  const A = Math.floor(yy / 100)
  const B = 2 - A + Math.floor(A / 4)
  return Math.floor(365.25 * (yy + 4716)) + Math.floor(30.6001 * (mm + 1)) + d + B - 1524.5
}

/** ΔT 近似（秒），1900–2150 段 */
function deltaTSeconds(y) {
  if (y >= 2005 && y < 2050) { const t = y - 2000; return 62.92 + 0.32217 * t + 0.005589 * t * t }
  if (y >= 1986 && y < 2005) {
    const t = y - 2000
    return 63.86 + 0.3345 * t - 0.060374 * t * t + 0.0017275 * t ** 3
      + 0.000651814 * t ** 4 + 0.00002373599 * t ** 5
  }
  if (y >= 2050 && y <= 2150) return -20 + 32 * Math.pow((y - 1820) / 100, 2) - 0.5628 * (2150 - y)
  const u = (y - 1820) / 100
  return -20 + 32 * u * u
}

/* ------------------------------------------------------------------ 朔（新月） */

const NEW_MOON_COEF = [
  [-0.40720, 0, 1, 0, 0], [0.17241, 1, 0, 0, 0], [0.01608, 2, 0, 0, 0],
  [0.01039, 0, 0, 1, 0], [0.00739, 1, 1, 0, 0], [-0.00514, 1, 0, -1, 0],
  [0.00208, 2, 1, 0, 0], [-0.00111, 0, 0, 1, -1], [-0.00057, 0, 0, 1, 1],
  [0.00056, 1, 0, 1, 0], [-0.00042, 3, 0, 0, 0], [0.00042, 1, 1, 1, 0],
  [0.00038, 1, 1, -1, 0], [-0.00024, 1, -1, 0, 0], [-0.00017, 0, 0, 0, 1],
  [-0.00007, 3, 0, -1, 0], [0.00004, 2, 2, 0, 0], [0.00004, 2, 0, -2, 0],
  [0.00003, 2, -1, 0, 0], [0.00003, 2, 0, 1, 0], [-0.00003, 2, 1, -1, 0],
  [0.00003, 1, 2, 0, 0], [0.00002, 1, 0, -2, 0], [0.00002, 0, 0, 2, -2],
  [0.00002, 0, 0, 2, 2], [0.00002, 1, -1, 1, 0], [-0.00002, 2, -1, -1, 0],
  [-0.00002, 0, 0, -1, 2]
]
const NEW_MOON_ADD = [
  [0.000325, 299.77, 0.107408], [0.000165, 251.88, 0.016321], [0.000164, 251.83, 26.651886],
  [0.000126, 349.42, 36.412478], [0.000110, 84.66, 18.206239], [0.000062, 141.74, 53.303771],
  [0.000060, 207.14, 2.453732], [0.000056, 154.84, 7.306860], [0.000047, 34.52, 27.261239],
  [0.000042, 207.19, 0.121824], [0.000040, 291.34, 1.844379], [0.000037, 161.72, 24.198154],
  [0.000035, 239.56, 25.513099], [0.000023, 331.55, 3.592518]
]

/** 第 k 个朔的北京日期（k=0 约当 2000-01-06） */
function newMoonDate(k) {
  const T = k / 1236.85
  const T2 = T * T
  const T3 = T2 * T
  const T4 = T3 * T

  let jde = 2451550.09766 + 29.530588861 * k + 0.00015437 * T2 - 0.000000150 * T3 + 0.00000000073 * T4

  const E = 1 - 0.002516 * T - 0.0000074 * T2
  const M = 2.5534 + 29.10535670 * k - 0.0000014 * T2 - 0.00000011 * T3
  const Mp = 201.5643 + 385.81693528 * k + 0.0107582 * T2 + 0.00001238 * T3 - 0.000000058 * T4
  const F = 160.7108 + 390.67050284 * k - 0.0016118 * T2 - 0.00000227 * T3 + 0.000000011 * T4
  const Om = 124.7746 - 1.56375588 * k + 0.0020672 * T2 + 0.00000215 * T3

  let corr = 0
  for (const [c, m, mp, f, om] of NEW_MOON_COEF) {
    const e = Math.abs(m) === 1 ? E : Math.abs(m) === 2 ? E * E : 1
    corr += c * e * sin(m * M + mp * Mp + f * F + om * Om)
  }
  jde += corr

  let add = 0
  for (const [c, a0, a1] of NEW_MOON_ADD) add += c * sin(a0 + a1 * k)
  jde += add

  const utc = jdToDate(jde)
  // 北京时间 = UTC + 8h；再减去 ΔT 影响（JDE 已是力学时，转世界时需减 ΔT）
  const yEst = utc.getUTCFullYear()
  return new Date(utc.getTime() + 8 * 3600 * 1000 - deltaTSeconds(yEst) * 1000)
}

/* ------------------------------------------------------------------ 太阳黄经 */

/** 太阳视黄经（度），Meeus 低精度式，误差约 0.01° */
function sunLongitude(jde) {
  const T = (jde - 2451545.0) / 36525
  const L0 = 280.46646 + 36000.76983 * T + 0.0003032 * T * T
  const M = 357.52911 + 35999.05029 * T - 0.0001537 * T * T
  const C = (1.914602 - 0.004817 * T - 0.000014 * T * T) * sin(M)
    + (0.019993 - 0.000101 * T) * sin(2 * M)
    + 0.000289 * sin(3 * M)
  const trueLong = L0 + C
  const omega = 125.04 - 1934.136 * T
  const apparent = trueLong - 0.00569 - 0.00478 * sin(omega)
  return mod(apparent, 360)
}

/** 求太阳黄经等于 target 度的时刻（牛顿迭代，around 给初值 JD） */
function solarLongitudeJD(target, aroundJD) {
  let jd = aroundJD
  for (let i = 0; i < 12; i += 1) {
    const lon = sunLongitude(jd)
    let diff = mod(target - lon + 180, 360) - 180
    if (Math.abs(diff) < 1e-6) break
    jd += diff * 365.2422 / 360
  }
  return jd
}

/** 冬至（太阳黄经 270°）的 JD，返回北京日期 */
function winterSolsticeDate(year) {
  // 冬至在 12 月 21 日前后
  const approx = dateToJD(new Date(Date.UTC(year, 11, 21, 12)))
  const jd = solarLongitudeJD(270, approx)
  const utc = jdToDate(jd)
  return { jd, date: new Date(utc.getTime() + 8 * 3600 * 1000) }
}

/* ---------------------------------------------------------------- 农历主逻辑 */

const MONTH_NAMES = ['正', '二', '三', '四', '五', '六', '七', '八', '九', '十', '冬', '腊']

function dayName(d) {
  if (d === 10) return '初十'
  if (d === 20) return '二十'
  if (d === 30) return '三十'
  const tens = ['初', '十', '廿', '三']
  return tens[Math.floor(d / 10)] + ['一', '二', '三', '四', '五', '六', '七', '八', '九'][(d - 1) % 10]
}

/** 取「北京时间当天 00:00」的儒略日整数，用于按天比较 */
const dayNumber = (date) => Math.floor(dateToJD(date) + 0.5)

/**
 * 计算某个农历年（以该年正月初一所在公历年标识）的各月初一日期。
 * 返回 [{ index, date, jd, hasMajorTerm }]，index 0 = 正月
 */
function lunarMonthsOfYear(year) {
  // 上一个冬至（year-1 年 12 月）与本年冬至
  const prevSolstice = winterSolsticeDate(year - 1)
  const thisSolstice = winterSolsticeDate(year)

  // 找到冬至所在月的朔（从冬至往前找最近的朔）
  const est = Math.floor((prevSolstice.jd - 2451550.09766) / 29.530588861)
  let startK = est
  for (let k = est + 2; k >= est - 3; k -= 1) {
    if (dayNumber(newMoonDate(k)) <= dayNumber(prevSolstice.date)) { startK = k; break }
  }

  // 收集从该朔开始、跨越到下一个冬至之后的所有朔
  const moons = []
  for (let k = startK; k < startK + 16; k += 1) {
    const d = newMoonDate(k)
    moons.push({ k, date: d, day: dayNumber(d) })
    if (moons.length > 2 && moons[moons.length - 1].day > dayNumber(thisSolstice.date)) break
  }

  // 农历十一月 = 含冬至的那个月
  let month11Index = 0
  for (let i = 0; i < moons.length - 1; i += 1) {
    if (moons[i].day <= dayNumber(prevSolstice.date) && dayNumber(prevSolstice.date) < moons[i + 1].day) {
      month11Index = i
      break
    }
  }

  // 两个冬至之间的朔望月个数：13 个则需置闰
  const monthCount = moons.length - 1
  // 正月 = 十一月之后第 2 个月
  const zhengIndex = month11Index + 2

  // 判断闰月：正月与下一年正月之间若有 13 个月，则第一个无中气的月为闰月
  const result = moons.slice(zhengIndex, zhengIndex + 13).map((m, i) => ({
    index: i,
    date: m.date,
    day: m.day,
    next: moons[zhengIndex + i + 1] ? moons[zhengIndex + i + 1].day : null
  }))

  // 中气判定：该月是否包含 30° 整数倍的太阳黄经时刻
  const MAJOR_TERMS = [330, 0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300]
  const withTerm = result.map((m) => {
    const end = m.next === null ? m.day + 30 : m.next
    let has = false
    for (const t of MAJOR_TERMS) {
      const jd = solarLongitudeJD(t, m.day - 0.5 + 15)
      const d = dayNumber(jdToDate(jd + 8 / 24))
      if (d >= m.day && d < end) { has = true; break }
    }
    return { ...m, hasMajorTerm: has }
  })

  // 若 13 个月里有 12 个中气，则第一个没有中气的月是闰月
  const leapCount = withTerm.filter((m) => !m.hasMajorTerm).length
  return { months: withTerm, needLeap: leapCount > 0, monthCount }
}

/**
 * 公历日期 → 农历
 * @param {Date} [date]
 * @returns {{year:number, month:number, day:number, isLeap:boolean, monthText:string, dayText:string, text:string}}
 */
export function toLunar(date) {
  const d = date || new Date()
  const targetDay = dayNumber(d)

  // 先确定农历年：找到「正月初一」不晚于今天的那个农历年
  let lunarYear = d.getFullYear()
  for (let y = d.getFullYear() + 1; y >= d.getFullYear() - 2; y -= 1) {
    const { months } = lunarMonthsOfYear(y)
    if (months.length && months[0].day <= targetDay) { lunarYear = y; break }
  }

  const { months } = lunarMonthsOfYear(lunarYear)

  // 逐月找目标日落在哪个月
  let mi = 0
  for (let i = 0; i < months.length; i += 1) {
    if (months[i].day <= targetDay) mi = i
    else break
  }
  const m = months[mi]
  const day = targetDay - m.day + 1

  // 若有闰月：需要标注是闰几月。闰月的 index 在正常月份之后
  // 这里通过「该月是否含中气」判断：不含中气即为闰月
  const isLeap = !m.hasMajorTerm && months.filter((x, i2) => i2 <= mi && !x.hasMajorTerm).length === 1

  // 月份序号：正月为 1，按含中气与否推进
  let monthNo = 0
  for (let i = 0; i <= mi; i += 1) {
    if (!months[i].hasMajorTerm && i !== 0) continue // 闰月不占月序
    monthNo += 1
  }
  if (monthNo < 1) monthNo = 1
  if (monthNo > 12) monthNo = 12

  const monthText = (isLeap ? '闰' : '') + MONTH_NAMES[monthNo - 1] + '月'
  const dayText = dayName(day)

  return {
    year: lunarYear,
    month: monthNo,
    day,
    isLeap,
    monthText,
    dayText,
    text: monthText + dayText
  }
}

/** 便捷：农历文案，如「八月十七」 */
export function todayLunarText(date) {
  return toLunar(date).text
}

export default toLunar

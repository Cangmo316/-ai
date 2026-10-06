/**
 * 比邻AI · 口型驱动（lip-sync driver）
 *
 * 输入：服务端 SSE `lipsync` 事件给的**关键帧**（`{b, e, v[]}`，单位毫秒）。
 * 输出：每个动画帧调用 `stage.setVisemes({...})`，把 15 个 `vis_*` 形态键的权重写到模型上。
 *
 * ## 为什么需要这个模块（而不是直接把 cues 丢给渲染器）
 *
 * 1. **渲染器不归零**：`face-three.js` 的 `setVisemes` 只写传入的键、**不把没传的键归零**
 *    （见其注释）。所以每帧必须给出**完整的 15 个键**，否则上一帧的口型会残留挂在脸上。
 * 2. **要做交叉淡化**：直接按区间硬切会有"啪"的跳变。按 `timingHint.crossfadeMs`（50ms）
 *    在相邻关键帧之间过渡，观感才连贯。
 * 3. **权重和 <= 1**：同一时刻总权重超过 1 会让形态键叠加过度（嘴被"拉爆"）。
 *
 * ## 与音频的关系（重要）
 *
 * 当前时间轴是服务端按字数**估算**的（`source: 'estimated'`）。本驱动用
 * `performance.now()` 自建时钟推进。真 TTS 就绪后应改为**以音频播放时刻为基准**
 * （否则音画会漂移）；届时只要把 `start(nowMs)` 的基准换成音频时钟即可，**本模块其余不动**。
 */

/** 交叉淡化时长（毫秒），与 `morph-viseme-cosyvoice2.json` 的 timingHint 一致。 */
export const CROSSFADE_MS = 50

/** 口型键全量清单（每帧都要给全，见模块注释第 1 条）。 */
/** 同一时刻最多混合的 viseme 数（来自 morph-viseme-cosyvoice2.json 的 timingHint）。 */
export const MAX_BLEND = 2

export const VISEME_KEYS = Object.freeze([
  'vis_silence', 'vis_AA', 'vis_E', 'vis_I', 'vis_O', 'vis_U', 'vis_MBP', 'vis_FV',
  'vis_L', 'vis_TH', 'vis_WQ', 'vis_RR', 'vis_SS', 'vis_KK', 'vis_NN',
])

function emptyFrame() {
  const frame = {}
  for (const key of VISEME_KEYS) frame[key] = 0
  return frame
}

/**
 * 把关键帧整理成便于按时间取样的形式。
 *
 * 做两件事：
 *   · 关键帧按 `b` 排序（服务端理论上已排好，但防御性排一次）
 *   · 记住每个关键帧的 `v` 列表（最多 2 个，后端已收敛）
 */
export function buildTrack(cues) {
  const list = Array.isArray(cues)
    ? cues
      .filter((cue) => cue && typeof cue.b === 'number' && typeof cue.e === 'number'
        && Array.isArray(cue.v) && cue.v.length > 0)
      .slice()
      .sort((a, b) => a.b - b.b)
    : []
  const duration = list.length ? list[list.length - 1].e : 0
  return { cues: list, durationMs: duration }
}

/**
 * 在 `tMs` 时刻取样，返回**完整 15 键**的权重表。
 *
 * 交叉淡化规则：每个关键帧的权重在其区间内为 1，并在**区间两端各 CROSSFADE_MS**
 * 内向相邻帧过渡（线性）。总权重按最大值归一化（而不是简单求和），
 * 这样两个 viseme 各 1.0 时不会变成"各自 0.5 而整体塌掉"。
 */
export function sampleAt(track, tMs) {
  const frame = emptyFrame()
  const { cues } = track
  if (!cues.length) {
    frame.vis_silence = 1
    return frame
  }
  // ⚠️ 负数时间/早于首帧要**在夹紧之前**判掉：`Math.max(0, t)` 会把"还没开始"夹成 0，
  //    而 0 通常落在第一帧区间内 → "还没开始"被误判成"第一帧正在进行"（测试抓到的 bug）。
  if (tMs < cues[0].b) {
    frame.vis_silence = 1
    return frame
  }
  const t = Math.max(0, tMs)
  // 找到当前区间（cues 已排序）
  let index = -1
  for (let i = 0; i < cues.length; i += 1) {
    if (t >= cues[i].b && t < cues[i].e) { index = i; break }
  }
  if (index === -1) {
    // 越界一律回静止：
    //   · 已经说过（t >= 最后一个区间的结尾）→ 嘴闭上，否则口型会"挂在脸上"
    //   · 还没开始（t 在第一个区间之前）→ 同样静止
    // 第一版这里只处理了"之后"，测试直接抓出来了。
    frame.vis_silence = 1
    return frame
  }

  const current = cues[index]
  const prev = index > 0 ? cues[index - 1] : null
  const next = index + 1 < cues.length ? cues[index + 1] : null

  const applyTo = (keyList, weight) => {
    if (weight <= 0) return
    const each = weight / keyList.length
    for (const key of keyList) {
      if (!(key in frame)) continue
      frame[key] = Math.max(frame[key], each)
    }
  }

  // 本体
  applyTo(current.v, 1)

  // 淡化窗长：取"本区间一半"与 CROSSFADE_MS 的较小者。
  // 短音的区间本来就短，用固定 50ms 会越过边界、把相邻音一路拖到区间末尾。
  const halfSpan = (current.e - current.b) / 2
  const fadeSpan = Math.min(CROSSFADE_MS, halfSpan)

  // ⚠️ **本帧自带 2 个音时不做交叉淡化**。
  //    否则"本帧 2 个 + 相邻帧 2 个"会同时混到 4 个，违反 timingHint 的
  //    「同一时刻最多混 2 个 viseme」（实测 t=170 处出现 vis_AA/vis_I/vis_MBP/vis_NN 四个）。
  //    单音帧才需要淡化过渡（它自己只有 1 个音，加相邻 1 个正好 2 个）。
  const single = current.v.length === 1

  if (single && prev && fadeSpan > 0 && t - current.b < fadeSpan) {
    applyTo(prev.v, 1 - (t - current.b) / fadeSpan)
  }
  if (single && next && fadeSpan > 0 && current.e - t < fadeSpan) {
    applyTo(next.v, 1 - (current.e - t) / fadeSpan)
  } else if (single && !next && prev && fadeSpan > 0 && current.e - t < fadeSpan) {
    // 最后一个音：淡出到**静止**而不是停住（否则最后一句的口型会一直挂着）
    const alpha = 1 - (current.e - t) / fadeSpan
    applyTo(current.v, 1 - alpha)
    frame.vis_silence = Math.max(frame.vis_silence, alpha)
  }

  // 归一化到总权重 <= 1：形态键权重和 > 1 会叠加过度（"嘴被拉爆"）。
  // 交叉淡化期间"前音 + 本音"必然同时 > 0，所以这一步是必须的，不是保险。
  let total = 0
  for (const key of VISEME_KEYS) total += frame[key]
  if (total > 1) {
    for (const key of VISEME_KEYS) frame[key] /= total
  }

  // 最后一道硬约束：**最多同时 2 个 viseme**（timingHint.maxCoarticulationBlend）。
  // 前面已经避免了"2+2=4"，但"淡出到静止 + 本帧 2 个音"这类边界仍会到 3 个。
  // 与其逐个组合去堵，不如按权重裁一刀 —— 这条对**任何输入**都成立。
  const positives = VISEME_KEYS.filter((key) => frame[key] > 0)
  if (positives.length > MAX_BLEND) {
    positives.sort((a, b) => frame[b] - frame[a])
    for (const key of positives.slice(MAX_BLEND)) frame[key] = 0
    let kept = 0
    for (const key of VISEME_KEYS) kept += frame[key]
    if (kept > 0 && kept !== 1) {
      for (const key of VISEME_KEYS) frame[key] /= kept
    }
  }
  return frame
}

/**
 * 创建一个口型播放器。
 *
 * @param {object} options
 *   · `heightOf(key)`  → 该 viseme 的开口幅度上限（默认 1；可用于压低某些音的幅度）
 *   · `onFrame(frame)` → 每帧回调，把完整权重表交给渲染器
 *   · `now()`          → 取当前时间（默认真实时钟，测试时可注入）
 *   · `fps`            → 驱动频率，默认 30（与 `uni-app` 的 30Hz 下发口径一致）
 */
export function createLipsyncPlayer(options) {
  const opt = options || {}
  const fps = Math.max(10, Math.min(60, opt.fps || 30))
  const interval = 1000 / fps
  const now = typeof opt.now === 'function' ? opt.now : () => performance.now()
  const onFrame = typeof opt.onFrame === 'function' ? opt.onFrame : () => {}
  const heightOf = typeof opt.heightOf === 'function' ? opt.heightOf : () => 1

  let track = { cues: [], durationMs: 0 }
  let startedAt = 0
  let timer = null
  let playing = false

  function tick() {
    if (!playing) return
    const t = now() - startedAt
    if (t >= track.durationMs) {
      stop()
      // 收尾必须送一帧全静止：否则最后一句的口型会一直挂在脸上
      const rest = emptyFrame()
      rest.vis_silence = 1
      onFrame(rest)
      return
    }
    const frame = sampleAt(track, t)
    for (const key of VISEME_KEYS) frame[key] *= heightOf(key)
    onFrame(frame)
  }

  function start(cues, startAtMs) {
    stop()
    track = buildTrack(cues)
    if (!track.cues.length) return { ok: false, reason: '没有可用的口型关键帧' }
    // `_startAtMs` 目前未用于"从音频第 N 毫秒开始"（真 TTS 对齐后才需要），
    // 保留形参是为了让调用方现在就能按最终签名传参，届时不必改调用点。
    void startAtMs
    startedAt = now() - (opt.offsetMs || 0)
    playing = true
    tick()
    timer = setInterval(tick, interval)
    return { ok: true, durationMs: track.durationMs, fps }
  }

  function stop() {
    playing = false
    if (timer) { clearInterval(timer); timer = null }
  }

  return {
    start,
    stop,
    isPlaying: () => playing,
    /** 诊断用：当前进度（毫秒）与总时长 */
    stats: () => ({
      playing,
      cues: track.cues.length,
      durationMs: track.durationMs,
      elapsedMs: playing ? Math.round(now() - startedAt) : 0,
    }),
  }
}

export default { CROSSFADE_MS, VISEME_KEYS, buildTrack, sampleAt, createLipsyncPlayer }

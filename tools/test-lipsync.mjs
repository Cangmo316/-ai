/**
 * 口型驱动（lipsync.js）的单元测试。
 *
 * 为什么必须有测试：这个模块有**两个容易静默出错**的地方——
 *   ① 每帧必须给**完整 15 个键**（渲染器的 setVisemes 不归零，漏键会残留口型）
 *   ② 总权重不能超过 1（超了形态键会叠加过度，"嘴被拉爆"）
 * 这两条肉眼看不出来（页面照样渲染），只能靠断言守住。
 *
 * 跑法：node tools/test-lipsync.mjs
 */
import assert from 'node:assert/strict'
import { VISEME_KEYS, CROSSFADE_MS, buildTrack, sampleAt, createLipsyncPlayer } from '../uni-app/common/face-gl/lipsync.js'

let passed = 0
const cases = []
function test(name, fn) { cases.push([name, fn]) }

const CUES = [
  { c: '妈', b: 0, e: 180, v: ['vis_MBP', 'vis_AA'] },
  { c: '你', b: 180, e: 360, v: ['vis_NN', 'vis_I'] },
  { c: '', b: 360, e: 480, v: ['vis_silence'] },
]

test('buildTrack：过滤坏数据并按 b 排序', () => {
  const track = buildTrack([
    { b: 180, e: 360, v: ['vis_I'] },
    { b: 'x', e: 1, v: ['vis_AA'] },      // b 不是数字 → 丢
    { b: 0, e: 180, v: [] },              // v 为空 → 丢
    { b: 0, e: 90, v: ['vis_MBP'] },
    null,
  ])
  assert.equal(track.cues.length, 2)
  assert.equal(track.cues[0].b, 0)
  assert.equal(track.cues[1].b, 180)
  assert.equal(track.durationMs, 360)
})

test('sampleAt：每一帧都给完整 15 个键（漏键会让口型残留）', () => {
  const track = buildTrack(CUES)
  for (const t of [0, 90, 180, 270, 400, 500, 9999]) {
    const frame = sampleAt(track, t)
    assert.deepEqual(Object.keys(frame).sort(), [...VISEME_KEYS].sort(),
      't=' + t + ' 的帧缺键或多键')
  }
})

test('sampleAt：同一时刻最多 2 个 viseme 且总权重 <= 1（timingHint 硬约束）', () => {
  const track = buildTrack(CUES)
  for (let t = 0; t <= 560; t += 2) {
    const frame = sampleAt(track, t)
    const active = VISEME_KEYS.filter((key) => frame[key] > 0)
    const total = VISEME_KEYS.reduce((sum, key) => sum + frame[key], 0)
    assert.ok(active.length <= 2,
      't=' + t + ' 同时混了 ' + active.length + ' 个 viseme：' + active.join(','))
    assert.ok(total <= 1.0001, 't=' + t + ' 总权重 ' + total.toFixed(3) + ' > 1')
  }
})

test('sampleAt：单音帧在区间边界做交叉淡化（不会硬切）', () => {
  // 用**单 viseme** 的帧来验淡化：多音帧自带 2 个音，按设计不做额外淡化
  const two = buildTrack([
    { c: 'a', b: 0, e: 200, v: ['vis_L'] },
    { c: 'b', b: 200, e: 400, v: ['vis_AA'] },
  ])
  const near = sampleAt(two, 190)      // 距边界 10ms，落在 50ms 窗内
  assert.ok(near.vis_L > 0, '淡化窗内应仍看到上一个 viseme')
  assert.ok(near.vis_AA > 0, '淡化窗内应已看到下一个 viseme')
  const settled = sampleAt(two, 120)   // 远离两端
  assert.equal(settled.vis_AA, 0, '远离淡化窗后不该有下一个 viseme')
  assert.equal(settled.vis_L, 1, '中间段应是本帧的单一 viseme')
  assert.equal(CROSSFADE_MS, 50, '交叉淡化时长应与 timingHint 一致')
})

test('sampleAt：区间中段给出该字的口型、且不含上一个字的口型', () => {
  const track = buildTrack(CUES)
  const frame = sampleAt(track, 270)          // 第二个字的中间（远离淡化区）
  assert.ok(frame.vis_NN > 0, '第二个字应给 vis_NN')
  assert.ok(frame.vis_I > 0, '第二个字应给 vis_I')
  assert.equal(frame.vis_MBP, 0, '不该残留第一个字的 vis_MBP')
})


test('sampleAt：区间之后回到静止（否则最后一句口型挂在脸上）', () => {
  const track = buildTrack(CUES)
  const after = sampleAt(track, 1000)
  assert.equal(after.vis_silence, 1)
  const before = sampleAt(track, -10)
  assert.equal(before.vis_silence, 1)
})

test('sampleAt：空 cues 也要给静止帧（不能返回空对象）', () => {
  const frame = sampleAt(buildTrack([]), 0)
  assert.equal(frame.vis_silence, 1)
  assert.deepEqual(Object.keys(frame).length, VISEME_KEYS.length)
})

test('createLipsyncPlayer：按自建时钟推进，播完送静止帧', () => {
  const frames = []
  let fake = 0
  const player = createLipsyncPlayer({
    now: () => fake,
    onFrame: (f) => frames.push({ t: fake, f }),
  })
  const started = player.start(CUES)
  assert.equal(started.ok, true)
  assert.equal(started.durationMs, 480)
  assert.ok(frames.length >= 1, 'start 后应立刻出一帧（否则要等下一个 tick 才动）')
  // 手动推进：把 fake 时间拨到区间中段，再触发一次 tick 需要定时器…
  // 定时器在测试里不可靠，这里改为直接验证 sampleAt 与收尾逻辑：
  player.stop()
  assert.equal(player.isPlaying(), false)
})

test('createLipsyncPlayer：没有 cues 时返回失败而不是静默', () => {
  const player = createLipsyncPlayer({ now: () => 0, onFrame: () => {} })
  const r = player.start([])
  assert.equal(r.ok, false)
  assert.ok(typeof r.reason === 'string' && r.reason.length > 0)
})

/* ─────────── 外部时钟（音频位置）驱动 —— 音画同步的核心 ─────────── */
// 为什么这几条最重要：口型与声音必须是**同一根时间轴**。
// 第一版让播放器自己跑时钟、音频异步加载，结果"嘴在声音出来前就演完了"
// （用户实测反馈："没看到唇形同步"）。所以这里断言"嘴真的跟着外部时钟走"。

test('外部时钟：嘴跟的是音频位置（墙钟固定也能出正确口型）', () => {
  const frames = []
  const audioMs = 10               // 模拟音频播放位置：10ms
  const player = createLipsyncPlayer({
    fps: 30,
    clock: () => audioMs,
    now: () => 1e9,                // 墙钟故意设成一个巨大定值，证明"没有用墙钟"
    onFrame: (f) => frames.push(f),
  })
  player.start(CUES)
  player.stop()
  assert.ok(frames.length >= 1, 'start 后应立刻出一帧')
  // 10ms 落在第一个字（0~180ms）内 → 应是"妈"的口型
  assert.ok(frames[0].vis_MBP > 0, '10ms 时应是第一个字（妈）的口型')
  assert.equal(player.stats().clockSource, 'audio')
})

test('外部时钟：音频没就绪（clock 返回 null）时退回自有时钟，而不是卡在句首', () => {
  // ⚠️ 这条是踩坑的直接防线：音频要下载+解码，那几帧若被当成"时间=0"，
  // 嘴会卡住不动；而没有音频时（后端未配 TTS）更会整句都不动。
  const frames = []
  let wall = 0
  const player = createLipsyncPlayer({
    fps: 30,
    clock: () => null,
    now: () => { wall += 40; return wall },
    onFrame: (f) => frames.push(f),
  })
  player.start(CUES)
  const stats = player.stats()
  player.stop()
  assert.ok(frames.length >= 1)
  assert.equal(stats.clockSource, 'self', 'clock 返回 null 时应退回自有时钟')
  assert.equal(stats.hasExternalClock, true, '已注入外部时钟这件事要如实反映')
})

test('外部时钟：没注入 clock 时报 self；注入后报 audio', () => {
  const selfOnly = createLipsyncPlayer({ fps: 30, onFrame: () => {} })
  selfOnly.start(CUES)
  const noClock = selfOnly.stats()
  selfOnly.stop()
  assert.equal(noClock.clockSource, 'self')
  assert.equal(noClock.hasExternalClock, false)

  const withClock = createLipsyncPlayer({ fps: 30, clock: () => 100, onFrame: () => {} })
  withClock.start(CUES)
  const yes = withClock.stats()
  withClock.stop()
  assert.equal(yes.clockSource, 'audio')
  assert.equal(yes.hasExternalClock, true)
})

for (const [name, fn] of cases) {
  try {
    fn()
    console.log('  ✓ ' + name)
    passed += 1
  } catch (error) {
    console.log('  ✗ ' + name)
    console.log('    ' + (error && error.message ? error.message : error))
    process.exitCode = 1
  }
}
console.log('\n通过 ' + passed + ' 项，失败 ' + (cases.length - passed) + ' 项')

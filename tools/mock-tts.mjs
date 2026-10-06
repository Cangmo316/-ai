#!/usr/bin/env node
/**
 * 比邻AI · mock 的语音合成桥（命令行跑 mock 时默认开，--no-tts 关闭；测试以 import 起 mock，不受影响）
 *
 * ## 为什么要有这一层
 *
 * mock 原来只发一段 3 秒的**类人声脉冲串**（mock-server 里的 buildToneWav）。
 * 它能证明"链路里有声音"，但**证明不了"听到的是人话"** —— 用户说的
 * "数字人说话没声音"，指的正是"听到的不是人话"。只有真语音才能让这句话在观感上一秒判定。
 *
 * ## 三条硬约束
 *
 * 1. **默认关**：`tools/test-*.mjs` 是同进程 import mock 的，测试必须与本机
 *    装没装中文声部无关。关着时行为与以前**逐字节一致**（还是 buildToneWav）。
 * 2. **失败必须静默降级**：沙箱/服务会话/无中文声部的机器上，SAPI 连"播到默认设备"
 *    都是 0x80070005（Access denied，实测）。任何失败都回落蜂鸣音，
 *    **不许**让语音把对话链路拖垮（对话内容本身才是主线）。
 * 3. **时长以真音频为准**：`audio.durationMs` 必须等于发出去那些字节的时长，
 *    口型时间轴再按它缩放 —— 否则又回到"嘴先停、声音还在响"那个坑。
 *
 * ## 缓存与并行
 *
 * 合成一次约 0.3–0.8s（含起一个 PowerShell 进程）。同一句不必重复合成：
 * 按「声部 + 语速 + 文本」做键缓存到**系统临时目录**（运行时数据不进仓库，也不污染工作区）。
 * mock 在逐字吐字的同时就发起合成（见 mock-server 的 prepareSpeech），
 * 写 `audio` 事件时才 await，首字延迟不受影响。
 *
 * ## 换实现（也用于 CI / Linux）：`BILIN_MOCK_TTS_CMD`
 *
 *     BILIN_MOCK_TTS_CMD="node tools/mock-tts-stub.mjs"
 *
 * 命令后面会追加两个参数：`<文本文件> <输出 wav>`。退出码 0 且输出是**非静音 WAV** 才算成功。
 * `tools/mock-tts-stub.mjs` 是这个约定的参照实现（测试就用它）。
 *
 * ## 环境变量
 *
 * | 变量 | 默认 | 说明 |
 * |---|---|---|
 * | `BILIN_MOCK_TTS` | `0` | `1` 打开真语音 |
 * | `BILIN_MOCK_TTS_CMD` | 空 | 自定义合成命令（覆盖内置的 SAPI 脚本） |
 * | `BILIN_MOCK_TTS_VOICE` | `Chinese` | 声部名匹配子串（SAPI 下即『Microsoft Huihui Desktop - Chinese (Simplified)』） |
 * | `BILIN_MOCK_TTS_RATE` | `1` | SAPI 语速 -10..10（1 = 比默认略慢，适老但不像念稿） |
 * | `BILIN_MOCK_TTS_TIMEOUT_MS` | `15000` | 单次合成超时（超了杀进程并回落） |
 * | `BILIN_MOCK_TTS_CACHE` | `<temp>/bilin-mock-tts` | 缓存目录 |
 * | `BILIN_MOCK_TTS_CACHE_ONLY` | `0` | `1` = 只读缓存不合成（离线预热/受限环境） |
 */
import { spawn } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const TOOLS_DIR = path.dirname(fileURLToPath(import.meta.url))
const PS_SCRIPT = path.join(TOOLS_DIR, 'mock-tts.ps1')

/** 判"到底有没有声音"的阈值，与 tools/test-audio-channel.mjs 的断言同一口径 */
const MIN_PEAK = 0.05
const MIN_DURATION_MS = 150

function envFlag(name, fallback) {
  const raw = String(process.env[name] === undefined ? '' : process.env[name]).trim().toLowerCase()
  if (!raw) return fallback
  if (raw === '1' || raw === 'on' || raw === 'true' || raw === 'yes') return true
  if (raw === '0' || raw === 'off' || raw === 'false' || raw === 'no') return false
  return fallback
}

/** 真语音是否打开（**默认关**：测试必须与本机环境无关） */
export function ttsEnabled() {
  return envFlag('BILIN_MOCK_TTS', false)
}

function powershellPath() {
  const root = process.env.SystemRoot || process.env.windir || 'C:\\Windows'
  return path.join(root, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
}

/** 按空格切命令，但尊重双引号（路径里可能有空格） */
function splitCommand(text) {
  const parts = []
  let current = ''
  let quote = false
  for (const ch of String(text)) {
    if (ch === '"') { quote = !quote; continue }
    if (!quote && (ch === ' ' || ch === '\t')) {
      if (current) { parts.push(current); current = '' }
      continue
    }
    current += ch
  }
  if (current) parts.push(current)
  return { file: parts[0], args: parts.slice(1), custom: true }
}

function ttsConfig() {
  const custom = String(process.env.BILIN_MOCK_TTS_CMD || '').trim()
  const rateRaw = Number(process.env.BILIN_MOCK_TTS_RATE)
  const timeoutRaw = Number(process.env.BILIN_MOCK_TTS_TIMEOUT_MS)
  const cfg = {
    enabled: ttsEnabled(),
    custom: Boolean(custom),
    voice: String(process.env.BILIN_MOCK_TTS_VOICE || 'Chinese'),
    rate: Number.isFinite(rateRaw) ? rateRaw : 1,
    timeoutMs: Number.isFinite(timeoutRaw) && timeoutRaw > 0 ? timeoutRaw : 15000,
    cacheDir: String(process.env.BILIN_MOCK_TTS_CACHE || path.join(os.tmpdir(), 'bilin-mock-tts')),
    cacheOnly: envFlag('BILIN_MOCK_TTS_CACHE_ONLY', false),
    command: custom ? splitCommand(custom) : {
      file: powershellPath(),
      args: ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', PS_SCRIPT],
      custom: false
    }
  }
  return cfg
}

/** 给 mock 的 /healthz 与启动日志用（把"到底有没有真语音"如实报出来） */
export function ttsStatus() {
  const cfg = ttsConfig()
  return {
    enabled: cfg.enabled,
    mode: cfg.enabled ? (cfg.custom ? 'custom-command' : 'windows-sapi') : 'off',
    voice: cfg.voice,
    rate: cfg.rate,
    cacheDir: cfg.cacheDir,
    cacheOnly: cfg.cacheOnly
  }
}

/**
 * PowerShell 5.1 的 stderr 是**本机 ANSI 码页**（中文机器上就是 GBK），
 * 直接拼进日志必然是乱码。只保留 ASCII：够定位（退出码 + 英文标记），也不污染日志。
 */
function asciiOnly(text) {
  return String(text || '').replace(/[^\x20-\x7E]/g, '').replace(/\s+/g, ' ').trim()
}

function buildArgs(cfg, textFile, outFile) {
  if (cfg.custom) return cfg.command.args.concat([textFile, outFile])
  return cfg.command.args.concat([
    '-Rate', String(cfg.rate),
    '-VoiceMatch', cfg.voice,
    '-TextFile', textFile,
    '-OutFile', outFile
  ])
}

function cacheKey(text, cfg) {
  const payload = [cfg.voice, String(cfg.rate), cfg.custom ? 'custom' : 'sapi', text].join('\u0000')
  let hash = 0xcbf29ce484222325n
  const prime = 0x100000001b3n
  const mask = 0xffffffffffffffffn
  for (let i = 0; i < payload.length; i += 1) {
    hash = (hash ^ BigInt(payload.charCodeAt(i))) & mask
    hash = (hash * prime) & mask
  }
  return hash.toString(16).padStart(16, '0')
}

/**
 * 解析 WAV 头（按块遍历，不假设固定 44 字节），并顺手算峰值/RMS。
 * 返回 null 表示"这不是一段能用的 WAV"。
 */
export function wavInfo(buffer) {
  if (!buffer || buffer.length < 44) return null
  if (buffer.toString('ascii', 0, 4) !== 'RIFF' || buffer.toString('ascii', 8, 12) !== 'WAVE') return null
  let offset = 12
  let fmt = null
  let data = null
  while (offset + 8 <= buffer.length) {
    const id = buffer.toString('ascii', offset, offset + 4)
    const size = buffer.readUInt32LE(offset + 4)
    const body = offset + 8
    if (id === 'fmt ' && size >= 16 && body + 16 <= buffer.length) {
      fmt = {
        channels: buffer.readUInt16LE(body + 2),
        sampleRate: buffer.readUInt32LE(body + 4),
        bits: buffer.readUInt16LE(body + 14)
      }
    } else if (id === 'data') {
      data = { start: body, bytes: Math.min(size, Math.max(0, buffer.length - body)) }
    }
    offset = body + size + (size % 2)
  }
  if (!fmt || !data || !fmt.channels || !fmt.sampleRate || !fmt.bits) return null
  const frameBytes = (fmt.bits / 8) * fmt.channels
  if (!frameBytes) return null
  const frames = Math.floor(data.bytes / frameBytes)
  let peak = null
  let rms = null
  if (fmt.bits === 16) {
    let sum = 0
    let count = 0
    peak = 0
    for (let i = 0; i + 1 < data.bytes; i += 2) {
      const value = buffer.readInt16LE(data.start + i) / 32768
      const magnitude = value < 0 ? -value : value
      if (magnitude > peak) peak = magnitude
      sum += value * value
      count += 1
    }
    rms = count ? Math.sqrt(sum / count) : 0
  }
  return {
    channels: fmt.channels,
    sampleRate: fmt.sampleRate,
    bits: fmt.bits,
    durationMs: (frames / fmt.sampleRate) * 1000,
    peak,
    rms
  }
}

function runCommand(file, args, timeoutMs) {
  return new Promise((resolve) => {
    let child = null
    try {
      child = spawn(file, args, { windowsHide: true })
    } catch (error) {
      resolve({ code: -1, stdout: '', stderr: String((error && error.message) || error) })
      return
    }
    let stdout = ''
    let stderr = ''
    let settled = false
    const finish = (code, extra) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve({ code, stdout, stderr: stderr + (extra || '') })
    }
    const timer = setTimeout(() => {
      try { child.kill() } catch (error) { void error }
      finish(-9, ' [超时 ' + timeoutMs + 'ms]')
    }, timeoutMs)
    if (child.stdout) child.stdout.on('data', (chunk) => { stdout += chunk })
    if (child.stderr) child.stderr.on('data', (chunk) => { stderr += chunk })
    child.on('error', (error) => finish(-1, ' ' + String((error && error.message) || error)))
    child.on('close', (code) => finish(typeof code === 'number' ? code : -1))
  })
}

async function readAudio(file) {
  let buffer = null
  try {
    buffer = await readFile(file)
  } catch (error) {
    void error
    return null
  }
  const info = wavInfo(buffer)
  if (!info) return null
  if (info.durationMs < MIN_DURATION_MS) return null
  if (typeof info.peak === 'number' && info.peak < MIN_PEAK) return null
  return { bytes: buffer, info }
}

/**
 * 合成一段语音。
 * @returns {{ok:true, bytes:Buffer, durationMs:number, cached:boolean, ms:number}
 *          | {ok:false, reason:string, ms:number}}  失败**不抛异常**，由调用方回落。
 */
export async function synthesizeSpeech(text) {
  const started = Date.now()
  const cfg = ttsConfig()
  if (!cfg.enabled) return { ok: false, reason: 'disabled', ms: 0 }
  const clean = String(text === undefined || text === null ? '' : text).trim()
  if (!clean) return { ok: false, reason: 'empty-text', ms: 0 }

  const key = cacheKey(clean, cfg)
  const wavPath = path.join(cfg.cacheDir, key + '.wav')
  const txtPath = path.join(cfg.cacheDir, key + '.txt')
  try {
    await mkdir(cfg.cacheDir, { recursive: true })
  } catch (error) {
    void error
  }

  const cached = await readAudio(wavPath)
  if (cached) {
    return { ok: true, bytes: cached.bytes, durationMs: cached.info.durationMs, cached: true, ms: Date.now() - started }
  }
  if (cfg.cacheOnly) return { ok: false, reason: 'cache-miss', ms: Date.now() - started }

  try {
    await writeFile(txtPath, clean, 'utf8')
  } catch (error) {
    return { ok: false, reason: 'text-write-failed: ' + String((error && error.message) || error), ms: Date.now() - started }
  }

  const result = await runCommand(cfg.command.file, buildArgs(cfg, txtPath, wavPath), cfg.timeoutMs)
  if (result.code !== 0) {
    const detail = asciiOnly(result.stderr).slice(0, 160)
    return { ok: false, reason: 'command-failed(' + result.code + ')' + (detail ? ': ' + detail : ''), ms: Date.now() - started }
  }

  const fresh = await readAudio(wavPath)
  if (!fresh) return { ok: false, reason: 'unusable-audio', ms: Date.now() - started }
  return { ok: true, bytes: fresh.bytes, durationMs: fresh.info.durationMs, cached: false, ms: Date.now() - started }
}
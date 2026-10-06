#!/usr/bin/env node
/**
 * 比邻AI · mock 语音合成的**测试替身**（等价于 tools/mock-tts.ps1 的契约）
 *
 * 契约（tools/mock-tts.mjs 按此调用）：
 *   <命令> <文本文件> <输出 wav>
 *   退出码 0 且输出是**非静音 WAV** 才算成功；否则调用方回落到蜂鸣音。
 *
 * 为什么要有它：
 *   ① 测试必须与"本机装没装中文声部"无关 —— Windows SAPI 只在普通用户会话里能出声，
 *      沙箱/CI/Linux 上必然失败。有了替身，`BILIN_MOCK_TTS_CMD="node tools/mock-tts-stub.mjs"`
 *      就能在任何机器上把**真语音那条分支**跑通并断言。
 *   ② 时长刻意做成**文本长度的函数**（0.1s/字，最少 0.5s）——这样"mock 是否真的
 *      按音频时长下发 durationMs/lipsync"是可断言的，而不是拿一个常数糊过去。
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const [textFile, outFile] = process.argv.slice(2)
if (!textFile || !outFile) {
  console.error('usage: mock-tts-stub.mjs <textFile> <outFile>')
  process.exit(2)
}

const text = readFileSync(textFile, 'utf8')
const chars = Array.from(String(text).replace(/\s/g, '')).length || 1
const seconds = Math.max(0.5, chars * 0.1)
const sampleRate = 16000
const frames = Math.round(seconds * sampleRate)

const buffer = Buffer.alloc(44 + frames * 2)
buffer.write('RIFF', 0)
buffer.writeUInt32LE(36 + frames * 2, 4)
buffer.write('WAVE', 8)
buffer.write('fmt ', 12)
buffer.writeUInt32LE(16, 16)
buffer.writeUInt16LE(1, 20)
buffer.writeUInt16LE(1, 22)
buffer.writeUInt32LE(sampleRate, 24)
buffer.writeUInt32LE(sampleRate * 2, 28)
buffer.writeUInt16LE(2, 32)
buffer.writeUInt16LE(16, 34)
buffer.write('data', 36)
buffer.writeUInt32LE(frames * 2, 40)
// 负载：220Hz 正弦 + 4 音节/秒的开口包络（非静音即可，这里验的是时长与链路，不是音色）
for (let i = 0; i < frames; i += 1) {
  const t = i / sampleRate
  const envelope = Math.pow(Math.max(0, Math.sin(2 * Math.PI * 4 * t)), 0.7)
  buffer.writeInt16LE(Math.round(Math.sin(2 * Math.PI * 220 * t) * envelope * 12000), 44 + i * 2)
}

mkdirSync(path.dirname(outFile), { recursive: true })
writeFileSync(outFile, buffer)
console.log('stub ok ' + seconds.toFixed(2) + 's')
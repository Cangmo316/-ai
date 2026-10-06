<#
  比邻AI · mock 的**离线中文语音合成**（Windows SAPI5 / Huihui）

  为什么 mock 要合成真人语音（而不是继续发蜂鸣音）：
    "数字人说话没声音"这句话，在观感上分不开两种情况 ——
      (a) 播放链路坏了；(b) 有声但是**听不懂的蜂鸣音**。
    mock 发类人声脉冲串时，(b) 会被误判成 (a)。发**能听懂的中文**，
    才能让"有没有声音"用耳朵一秒判定。

  为什么用 SAPI5 而不是百炼 Qwen-TTS：
    百炼要 DASHSCOPE_API_KEY（本机只有 DeepSeek 的 key，且要按字符计费、要出网）；
    SAPI5 是本机自带、免费、离线。生产路线仍是百炼（server/app/voice/qwen_tts.py），
    mock 只是联调靶子 —— 契约（签名 URL + durationMs）两边完全一致。

  ⚠️ 已知限制（实测）：
    · 只在**非沙箱**的普通用户会话里能出声。沙箱/服务会话里 SpVoice 连
      "播到默认设备"都会 0x80070005（Access denied），文件流写入同样被拒 →
      调用方（tools/mock-tts.mjs）必须**兜底**回 buildToneWav，不能让它拖垮链路。
    · 必须 WaitUntilDone 再 Close：不等就会把音频**截断**（实测"你好。"只留 314 字节）。

  用法（由 tools/mock-tts.mjs 调用，不直接给用户用）：
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\mock-tts.ps1 `
      -TextFile <utf8 文本文件> -OutFile <输出 wav>
    退出码 0 且 stdout 以 "ok bytes=" 开头才算成功；其余一律视为失败。
#>
param(
  [Parameter(Mandatory = $true)][string]$TextFile,
  [Parameter(Mandatory = $true)][string]$OutFile,
  [string]$VoiceMatch = 'Chinese',
  [int]$Rate = -1,
  [int]$Volume = 100,
  [int]$SampleFormat = 18,
  [int]$TimeoutMs = 60000
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $TextFile)) { [Console]::Error.WriteLine('text file not found: ' + $TextFile); exit 2 }
$text = [System.IO.File]::ReadAllText($TextFile, (New-Object System.Text.UTF8Encoding($false)))
if (-not $text.Trim()) { [Console]::Error.WriteLine('empty text'); exit 2 }

$dir = Split-Path -Parent $OutFile
if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
if (Test-Path -LiteralPath $OutFile) { Remove-Item -LiteralPath $OutFile -Force }

try {
  $voice = New-Object -ComObject SAPI.SpVoice
  $voices = $voice.GetVoices()
  $picked = $null
  for ($i = 0; $i -lt $voices.Count; $i++) {
    $desc = $voices.Item($i).GetDescription()
    if ($desc -like ('*' + $VoiceMatch + '*')) { $picked = $voices.Item($i); break }
  }
  if ($null -eq $picked) { [Console]::Error.WriteLine('no voice matching: ' + $VoiceMatch); exit 3 }
  $voice.Voice = $picked
  $voice.Rate = $Rate
  $voice.Volume = $Volume

  $stream = New-Object -ComObject SAPI.SpFileStream
  $fmt = New-Object -ComObject SAPI.SpAudioFormat
  $fmt.Type = $SampleFormat
  $stream.Format = $fmt
  $stream.Open($OutFile, 3, $true)
  $voice.AudioOutputStream = $stream
  $null = $voice.Speak($text, 0)
  $null = $voice.WaitUntilDone($TimeoutMs)
  $stream.Close()
} catch {
  [Console]::Error.WriteLine('tts failed: ' + $_.Exception.Message)
  exit 4
}

if (-not (Test-Path -LiteralPath $OutFile)) { [Console]::Error.WriteLine('no output file'); exit 5 }
$len = (Get-Item -LiteralPath $OutFile).Length
if ($len -le 44) { [Console]::Error.WriteLine('empty audio: ' + $len + ' bytes'); exit 6 }
[Console]::Out.WriteLine('ok bytes=' + $len)
exit 0
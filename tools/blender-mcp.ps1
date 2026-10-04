# 与运行中的 BlenderMCP 桥通信（localhost:9876，JSON 行协议）
# 用法： pwsh -File tools\blender-mcp.ps1 -Command get_scene_info
#        pwsh -File tools\blender-mcp.ps1 -Command execute_code -Code 'print(bpy.app.version_string)'
param(
    [Parameter(Mandatory = $true)][string]$Command,
    [string]$Code,
    [int]$Port = 9876
)

$ErrorActionPreference = 'Stop'
$client = New-Object System.Net.Sockets.TcpClient
$client.Connect('127.0.0.1', $Port)
$client.ReceiveTimeout = 600000
$stream = $client.GetStream()

$payload = @{ type = $Command }
if ($Code) { $payload.params = @{ code = $Code } }
$json = ($payload | ConvertTo-Json -Depth 6 -Compress)
$bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
$stream.Write($bytes, 0, $bytes.Length)
$stream.Flush()

$buffer = New-Object byte[] 65536
$builder = New-Object System.Text.StringBuilder
do {
    $read = $stream.Read($buffer, 0, $buffer.Length)
    if ($read -le 0) { break }
    [void]$builder.Append([System.Text.Encoding]::UTF8.GetString($buffer, 0, $read))
    $text = $builder.ToString()
    $complete = $false
    try { $null = $text | ConvertFrom-Json; $complete = $true } catch { }
} while (-not $complete)

$client.Close()
$text

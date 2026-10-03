param(
  [Parameter(Mandatory=$true)][string]$In,
  [Parameter(Mandatory=$true)][string]$Out,
  [int]$Height = 270
)
# 比邻AI · 截图裁图（只留 3D 舞台区域再比哈希）
# 为什么要裁：捏脸页整屏截图包含滑杆数字，UI 一动哈希就变，
# 用它判断"模型到底动没动"会得出假阳性；只比预览区像素才说明问题。
Add-Type -AssemblyName System.Drawing
$src = [System.Drawing.Image]::FromFile((Resolve-Path $In))
try {
  $h = [Math]::Min($Height, $src.Height)
  $dst = New-Object System.Drawing.Bitmap($src.Width, $h)
  $g = [System.Drawing.Graphics]::FromImage($dst)
  $g.DrawImage($src, (New-Object System.Drawing.Rectangle(0,0,$src.Width,$h)), (New-Object System.Drawing.Rectangle(0,0,$src.Width,$h)), [System.Drawing.GraphicsUnit]::Pixel)
  $g.Dispose()
  $dst.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
  $dst.Dispose()
  $hash = (Get-FileHash $Out).Hash.Substring(0,12)
  Write-Output "CROP $Out ${hash}"
} finally { $src.Dispose() }
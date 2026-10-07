param(
  [Parameter(Mandatory=$true)][string]$Image,
  [Parameter(Mandatory=$true)][double]$CenterZ,
  [Parameter(Mandatory=$true)][double]$OrthoScale,
  [double]$SearchTopRatio = 0.30,
  [double]$SearchBottomRatio = 0.62,
  [int]$DarkThreshold = 110
)
# 比邻AI · 从"正视图渲染"里找眼窝（暗斑）并反投影成世界坐标
# 为什么要这样：头高比例法会把眼睛算高（原始网格头顶含头发），
# 必须用几何证据定位：正交正视图里眼窝是暗斑，按已知相机参数可反投影回世界坐标。
Add-Type -AssemblyName System.Drawing
$img = [System.Drawing.Bitmap]::FromFile((Resolve-Path $Image))
try {
  $W = $img.Width; $H = $img.Height
  $y0 = [int]($H * $SearchTopRatio); $y1 = [int]($H * $SearchBottomRatio)
  $leftX = @(); $leftY = @(); $rightX = @(); $rightY = @()
  for ($py = $y0; $py -lt $y1; $py++) {
    for ($px = 0; $px -lt $W; $px++) {
      $c = $img.GetPixel($px, $py)
      $lum = 0.299 * $c.R + 0.587 * $c.G + 0.114 * $c.B
      if ($lum -lt $DarkThreshold) {
        if ($px -lt $W / 2) { $leftX += $px; $leftY += $py } else { $rightX += $px; $rightY += $py }
      }
    }
  }
  function Stats($xs, $ys) {
    if ($xs.Count -eq 0) { return $null }
    return @{ n = $xs.Count; cx = ($xs | Measure-Object -Average).Average; cy = ($ys | Measure-Object -Average).Average }
  }
  $l = Stats $leftX $leftY; $r = Stats $rightX $rightY
  function ToWorld($px, $py) {
    $wx = ($px / $W - 0.5) * $OrthoScale
    $wz = $CenterZ + (0.5 - $py / $H) * $OrthoScale
    return @([math]::Round($wx,4), [math]::Round($wz,4))
  }
  "  搜索带: y=$y0..$y1  (阈值 lum<$DarkThreshold)"
  if ($l) { $w = ToWorld $l.cx $l.cy; "  左眼暗斑: $($l.n) px  像素($([math]::Round($l.cx,1)),$([math]::Round($l.cy,1)))  → 世界 X=$($w[0]) Z=$($w[1])" }
  if ($r) { $w = ToWorld $r.cx $r.cy; "  右眼暗斑: $($r.n) px  像素($([math]::Round($r.cx,1)),$([math]::Round($r.cy,1)))  → 世界 X=$($w[0]) Z=$($w[1])" }
} finally { $img.Dispose() }
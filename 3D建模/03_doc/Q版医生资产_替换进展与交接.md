# 换成 Q 版「男医 / 女医」资产 · 进展与交接（2026-10-05）

> 用户指示：用 `3D建模/男医`、`3D建模/女医` 两个模型**同时替换**男女形象。
> 策略不变：保留端侧、**去捏脸**，只做「**唇形同步 + 招手互动**」。

---

## 1. 两个新资产的事实（实测）

| 项 | 男医 | 女医 |
|---|---|---|
| 源文件 | `男医\Q版男医\29032c6e….obj` | `女医\Q版女医\ba9ff1c7….obj` |
| 规模 | **749,934 顶点 / 1,499,888 面** | **749,956 顶点 / 1,499,920 面** |
| 贴图 | 4 张 4096² PBR（与之前同套命名） | 同 |
| 轴向 | **Y-up** → 已 +90° 转 Z-up | 同 |
| 身高 | 1.1210m | 1.1224m |
| 实测 landmark | 鼻尖 z=**1.0135**、嘴 z=**0.9625** | 鼻尖 z=**1.0071**、嘴 z=**0.9689** |
| 手骨位置 | 腕 x=**0.385** | 腕 x=**0.381** |
| 风格 | Q 版男医（白大褂 + 听诊器） | Q 版女医 |

**两个模型的"人物设定"**：Q 版医生形象（诊所场景），与之前的"小男孩玩偶"是两套。

---

## 2. 已完成（两个模型都跑完了整条管线）

| 步骤 | 男医 | 女医 |
|---|---|---|
| 转轴 | `source_male3_zup.blend` | `source_female3_zup.blend` |
| 骨架（41 骨，含左右手臂链） | `rig_male3_step1.blend` | `rig_female3_step1.blend` |
| 减面 | `male3_60k.blend`（59,000 tri） | `female3_60k.blend`（58,998 tri） |
| 权重 | `male3_w.blend` | `female3_w.blend` |
| 口型/表情形态键（23） | `male3_morphs.blend` | `female3_morphs.blend` |
| **招手动画** | `male3_wave.blend`（78 帧/2.6s） | `female3_wave.blend` |
| 导出（带动画） | **14.5MB**，`wave` 123 通道 | **14.4MB** |
| 已装进端侧 | `uni-app/static/avatar/BilinAI_MaleFaceRig_60k_edit.glb` | `..._FemaleFaceRig_60k_edit.glb` |

备份：`_rig_work/backup-doctor-20261005-173455/`

**H5 实测已加载成功**：`bones:41 / meshes:1 / morphSlots:23 / triangles:58998 / warnings:0`。
用 node 直读 GLB 也确认：`animations: wave (123 channels)`、`morphTargets: 23`、`skins joints: 41`。

---

## 3. 招手动画的关键实测（工具：`tools/blender-wave-anim.py`）

**轴必须实测**（资产转过轴，局部轴不直观）：

| 探测项 | 男医 | 女医 |
|---|---|---|
| 抬臂轴（世界 Δz 最大） | `upperarm.R` **X 轴** +1（+99.1mm/40°） | 同（+98.2mm） |
| 摆动轴（世界 Δx 最大） | `upperarm.R` **Z 轴** −1（73.3mm/45°） | 同（108.5mm） |
| **自动验收结果** | 手部抬起 **180.4mm**、左右摆动 **68.5mm** | 抬起 ~133mm、摆动 ~30mm |

**两个踩过的坑**：
1. 第一版把"摆动"放在 `forearm` 上 → 手部左右只有 **1.5mm**，动画看起来"只抬了下手"。
   实测 `forearm`/`hand` 任一轴的横向都只有 1~4mm（圆团手 + 短前臂），**指望不上**；
   横向摆动必须用 `upperarm` 的 Z 轴。
2. "按 Δx 选摆动轴"会**选回抬臂用的同一根轴**（`upperarm` X 同时产生很大 Δx、Δz），
   两者在同一通道上**相互抵消** → 验收显示"抬起 1.3mm"。
   **修正：摆动只在"除抬臂轴之外"的轴里挑。**

**几何上限（要有预期）**：肩在 z=0.592、手静止在 z=0.485、上臂约 140mm——
**手最多举到接近肩高**（扫 ±90° 网格，最好的组合也只到"肩相对 −15mm"）。
所以这个 Q 版体型的"招手"是**抬臂到肩高 + 前臂弯曲 + 左右摆**，不会有写实角色那种"手举过头顶"。

---

## 4. ✅ 已解决：端侧取景裁切面部

**现象**：捏脸页预览里只能看到头发 + 上半张脸（下半张被切）。

**排查过程（值得记下来，因为走了弯路）**：
1. 先按"头身比自适应/取景盒放大"改了两处 —— **没用**；
2. 给渲染器加了 `stage.debug()`（暴露相机位置/FOV/aspect、`focus` 盒、`root` 位置、
   renderer 尺寸与 dpr），配合 `stats().frame` 看数 —— 发现**相机数学上够用**
   （可见高 0.539 > 取景盒高 0.431，头只该占 36% 高），与"画面上只看到头"矛盾；
3. 于是改成**实测二分**：把 `FIT_MARGIN` 从 1.25 调到 **2.2**（`dist` 1.006 → 1.771），
   重载后**整张脸完整入框** ✅ —— 说明真实的"可见范围"比相机公式小得多，
   最可能的原因是**渲染器内部尺寸/视口与相机 aspect 口径不一致**（`canvas` CSS 391×285、
   缓冲 782×570、`dpr=2`，三者都对得上，但画面等效视野明显更窄）。

**采用的修法（本轮）**：`uni-app/common/face-gl/face-three.js` 的 `FIT_MARGIN = 2.2`，
并在注释里写明原因。同时保留了两处更有普适性的改动：
① `computeFocus()` 用**几何实测头高**（不再只信 head 骨 —— Q 版头发高会让它算小）；
② 取景盒**补成与画布同纵横比**（横画布就补高），从机制上避免这类裁切。

**遗留的小问题**：现在头略偏上、下巴贴近底边；若要更居中，把 `FIT_MARGIN` 再微调
（2.2 → 2.5）或把取景盒中心下移一点点即可。

**留下的诊断口子**：`window.__blFaceStage.debug()` —— 以后再遇到取景/相机问题，
先看它，不要靠猜（这轮的弯路就是猜出来的）。

## 5. 还没做（下一步清单）

1. **取景裁切**（§4）——目前最影响观感的遗留问题；
2. **减骨保留手臂链**：`blender-reduce-bones.py` 现在减到 7 骨（**不含手臂**），
   本方案要保留（建议 root/neck/head/jaw/eye.L/eye.R + 左右各 4 根 ≈ 15 骨）；
2. **交付期件**：`_delivery_baked.glb` 还没用新模型重做（现在两个角色都只有编辑期件是新的）；
3. **契约测试改判**：`tools/test-avatar-v2-glb.mjs` 现在要求 113 个 `shape_*`，
   应改为"口型键（vis_*/expr_*）+ 动画片段存在"；
4. **端侧接线**：捏脸页入口改「此功能正在开发中」提示；`pages/vision` 接播放器 + 播放 `wave`；
5. **材质偏油亮**：端侧 3 盏灯共 5.95 强度，在皮肤上高光过强（可统一调）。

---

## 6. 复跑命令（两个模型同一条链）

```powershell
$b="E:\Blender\blender-5.1.2-windows-x64\blender.exe"; $w="E:\比邻AI\3D建模\_rig_work"
# 以女医为例（男医把 female3→male3、路径换成男医目录）
& $b -b --python tools/blender-env.py --python tools/blender-survey-source.py -- `
     --in "E:\比邻AI\3D建模\女医\Q版女医\ba9ff1c7e2fa59b933be826d97856f52.obj" --out "$w\source_female3.blend"
& $b -b "$w\source_female3.blend" --python tools/blender-env.py --python tools/blender-axis-fix.py -- --out "$w\source_female3_zup.blend"
& $b -b "$w\source_female3_zup.blend" --python tools/blender-env.py --python tools/blender-rig-structural.py -- --out "$w\rig_female3_step1.blend"
& $b -b "$w\rig_female3_step1.blend" --python tools/blender-env.py --python tools/blender-decimate.py -- `
     --out "$w\female3_60k.blend" --target-tris 59000 --no-protect --mouth-z 0.9689 --eye-z 1.0071
& $b -b "$w\female3_60k.blend" --python tools/blender-env.py --python tools/blender-rig-weights.py -- --out "$w\female3_w.blend" --mode analytic --rounds 3 --no-hair-mask
& $b -b "$w\female3_w.blend" --python tools/blender-env.py --python tools/blender-morph-build.py -- --out "$w\female3_morphs.blend" --strain-k 0.30 --jaw-scale 0.60
& $b -b "$w\female3_morphs.blend" --python tools/blender-env.py --python tools/blender-wave-anim.py -- `
     --out "$w\female3_wave.blend" --side R --raise-deg 80 --swing-deg 30 --swing-cycles 3
& $b -b "$w\female3_wave.blend" --python tools/blender-env.py --python tools/blender-export-glb.py -- `
     --out "$w\staging\BilinAI_FemaleFaceRig_60k_edit.glb" --texture-max 1024 --keep-morph-prefix vis_,expr_ --animations
```

**两条必看的判据**：
- morph-build 输出里的 `唇部定位：… → 掩膜命中 N 顶点，嘴半宽 M mm`：**N 不能是 0**；
- wave-anim 输出里的 `验收：手部抬起 X mm，左右摆动 Y mm`：**X>40mm 且 Y>15mm** 才算"招手明显"。

# 捏脸渲染层 · 端侧 3D 舞台（common/face-gl）

> 本目录是**手写代码**，不是 `E:\blender demo` 交付流水线的产物。
> 流水线产物是 `common/face/`（只读，勿手改，再生成会覆盖）。渲染层刻意分开放，
> 免得上游再生成时被冲掉。

## 目录内容

| 文件 | 说明 |
|---|---|
| `assets.js` | 纯数据：资产路径、性别选项、资产 URL 解析。**不 import three.js** |
| `face-three.js` | 端侧 3D 舞台（three.js 封装）：加载 / 构图 / 交互 / 权重写入 |
| `../libs/three/` | three.js 固定副本（`three.module.js` + `GLTFLoader.js` + `BufferGeometryUtils.js`）|

`assets.js` 之所以不引 three.js：App 端**逻辑层**也会 import 它（只为拿性别选项），
不能把 1.2 MB 的 three.js 拖进逻辑层包体。

## 与 `common/face/` 的分工

| 层 | 目录 | 职责 |
|---|---|---|
| 逻辑层 | `common/face/` | 参数 → 权重 → 四通道指令（零依赖、零 I/O、只读产物）|
| 渲染层 | `common/face-gl/` | 把四通道指令写进 three.js 场景、构图、手势交互 |

连接点是逻辑层自带的两个 API，渲染层不重造：

```js
import { adapter, bindThree } from '@/common/face/face-index.js'
const bound = bindThree(gltf.scene)                 // glTF → 适配器认得的 model
adapter.applyToModel(bound, view.cmds)              // 把已算好的指令写进场景
```

## 端侧资产（`uni-app/static/avatar/`）

| 用途 | 女性 | 男性 | 有什么 / 缺什么 |
|---|---|---|---|
| 捏脸（编辑期母本） | `BilinAI_FemaleFaceRig_60k_edit.glb` | `BilinAI_MaleFaceRig_60k_edit.glb` | 113 个 `shape_*`；20 骨（点号制 `eye.L`）；无 `vis_*` |
| 口型 / 表情（运行期） | `BilinAI_FemaleFaceRig_60k_delivery_baked.glb` | `BilinAI_MaleFaceRig_60k_delivery_baked.glb` | 23 个 `vis_*` / `expr_*`；8 骨（下划线制 `eye_L`）；`shape_*` 已烘焙 |

- **捏脸页默认女性**（`DEFAULT_GENDER = 'female'`），顶部可切男性。
  性别只决定加载哪一份 `.glb`，参数表与捏脸结果语义不变。
- 两代骨名都由 `bindThree` 的骨名互补回退（`eye.L` ↔ `eye_L`）兜住，页面无需分支。
- 这 4 份 `.glb` 与 `3D建模/` 下的源文件**逐字节相同**（git 按内容寻址，只存一份）。

## 舞台 API

```js
import { mountFaceStage, unmountFaceStage, getFaceStage } from '@/common/face-gl/face-three.js'

const stage = mountFaceStage(el, { onReady, onError, onStatus })  // 单例，幂等
stage.load('female')            // 加载（同性别重复调用走幂等守卫）
stage.applyWeights(weights)     // 写入 morph 权重（渲染层会按网格补齐重名 target）
stage.applyWeightsThrottled(w)  // 30Hz 节流版（拖动时用）
stage.rotate(dx, dy)            // 手动转向
stage.resize()                  // 画布尺寸变化后调用
stage.stats()                   // 诊断：{ ready, triangles, frame, ... }
stage.dispose()
```

`stats().frame` 是资产验收要的构图诊断：`{ focus, body, center, headY, cutY, dist, aspect, canvas }`。

## 构图：为什么默认不是全身

资产是**全身**模型（高约 1.19），脸只占身高 1/8 左右；按全身包围盒取景时，
三条滑杆全作用在脸上，动了也看不出来。所以：

- 以 rig 的 `head` 骨为基准（实测 `headY ≈ 0.998`），下探 `FOCUS_BELOW_HEAD = 0.45`
  个头高带出脖子与肩，取「头肩」构图。
- 拿不到 `head` 骨时按「身高 1/7.5 是头」推算兜底。
- 水平方向按 `max(size.x, size.z)` 预留转头到 90° 的厚度，避免转过去被裁。

**踩过的坑（改这里前先读）**：

1. `Box3.setFromObject(root)` 对 `SkinnedMesh` 量的是**蒙皮后**包围盒。首帧
   `skeleton.boneMatrices` 还没更新，实测 `size.y = 0.9111`（真值 1.1882）、
   `center.y = 0.4484`（真值 0.5941）→ 模型被放大 1.3 倍并上移，头顶被裁。
   故改用 `restBoxOf()`：直接遍历 `geometry.boundingBox`（顶点 rest pose）× `matrixWorld` 求并集，
   与 glTF accessor 的 min/max 一致。
2. `resize()` **只在画布尺寸真变了**才重新构图，否则每次 resize 都会把滚轮缩放顶掉。
3. 平移用 `root.position.copy(center).negate()`，不要用 `sub()`，否则重复调用会二次平移。

## 双端分叉（改这里前先读）

`<script module lang="renderjs">` **在 H5 端同样会被加载并执行**，`:change:` 绑定也照常派发。
若不拦住，renderjs 会和 `<script setup>` 抢同一个舞台，并抛
`Vue warn: Cannot mutate <script setup> binding "stage" from Options API.` + `TypeError`。

所以 `face.vue` 用**编译期条件**严格分叉：

- `// #ifdef APP-PLUS`：renderjs 生效，由它挂载；`data` 字段名用 `gl` 而非 `stage`
  （与 `<script setup>` 暴露的 `stage` 同名会被 Vue 拦下）。
- `// #ifndef APP-PLUS`：H5 端保留**同名空方法** `bootStage/onBoot/onGender/onPayload`，
  接住 `:change:` 派发（方法不能缺，缺了报找不到方法）；舞台由 `<script setup>` 独占。
- 两端调的是**同一个渲染器**，不存在两份实现。

## 红线

- 页面文案统一取 `UI_COPY`（`common/face/face-index.js`），**禁止页面自写**。
- `aiBadge` / `aiBadgeDetail` 常驻、不可关闭。
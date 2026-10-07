# 资产体积分析与"是否放宽 8MB 预算"的论证（2026-10-05）

> 起因：Q 版医生两个模型做出来后，四个 `.glb` 都在 **14.4~14.5MB**，而
> `比邻AI_数字人资产交付规范.md` §5 写 `.glb ≤ 8MB（Draco 压缩后）`。
> 用户提出：**能否放宽 §5 的预算、调整规划，而不是继续减面**。

---

## 1. 结论（先给答案）

> **📌 后续补充（2026-10-05，本文之后）**：本次讨论暴露出一个更大的问题——
> **那 8MB 到底是不是硬约束？** 查证结论是：**不是**。它只是我们自定的首屏加载预算，
> 无任何平台强制，且**只约束"首屏必须加载的件"**。
> 这条性质已写进契约：`比邻AI_数字人资产交付规范.md` **§5.1~§5.3**（含"超标了怎么办"的三步流程）。
> **下次遇到体积问题，请先看 §5.3**：第一步是分辨"首屏件还是按需件"，
> **不要一上来就减面/降贴图** —— 本文当初就是在没有这条规则的情况下，
> 把"1K 还是 2K 贴图"反复试了一轮。

**不需要放宽规范，也不需要减面。** 规范里那行 8MB 的**前提就是"Draco 压缩后"**，
而我们之前导出时 **Draco 是关的**。打开后：

| 配置 | 体积 | 判定 |
|---|---|---|
| 1K 贴图 + **未压缩**（之前交付的四个件） | **14.5MB** | ❌ 超 8MB |
| **1K 贴图 + Draco** | **6.4MB** | ✅ 合规（规范 §5 贴图预算正是 1K、压缩正是 Draco 6 级） |
| 2K 贴图 + Draco（规范"上限"档） | 14.6MB | ❌ 超 |
| 4K 贴图 + Draco | 42.2MB | ❌ 大幅超 |

**瓶颈是贴图，不是面数**：Draco 把几何从 9.5MB 压到约 **2.9MB**；
剩下的差异全在贴图（1K 与 2K 差约 8MB）。

---

## 2. 体积构成（实测，工具 `_rig_work/_glb_view_size.mjs`）

男医 edit 件 14.5MB 的实际 bufferView 占用：

| 项 | 大小 | 说明 |
|---|---|---|
| `attrs: WEIGHTS_0` | **2.70MB** | 导出器写成 **4×float32**（29,490 顶点） |
| `attrs: POSITION` | 2.03MB | float32 VEC3 |
| `attrs: NORMAL` | 2.03MB | float32 VEC3 |
| `attrs: TEXCOORD_0` | 1.35MB | float32 VEC2 |
| `attrs: JOINTS_0` | 0.68MB | uint16 VEC4（padding） |
| `indices` | 0.68MB | uint32 |
| 贴图（3 张，含 ORM 合并） | 3.55MB | 1024² PNG |
| morph 目标 | **≈0** | **走稀疏访问器**，只存位移了的顶点（23 个目标都是稀疏） |
| 未引用 bufferView | 1.47MB | 疑为逆绑定矩阵等 |

**两个反直觉的实测结论**：
1. **morph 目标不占体积** —— 之前担心 23 个 morph 会撑大文件，实测**几乎为零**，
   因为 Blender 用**稀疏访问器**（只存动了的顶点）。
   （注：`_glb_attr_size.mjs` 按 accessor 逻辑尺寸算会给 46MB 的假象，**要用 bufferView 实际占用**。）
2. **Draco 对 morph 大量模型收益有限** —— 第一版"只开 Draco 不缩放贴图"的测试得到 **42MB**，
   一度以为"开 Draco 反而暴涨"；实际是那个临时脚本**没走贴图缩放流程**、用了 4096 原图。
   走完整流程后：**14.5 → 6.4MB**。

---

## 3. ⚠️ 采用 Draco 的代价：端侧要加解码器

仓库的 three 是**本地引入**（`uni-app/libs/three/three.module.js` + `GLTFLoader.js`），
**目前没有 Draco 解码器**，而规范 §6 对压缩那行的原话是：
「Draco 级别 6（**先在端上实测兼容性**）」——即规范本身就要求先验端侧。

采用 Draco 需要补两件（都能放本地、无 CDN 依赖）：
- `DRACOLoader.js`（three 官方 examples 里的加载器）
- Draco 解码器（`draco_decoder.wasm` + `draco_wasm_wrapper.js`，约 **250KB** 量级）

**验证过的可放心之处**（对 6.4MB 中间件直读 JSON 确认）：
- `KHR_draco_mesh_compression` 参与压缩的是 `POSITION/NORMAL/TEXCOORD_0/JOINTS_0/WEIGHTS_0`；
- **morph 目标不在 Draco 内**（仍是常规稀疏访问器）→ 不受 Draco 支持范围限制；
- **23 个 morph 名字齐全**（存在 `mesh.extras.targetNames`，与未压缩件一字不差）；
- `animations: wave(42 通道)`、`skins joints: 14` 都完好。

---

## 4. 如果要"放宽规范"，该怎么放宽（备选，本轮未采用）

用户的直觉是对的一半：**几何确实没超**，这段瓶颈来自我此前为修复**眼球细节**而放宽的
60k 面预算与 1024 贴图的取舍。若坚持**不带解码器、不加端侧复杂度**，可以按下面的口径改规范：

| 项 | 现规范 | 建议放宽口径 | 依据 |
|---|---|---|---|
| `.glb`（未压缩） | 未列 | **≤16MB** | 本轮四个件 14.4~14.5MB 的实测值 + 余量 |
| 贴图 | 1K / 上限 2K | 保持 | 加大贴图是超预算的主因，不该放宽 |
| 三角面 | ≤45k / 上限 60k | 保持 | 实测 59k 在限内 |
| 压缩 | Draco 6 级 | 「Draco 可选；未压缩件按 16MB 判」 | 两条路都能走 |

**但这个放宽的代价是数据传输量**：端侧首屏要拉 14.5MB（弱网/移动网络下明显更慢），
而 6.4MB 那条路能让**首屏加载时间减半以上**。所以除非明确不想引入解码器，
否则**不建议放宽**。

---

## 5. 本轮的实际动作

- `tools/blender-export-glb.py` 新增 **`--draco`**（默认关，保持历史行为）+ `--draco-level`；
- 用 **1K 贴图 + Draco** 重新导出男/女两个交付件（各 **6.4MB**），四个件全部满足规范 §5。

**下一步（待定）**：是否引入 Draco 解码器。
- 若引入：把 `DRACOLoader` 与解码器放进 `uni-app/libs/three/`，在 `face-three.js` 里挂上，
  并按规范 §6 的要求**在 H5 实测兼容性**（含形态键与动画一起动）。
- 若不引入：按 §4 的口径改规范，交付未压缩的 14.5MB 件。


---

## 6. ✅ 已按方案 A 落地（2026-10-05）

**决定**：引入 Draco 解码器，交付 **1K 贴图 + Draco** 的 6.4MB 件 —— 守规范、不减面、不牺牲动画。

### 6.1 端侧接入（本地化，无 CDN 依赖）

| 文件 | 位置 | 大小 |
|---|---|---|
| `DRACOLoader.js` | `uni-app/libs/three/`（与 GLTFLoader 同级） | 13KB |
| `draco_wasm_wrapper.js` | **`uni-app/static/draco/`** | 57KB |
| `draco_decoder.wasm` | **`uni-app/static/draco/`** | 279KB |

两点取舍（都有理由）：
1. **解码器放 `static/` 而不是 `libs/`** —— uni-app 只保证 `static/` 目录打包时**全量拷贝**，
   `libs/` 下的 `.wasm` 有被漏掉的风险；`static/` 两个端都能直接按 URL 取到。
2. **只用 WASM 解码**（`setDecoderConfig({ type: 'wasm' })`），不带 JS 回退版
   —— 省掉 700KB 的 `draco_decoder.js`（编码器 907KB 也一并清掉）。

`DRACOLoader.js` 的 import 原是 bare specifier `'three'`（three 官方 examples 的写法），
本仓库没有 importmap，已改为相对路径 `'./three.module.js'`。

### 6.2 接线位置

`uni-app/common/face-gl/face-three.js`：
```js
const dracoLoader = new DRACOLoader()
dracoLoader.setDecoderPath(resolveAssetUrl('static/draco/') + '/')
dracoLoader.setDecoderConfig({ type: 'wasm' })
const loader = new GLTFLoader()
loader.setDRACOLoader(dracoLoader)
```
解码器路径复用 `assets.js` 里已有的 `resolveAssetUrl`（H5 用站点根、App 用相对路径）。

### 6.3 端侧兼容性实测（规范 §6 要求"先在端上实测兼容性"）

CDP 的浏览器窗口当时状态异常，于是**绕开 HBuilderX 的 GUI**：
起一个无头 Edge（`--remote-debugging-port=9600`）跑自包含测试页，
用**项目自己的 three r160 + DRACOLoader** 真加载 Draco 件。结果：

| 资产 | 解码耗时 | 三角面 | morph | 动画 | 骨数 |
|---|---|---|---|---|---|
| 男医 delivery | 124~138ms | 59,000 | 23（可驱动） | `wave` 42 通道 | 14 |
| 女医 delivery | 116~119ms | 58,998 | 23（可驱动） | `wave` 42 通道 | 14 |
| 女医 edit | 119ms | 58,998 | 23（可驱动） | `wave` 123 通道 | 41 |

**`morphDriven: 23`** 这一项是关键 —— 它不只检查名字在不在，而是**把形态键下标真正推了一下**
确认 morph 能驱动（Draco 常见坑就是"几何解出来了但 morph 失效"）。
结论：**Draco 与形态键、动画、蒙皮三者共存正常**。

> 这轮临时测试页已删除；验证手法（无头 Edge + 自包含页 + `hx-cdp`）记在此处备用。

### 6.4 四个件的最终状态

| 资产 | 体积 | 判定 |
|---|---|---|
| 男医 edit / delivery | 6.4MB / 6.4MB | ✅ 规范 §5 |
| 女医 edit / delivery | 6.3MB / 6.3MB | ✅ 规范 §5 |

`npm run test:face` 20/20、`npm test` 全绿。

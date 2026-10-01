# 捏脸模块 · uni-app 接入包（common/face）

> 来源：`E:\blender demo` 交付流水线。本目录是**只读产物**，请勿手改；
> 重新生成见文末「再生成」。

## 目录内容

| 文件 | 说明 | 字节 |
|---|---|---|
| `face-index.js` | **唯一入口**。页面只 import 这个文件 | 见文件 |
| `parameters-table.js` | 参数表（102 条：morph 63 / material 27 / bone 6 / asset 6） | 27,935 |
| `shape-namespace-map.js` | 形态键命名空间（63 参数 → 113 个 `shape_*`） | 22,866 |
| `face-params.js` | 参数 → 权重（软夹取 / 年龄联动 / 等强系数 / 不得为负） | 8,412 |
| `face-preset.js` | 预设序列化 / 分享码 / 面容柜（12 槽） | 26,350 |
| `care-trim.js` | 康养裁剪（保留 79 / 弱化 20 / 不做 3 / 增强 15） | 12,517 |
| `face-adapter.js` | 四通道指令 + 30Hz 节流 + three.js 薄绑定 | 17,778 |

**零依赖、零 I/O**：不读文件、不写 storage、不发网络、不起定时器。
持久化由页面负责（`uni.setStorageSync` 等），因此本层可单测、可整包复用。

## 快速接入

```js
import {
  SLIDERS, defaultValues, computeView, randomValues,
  buildSave, loadSave, createCabinet,
  UI_COPY, createThrottle,
} from '@/common/face/face-index.js'

const values = reactive(defaultValues())      // { face_width: 0, eye_size: 0, age_overall: 0 }
const view = computed(() => computeView(values))
// view.value.drivers  → 给 CSS 预览的净驱动量（-1~1 / 0~1）
// view.value.weights  → 形态键权重（可直接喂 glTF morphTargetInfluences）
// view.value.cmds     → 四通道指令（morph / bone / material / asset）
// view.value.share    → 分享码（n=43 时 120 字符，未超 §8.2 上限）
```

### 滑杆

`SLIDERS` 已是「开箱可用」的元数据，字段：

| 字段 | 含义 |
|---|---|
| `key` / `name` | 参数键 / 中文名（脸宽 / 眼睛大小 / 年龄感） |
| `uMin` / `uMax` | UI 整数区间（双向 `-100~100`，单向 `0~100`） |
| `step` | 步长，恒为 1 |
| `defU` | 默认 UI 值 |
| `paramMin` / `paramMax` | 参数域区间（送引擎用） |
| `bidirectional` | 是否双向（决定滑杆是否画中线） |
| `targets` | 该滑杆驱动的 `shape_*` 目标 |
| `trim` | 康养裁剪档位（保留 / 弱化 / 不做） |

```html
<bl-slider
  v-for="p in SLIDERS" :key="p.key"
  :name="p.name" :value="values[p.key]"
  :min="p.uMin" :max="p.uMax" :step="p.step"
  @update:value="values[p.key] = $event"
/>
```

> ⚠️ 双向参数（`uMin = -100`）**必须**把 `:min` 透传给 `bl-slider`，
> 否则组件默认 `0~100` 会把「变窄」一半的行程吃掉。

### 开放更多滑杆

`SLIDER_KEYS` 目前只放 3 条（最小闭环：A 区脸型 / C 区眼 / G 区年龄）。
参数表里另 99 条已全部可用，只需扩白名单，逻辑层不用改：

```js
sliderMeta(['face_width', 'jaw_width', 'nose_tip_size'])  // 临时
// 或长期：改 face-index.js 的 SLIDER_KEYS 后重新生成
```

## 红线文案（规格书 §7.4）

页面**禁止**自己写一份，必须引用：

| 键 | 文案 | 展示要求 |
|---|---|---|
| `aiBadge` | 本形象为 AI 数字人 | 常驻，不可关闭 |
| `aiBadgeDetail` | 基于本人授权素材生成，不是真人实时画面 | 常驻，不可关闭 |
| `saveNotice` | 形象仅用于陪伴对话，不会用于其他用途 | 保存成功后展示 |
| `consentRequired` | 需先完成肖像授权后才能保存形象 | 未授权时阻断保存 |

## 保存与还原

```js
// 保存
const { params, preset, share } = buildSave(values, { name: '日常 · 妈妈' })
uni.setStorageSync('bl_face_active', JSON.stringify(preset))

// 还原（预设对象或分享码都吃）
const r = loadSave(uni.getStorageSync('bl_face_active'))
if (r.ok) Object.assign(values, r.values)

// 多套面容（上限 12 槽）
const cab = createCabinet({ json: uni.getStorageSync('bl_face_cabinet') || undefined })
cab.addSlot(paramsOf(values), { name: '出门妆' })
uni.setStorageSync('bl_face_cabinet', JSON.stringify(cab.toJSON()))
```

面容柜带校验位：内容被改动后 `createCabinet({ json })` 会抛错，不会静默用脏数据。

## 接 3D 渲染器（three.js）

CSS 预览只是降级态；真 3D 用 `bindThree` 把 glTF 场景包成适配器认得的 `model`：

```js
import {
  adapter, bindThree, createThrottle, paramsOf,
  table, preset, fp,
} from '@/common/face/face-index.js'

// 1) 把 three.js 场景包成适配器认得的 model（按 name 取骨/材质，不按 index）
const bound = bindThree(gltf.scene, {
  assetRegistry: { hair_slot: [...], brow_style: [...], lash_mesh: [...], bangs_slot: [...] },
})

// 2) 拖动回调做 30Hz 节流（规格书 §7.3），超出频率的调用会被直接丢弃
const throttle = createThrottle(
  (params) => adapter.applyParams(bound, table, preset, fp, params),
  { hz: 30 },
)

// 3) 滑杆拖动 / 松手
throttle.call(paramsOf(values))   // → { applied: true,  dropped: false, result: {...} }
                                  // → { applied: false, dropped: true }（被节流丢弃）
```

两个 API 的分工别记混：

| API | 作用 |
|---|---|
| `bindThree(root, opt)` | three.js `Object3D` → 适配器 model（只读视图，无写方法） |
| `adapter.applyToModel(model, cmds)` | 把**已经算好的**四通道指令写进 model |
| `adapter.applyParams(model, table, preset, fp, params)` | 参数一步到位：算指令 + 写进 model |
| `createThrottle(fn, { hz })` | 返回 `{ hz, minGap, call(arg), stats(), reset() }`，**用 `.call()` 触发** |

## 交付期骨骼口径（耳骨已保留）

- **耳部骨通道**：交付 glb 实测 **8 根骨骼**（`neck` / `head` / `jaw` / `tongue` / `eye_L` /
  `eye_R` / `ear_L` / `ear_R`），`ear` 命中 2。`ear_size` / `ear_protrusion` / `ear_height`
  三条参数**在交付件上可直接写入**（第 11 阶段恢复耳骨，第 6 阶段减骨曾把它们并入 `head`）。
  若某版资产缺 `ear_*`，适配器仍逐骨名告警而非静默失败（见交付说明 §25）。
- **两代骨名都认**：交付件骨名 `eye_L` / `ear_L`，编辑期母本骨名 `eye.L` / `ear.L`；
  适配器 `getBone()` 先按原名查、再按 `_L`/`_R` 与 `.L`/`.R` 互补回退（`expandBoneAliases()`），
  两代资产都能把 6 条骨通道参数落到位。若两种命名都没有该骨，仍逐骨名告警而非静默失败。
- `shape_*` 形态键在交付 glb 中为 0（已烘焙），当前 23 个 target 全是 `vis_*` / `expr_*`。
  权重表照常输出，接自带动画骨骼的资产即可生效。

 端侧资产选择（捏脸 / 口型两件套）

`uni-app/static/` 放了两件**互补**的女生资产，按用途取用（R45 投递）：

| 用途 | 文件 | 字节 | 有什么 / 缺什么 |
|---|---|---|---|
| 口型 / 表情（运行期） | `BilinAI_FaceRig_60k_delivery_baked.glb` | 7,582,548 | 23 个 `vis_*` / `expr_*`；`shape_*` = 0（捏脸结果已烘焙进顶点） |
| 捏脸（编辑期） | `BilinAI_FaceRig_60k_edit.glb` | 10,073,348 | 113 个 `shape_*`（带 `targetNames`）；`vis_*` / `expr_*` = 0；20 骨（点号制 `eye.L` / `ear.L`） |

- 捏脸页默认形象 = **女性**，加载 `BilinAI_FaceRig_60k_edit.glb`；20 骨命名由 `expandBoneAliases()`
  回退到交付件口径，**不需要改页面代码**。
- 两件**不能互相替代**：要在同一页面同时做「捏脸 + 口型」，需要一个把 113 个 `shape_*` 与
  23 个 `vis_*` / `expr_*` 合并的资产（本轮未做，已列为待办）。
- 两件内嵌贴图均为 1K（R45 由 2048 / 4096 降到 1024，`eye_iris` 256）；端侧纹理显存约
  67 MB → 17 MB，交付 `.glb` 由 14.41 MB 降到 7.23 MB（规格书 §5 上限 8 MB）。


## 再生成

```powershell
# 1) 同步逻辑层 4 个模块 + 参数表/命名空间
node _mk_json_esm.mjs
# 2) 自检（153 断言）
node _uniapp_smoke.mjs
```

再生成后请重跑 `client/` 下的 4 个测试（`1822 + 584 + 272 + 534`），确认逻辑层未被改动。
# 比邻AI 数字人资产交付规范

> 版本：V1.0 ｜ 日期：2026-09-24
> 用途：Blender 建模/绑定完成后按本规范交付，保证能**直接接入** uni-app 端侧渲染（renderjs + Three.js）与 3D 捏脸系统
> 配套：《比邻AI_项目设计方案.md》§3.6 捏脸系统 / §4.4 资产管线

> **交付前请逐条勾选第 7 章验收清单。** 不符合的资产无法接入，只能返工——而返工意味着重新绑定。

---

## 1. 交付物清单

| # | 交付物 | 格式 | 说明 |
|---|---|---|---|
| 1 | 数字人模型 | `.glb`（glTF 2.0 二进制） | 含骨架 + morph targets + 材质贴图 |
| 2 | Blender 母版 | `.blend` | 与导出的 glb 一致，供后续修改 |
| 3 | 贴图 | `albedo` / `normal` / `roughness` `.png` | 打包进 glb，同时给原始文件 |
| 4 | 命名对照表 | `.csv` 或 `.md` | 骨骼名 / morph 名 / 材质名 → 含义 |
| 5 | 预览图 | `.png` | 正面 / 45° / 侧面，用于入库审核 |
| 6 | 参数测试记录 | `.md` | 捏脸参数拉到极值时的截图（验证不破面） |

---

## 2. 尺度与坐标系（最容易错，先对齐）

| 项 | 要求 | 原因 |
|---|---|---|
| 单位 | 米（Blender 场景单位 = 1m） | 端侧渲染按米制 |
| 人物身高 | 1.60–1.75m；半身像则头高 0.22–0.25m | 与相机预设匹配 |
| 朝向 | Blender 中面朝 **-Y**，导出勾选 **+Y Up** | glTF 约定为 Y 上、-Z 前；Blender 导出会自动换算 |
| 原点 | 双脚中点（半身像放颈部中心） | 统一挂载与旋转 |
| 变换 | 导出前**应用全部变换**，Scale/Rotation 归零 | 否则端侧缩放错乱 |
| 比例 | X/Y/Z scale 均为 1.0 | 体型靠骨骼与 morph，不靠缩放 |

---

## 3. 骨架规范

| 项 | 要求 |
|---|---|
| 根骨 | 单一根骨骼，命名 `root` |
| 头部链 | `head` / `neck` / `jaw` / `eye.L` / `eye.R` **必须存在**（捏脸与口型都要用） |
| 骨骼总数 | ≤ 70（移动端性能预算） |
| 命名 | 仅英文 + `.`（如 `eye.L`），**禁止中文与空格** |
| 蒙皮 | 面部权重刷好，不得有硬边穿插 |
| 导出 | 蒙皮网格**不要** Apply Modifiers（勾了会丢绑定） |

---

## 4. Morph Targets（最关键的一节）

### 4.1 三个命名空间（必须严格遵守）

| 前缀 | 用途 | 数量 | 举例 |
|---|---|---|---|
| `vis_` | 口型（viseme） | 15–20 | `vis_sil` `vis_aa` `vis_ee` `vis_ii` `vis_oo` `vis_uu` `vis_mbp` `vis_fv` `vis_l` `vis_th` `vis_wq` |
| `exp_` | 表情 | ≥ 6 | `exp_smile` `exp_frown` `exp_surprise` `exp_blink` `exp_eyeclose` `exp_squint` |
| `shape_` | 捏脸 | 113 个 target / 63 个参数 | `shape_face_width_up` `shape_face_width_dn` `shape_jaw_width_up` `shape_eye_size_dn` `shape_nose_tip_size_up` `shape_forehead_wrinkle_up`（完整清单见 §4.3） |

**硬规则**：

- 三类 morph **不得复用同一个 target** —— 复用会导致"捏完脸数字人不会说话"（见设计方案 §3.6 双层架构）
- 每个 morph 只做**单一方向**变形，不要做成双向滑杆（正负方向用两个 target 表示）
- 命名全小写、`_` 分隔，禁止中文与空格
- `shape_` 组 63 个参数展开成 113 个 target：双向参数建 `<key>_up` 与 `<key>_dn` 两个（各管一个方向），单向只建 `<key>_up`；**权重恒 ≥ 0**，负权重一律视为非法
- `ear.L` / `ear.R` 等含点的骨骼名在 glTF 中写作 `eye_L` / `eye_R`（glTF 不允许 `.`）

### 4.2 中文 viseme 覆盖要求

中文用**音素 → viseme 映射（约 15 个口型）**，不是照搬 ARKit 52（那套偏英文与表情）。需覆盖：

- 元音：`a` `o` `e` `i` `u` `ü`
- 辅音口型：`b p m` / `f v` / `d t n l` / `g k h` / `j q x` / `zh ch sh r` / `z c s`

### 4.3 捏脸参数与现有滑杆的对应

端上捏脸页（`pages/face/face.vue`）已改为消费统一的**参数表**
—— `uni-app/common/face/parameters-table.js`，102 条，四通道混编：

| 通道 | 条数 | 端侧落点 |
|---|---|---|
| `morph` | 63 | `shape_*` morph 权重 |
| `material` | 27 | 材质色板 / 标量（改属性，不重建材质） |
| `bone` | 6 | 骨骼 `scale` / `translate` / `rotate` |
| `asset` | 6 | 独立 mesh 槽位（枚举切换）或权重 |

> 命名以参数表 `k` 列为准，端侧**不得出现第二份命名**。
> 旧文档里的 `shape_jaw_width` / `shape_eye_size` / `shape_nose_bridge` /
> `shape_mouth_width` / `shape_wrinkle_*` 都只是临时叫法；正式名为
> `shape_<key>_up` / `shape_<key>_dn`（单向下标 `_up` 可省略，见下表）。

#### 4.3.1 原 8 个滑杆 → 参数表 key

| 原滑杆 | 入口 key | 同组其它 key | 通道 |
|---|---|---|---|
| 脸型 | `face_width` | `face_length` / `cheekbone_height` / `cheekbone_width` / `cheek_fullness` / `temple_width` / `jaw_width` / `jaw_angle` / `chin_length` / `chin_protrusion` / `chin_width` / `chin_cleft` / `forehead_height` / `forehead_width` | morph |
| 眼睛 | `eye_size` | `eye_height` / `eye_width` / `eye_inner_corner` / `eye_outer_corner` / `eye_lid_type` / `eye_tilt` / `eye_aegyo` / `eye_socket_depth` / `pupil_size` / `iris_size` / `eye_spacing` | morph + bone |
| 鼻子 | `nose_tip_size` | `nose_length` / `nose_bridge_height` / `nose_bridge_width` / `nose_bridge_curve` / `nose_tip_upturn` / `nostril_width` / `nostril_height` / `nostril_size` / `nose_root_depth` | morph |
| 嘴巴 | `mouth_width` | `mouth_height` / `lip_upper_thickness` / `lip_lower_thickness` / `lip_shape` / `mouth_corner_up` / `mouth_protrusion` / `philtrum_length` / `philtrum_depth` / `teeth_size` | morph |
| 发型 | `hairstyle` | `bangs` / `hair_color` / `white_hair_ratio` | asset + material |
| 肤色 | `skin_tone` | `skin_texture` / `oiliness` | material |
| 年龄感 | `age_overall` | 皱纹组 + `skin_texture` + `cheek_fullness` + `eye_bag`（在 Blender 侧组合，端上只出一个滑杆） | morph |
| 服饰 | **不在参数表内** | 由造型 / 换装模块处理，与捏脸解耦 | — |

#### 4.3.2 首批开放滑杆（最小闭环 3 条，UI 已接通）

| key | 中文 | UI 区间 | 参数域 | 方向 | 运行时 target |
|---|---|---|---|---|---|
| `face_width` | 脸宽 | `-100~100` | `-1~+1` | 双向 | `shape_face_width_up` / `shape_face_width_dn` |
| `eye_size` | 眼睛大小 | `-100~100` | `-1~+1` | 双向 | `shape_eye_size_up` / `shape_eye_size_dn` |
| `age_overall` | 年龄感 | `0~100` | `0~1` | 单向 | `shape_age_overall_up` |

> `age_overall` 在表内写作 `shape_age_overall`，端上展开为 `shape_age_overall_up`，
> 请在 Blender 侧以**展开后的名字**建键。

#### 4.3.3 骨骼通道（6 条，命名逐字一致）

| key | 骨骼 | 类型 | 区间 | 默认 | 镜像 |
|---|---|---|---|---|---|
| `neck_thickness` | `neck` | scale | 0.85~1.15 | 1.0 | 否 |
| `eye_spacing` | `eye.L` / `eye.R` | translate x | ±3 mm | 0 | 是（左右反号） |
| `ear_size` | `ear.L` / `ear.R` | scale | 0.90~1.10 | 1.0 | 否 |
| `ear_protrusion` | `ear.L` / `ear.R` | rotate y | ±8° | 0 | 是（左右反号） |
| `ear_height` | `ear.L` / `ear.R` | translate z | ±3 mm | 0 | 否（左右同号） |
| `head_scale` | `head` | scale | 0.92~1.08 | 1.0 | 否 |

> 资产里骨骼名是 `eye_L` / `eye_R`（glTF 不允许 `.`），参数表写 `eye.L` / `eye.R`，
> 由适配器 `expandBoneTargets` 负责映射。
>
> **交付期骨骼**：当前 `.glb` 为 8 根骨骼（`neck` / `head` / `jaw` / `tongue` /
> `eye_L` / `eye_R` / `ear_L` / `ear_R`），即**保留 `ear.L` / `ear.R`**，
> 上表三条 ear 参数在交付件上**可直接写入**，骨通道缺口已消除。
> 该口径按《比邻AI_3D捏脸与面部骨骼绑定提示词》验收清单「交付资产 ≤ 8 骨」执行
> （8 骨恰为上界），相对《面部骨骼绑定交付说明》§16「只保留 6 根」属**有意偏离**，
> 理由与数值证据见该说明 §25。

#### 4.3.4 资产槽位（6 条）

| key | 槽位 | 类型 | 档位 |
|---|---|---|---|
| `brow_shape` | `brow_style` | enum | 10 款 |
| `lash_length` | `lash_mesh` | enum | 3 档 |
| `hairstyle` | `hair_slot` | enum | 12 款 |
| `bangs` | `bangs_slot` | enum | 6 款 |
| `beard_type` | `beard_slot` | enum | 本档不做（女性形象） |
| `beard_density` | `beard_density` | weight | 本档不做 |

---

## 5. 面数与贴图预算

| 项 | 预算 | 上限 |
|---|---|---|
| 三角面 | ≤ 45k | 60k |
| 顶点 | ≤ 30k | 40k |
| 贴图 | 1K | 2K |
| 材质数 | 3 | 5 |
| morph target 总数 | ≤ 45 | 60 |
| 导出 `.glb` | ≤ 5MB | 8MB（Draco 压缩后） |

---

## 6. 导出设置（Blender → glTF）

| 选项 | 值 |
|---|---|
| 格式 | glTF Binary (.glb) |
| +Y Up | 勾选 |
| 应用修改器 | **不勾**（蒙皮网格勾了会丢绑定） |
| 应用变换 | 勾选 |
| 材质 | 导出 PBR：BaseColor / Normal / Roughness / Metallic |
| 动画 | 一期不导出（口型运行时驱动）；如含待机动作，单独文件 |
| 压缩 | Draco 级别 6（先在端上实测兼容性） |
| 法线 / 切线 | 勾选（morph 依赖正确切线） |

---

## 7. 交付前验收清单

- [ ] 单位 = 米，身高在 1.60–1.75m，scale 全为 1.0
- [ ] 朝向正确，原点在双脚中点 / 颈部中心
- [ ] 骨骼 ≤ 70，命名全英文，`jaw` / `eye.L` / `eye.R` 存在
- [ ] morph 严格分 `vis_` / `exp_` / `shape_` 三命名空间，**无复用**
- [ ] 中文 viseme 覆盖完整（≥15，含 ü 与全部辅音口型）
- [ ] 捏脸 morph 覆盖参数表 63 条 morph 参数（≥ 20 为底线），首批 3 条滑杆（`face_width` / `eye_size` / `age_overall`）端到端跑通
- [ ] 三角面 ≤ 60k，贴图 ≤ 2K，`.glb` ≤ 8MB
- [ ] **捏脸拉到极值不破面、不穿模**（附截图）
- [ ] **捏脸之后口型仍可辨识**（捏极端嘴型后跑一遍全部 viseme，附截图）
- [ ] `gltf-validator` 校验通过，无 error
- [ ] 在端侧渲染器（renderjs + Three.js）实测：能加载、能动、帧率达标

---

## 8. 常见返工原因（提前避开）

| 现象 | 原因 |
|---|---|
| 端侧模型巨大 / 位置错乱 | 没应用变换，或单位不是米 |
| 数字人张不开嘴 | 捏脸与口型共用了同一个 morph target |
| 嘴一直微张 | viseme 静默基准值没在捏脸后重新归一化 |
| 导出后模型不动 | 勾了 Apply Modifiers，绑定信息丢失 |
| 加载后材质发黑 | 法线贴图方向错误 / 切线缺失 / 用了不支持的材质节点 |
| 捏脸拉到极值破面 | 单个 morph 变形幅度过大，应拆分或限制范围 |

---

## 9. 交付流程

```
你完成 Blender 绑定
   → 按第 6 章导出 .glb
   → 自查第 7 章清单（截图留证）
   → 交付到 E:\比邻AI\uni-app\static\avatar\
   → 我方跑 gltf-validator + 端侧加载实测
   → 通过则入库并接进捏脸页；不通过则退回并附具体失败项
```
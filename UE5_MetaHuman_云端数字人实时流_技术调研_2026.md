# UE5 MetaHuman 用于「云端数字人实时流」调研报告

> 调研时间：2026 年（资料截至 UE 5.7 / MetaHuman 5.7，2025-11-12 随 UE 5.7 发布）
> 原则：每个数字都给来源 URL；查不到的明确标「未找到权威来源」，不臆造。

---

## 1. MetaHuman 的现行形态

### 结论（1–3 行）

MetaHuman Creator 的**网页版（cloud-based web app）已经不再是创建工作流**——从 UE 5.6 起，MetaHuman Creator 变成了 UE 编辑器内的插件/资产编辑器，网页版只保留迁移通道。UE 5.6/5.7 的正式工作流是「UE 内置 MetaHuman Character 资产 + Assembly 装配管线」，Maya / Houdini 是**可选的 DCC 编辑环节**（MetaHuman for Maya / for Houdini 插件），不是替代关系。资产**不能**通过官方管线导出成 GLB/FBX 给 three.js——官方只导出 DNA + 贴图给 Maya/Houdini；但 2025 年 6 月起授权已放宽到「可用于任意 DCC / 游戏引擎（含 Unity、Godot）并商业使用」，所以法律上不再禁止，瓶颈纯在**技术管线**。

### 依据与来源

**1.1 网页版状态：已被 in-editor 取代（UE 5.6 起）**

Epic 官方文档《MetaHuman Workflow Changes》原文（5.7 版）：

> "As of Unreal Engine 5.6, you will no longer use the MetaHuman Creator web application to create and author MetaHuman Characters. New characters are created directly in the Unreal Engine editor using the new MetaHuman Character asset."

同一页还说明：

- 编辑器内的这个资产编辑器**现在就叫 MetaHuman Creator**（名字被复用，容易混淆）
- 老的 UE ≤5.5 角色要通过 Quixel Bridge 的 migrate 迁移成新的 MetaHuman Character 资产
- 新的 Assembly 管线（MetaHuman Assembly）**取代了 Quixel Bridge** 导出 game-ready 资产的职责

来源：<https://dev.epicgames.com/documentation/metahuman/metahuman-workflow-changes?application_version=5.7>

**1.2 UE 5.6 / 5.7 的正式工作流**

| 环节 | 5.6 / 5.7 的做法 | 来源 |
|---|---|---|
| 创建/编辑角色 | UE 编辑器内 **MetaHuman Character 资产**（编辑器名为 MetaHuman Creator） | [Workflow Changes](https://dev.epicgames.com/documentation/metahuman/metahuman-workflow-changes?application_version=5.7) |
| 装配出可用资产 | **Assembly** 工具，4 条管线：UE Cine / UE Optimized / UEFN Export / **DCC Export** | [Assembly](https://dev.epicgames.com/documentation/metahuman/assembly?application_version=5.7) |
| 动画 | **MetaHuman Animator 随 UE 一起发布**（不再需要从 Fab 下载 MetaHuman Plugin）；深度数据解算需额外装 MetaHuman Animator Depth Processing 插件 | [Workflow Changes](https://dev.epicgames.com/documentation/metahuman/metahuman-workflow-changes?application_version=5.7) |
| DCC 编辑（可选） | MetaHuman for Maya / MetaHuman for Houdini（Fab 上免费插件），配合 **Character Assembler** | [Assembly](https://dev.epicgames.com/documentation/metahuman/assembly?application_version=5.7) |
| 多人动捕采集 | **Capture Manager in Live Link Hub** 取代独立 Capture Manager 工具 | [Workflow Changes](https://dev.epicgames.com/documentation/metahuman/metahuman-workflow-changes?application_version=5.7) |

5.7 新增（对云端部署有实际影响）：

- **MetaHuman Creator 插件支持 Linux 和 macOS**（此前只有 Windows）
- MetaHuman for Maya / for Houdini **也支持 Linux**
- **MetaHuman Animator 的 Linux/macOS 支持仍是「planned for a future release」（未发布）**
- MetaHuman Creator 新增 **Python / Blueprint API**，可把绝大多数编辑与装配操作批处理，且能「run them either interactively in the Unreal Editor or on a compute farm for offline processing」

来源：<https://dev.epicgames.com/documentation/metahuman/metahuman-5-7-release-notes?application_version=5.7&lang=en-US>、<https://www.metahuman.com/releases/metahuman-5-7-is-now-available?lang=en-US>

**1.3 能否脱离 UE 单独使用（GLB/FBX 给 three.js）**

**官方导出能力（官方文档口径）：**

DCC Export 管线只导出：

> "Export head DNA, face DNA, and texture files as a zip archive ready to use in a third-party DCC application such as Maya or Houdini."

即官方给第三方的交换格式是 **DNA（Epic 专有格式）+ 贴图**，**不是 GLB**。DNA 需要 Maya/Houdini 侧的 MetaHuman 插件才能解析。

来源：<https://dev.epicgames.com/documentation/metahuman/assembly?application_version=5.7#dcc-export>

5.7 只提到「支持通过 **FBX** 与外部 DCC 做 mesh round-tripping」（指 conform 模板的 UV 空间顶点对应），不是「整角色 FBX 导出」。

来源：<https://dev.epicgames.com/documentation/metahuman/metahuman-5-7-release-notes?application_version=5.7&lang=en-US>

**授权口径（2025-06 起已放宽）：**

2025 年 6 月 MetaHuman 结束 Early Access 时，Epic 修改了授权：

- MetaHuman 工具集**改由标准 Unreal Engine EULA 覆盖**
- **MetaHuman 角色与服装可以在线市场上出售**，也可用于**其他 DCC 应用或游戏引擎（含 Unity、Godot）里制作的商业项目**
- 唯一例外是 AI：「可以使用在『包含人工智能技术的工作流』中，但**不能用于训练或增强 AI 模型本身**」
- 因为 MetaHuman 角色和动画被归类为「**non-engine products（非引擎产品）**」，用在 Unity/Godot 游戏里**不产生 5% 分成**

来源：<https://www.cgchannel.com/2025/06/you-can-now-sell-metahumans-or-use-them-in-unity-or-godot/>

**旧口径已失效（重要）**：2021 年论坛的官方口径是「MetaHuman assets are currently licensed only for use with Unreal Engine」，导出只是为了在 3D 软件里编辑后再带回 UE。**这条对 2025 年 6 月之后的版本已不适用**，不要引用。

来源（历史口径，仅供对照）：<https://forums.unrealengine.com/t/metahuman-to-gltf/226635>

**实操结论：**

- 法律上：可以用在 three.js 项目里（授权允许）
- 技术上：**没有官方 GLB 通路**。社区存在自建管线（如 `metahuman-to-glb`），但属非官方、无 Epic 支持，且 DNA → glTF 会丢掉 RigLogic 高精度解算能力。页面抓取失败，仅给链接不引述细节：<https://github.com/smorchj/metahuman-to-glb>
- Epic 官方从未提供 MetaHuman → glTF 导出器；2021 年起就有 feature request 至今未落地：<https://forums.unrealengine.com/t/metahuman-to-gltf/226635>

---

## 2. 顶配数据量

### 结论（1–3 行）

官方 LOD 规范给出的 LOD0 数字是：**头部 24,000 顶点 / 669 blendshapes / 713 joints**，**身体 30,500 顶点**，共 **8 级 LOD（0–7）**。单角色显存/内存占用官方给了明确量级：**Cinematic 装配 1–2 GB（5.7）/ 2–3 GB（5.5 旧文档），Optimized 装配 < 100 MB**。毛发 Groom 的 VRAM 是**全量常驻、无流式卸载机制**，是多人同屏时的隐性成本大头。

### 依据与来源

**2.1 骨骼 / blendshape / 顶点（官方 LOD 规范表）**

来源：<https://dev.epicgames.com/documentation/metahuman/platform-support-and-lod-specifications-for-metahumans>

| LOD | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| **头部 Vertices** | 24,000 | 12,000 | 6,000 | 2,500 | 1,300 | 560 | 270 | 130 |
| **Blendshapes** | **669** | – | – | – | – | – | – | – |
| **Joints** | **713** | 529 | 397 | 283 | 84 | 70 | 41 | 26 |
| **Skin Influences** | 12 | 12 | 12 | 8 | 8 | 8 | 4 | 4 |
| **Animated Maps** | Yes | Yes | No | No | No | No | No | No |
| **Body Vertices** | 30,500 | 7,600 | 3,350 | 1,507 | – | – | – | – |
| **Body Correctives** | Yes | Yes | No | No | – | – | – | – |
| **Body Skin Influences** | 8 | 8 | 8 | 4 | – | – | – | – |
| **Hair Strands** | 50,000 | 25,000 | – | – | – | – | – | – |
| **Hair Card Vertices** | 30,000 | 15,000 | 10,000 | 3,000 | 1,500 | – | – | – |
| **Hair Mesh Vertices** | – | – | – | – | – | 500 | 250 | 100 |
| **Facial Hair Strands** | 10,000 | 5,000 | – | – | – | – | – | – |
| **Facial Hair Card Vertices** | 15,000 | 7,000 | 3,000 | 1,000 | 500 | – | – | – |

补充官方说明（矫正「骨骼 1000+」的说法）：

- 官方 DNA 文档：**8 级 LOD（0–7）**，「There is only one set of joints operating across all LODs. The reduced joint count when descending LODs is done by exclusion」——**LOD0 的 713 joints 是上限**，没有 1000+ 的官方数字。
- RigLogic 接收「**hundreds of semantically meaningful channels**」（数百个语义化通道，如 inner brow up/down），映射到大量 joint 的变换 + LOD0 的 per-vertex displacement。
- **per-vertex 顶点位移（shape/morph）只在 LOD0 使用**，低 LOD 完全忽略。

「1000+ 骨骼」**未找到权威来源**——官方最高是头部 713 + 身体的 spine/clavicle/arm/neck/head 等约 30 根，合计约 750 量级。

来源：<https://dev.epicgames.com/documentation/en-us/metahuman/metahuman-dna-rig-definition-and-rig-operation>

**2.2 顶点/三角面**

官方只公开**顶点数**（24000 + 30500 = LOD0 头部+身体约 54,500 顶点），**未公开三角面数**。三角面数**未找到权威来源**（可用「约等于顶点数 ×2」粗估，但属推测，不作结论）。

**2.3 材质与 shader 复杂度**

官方口径（Cinematic vs Optimized 差异表）：

| 项 | Cinematic | Optimized (High/Medium/Low) |
|---|---|---|
| 材质与贴图 | 全分辨率贴图；**分离材质覆盖全部用例，灵活性最大** | 压缩贴图省内存；**优化材质、指令更少、贴图烘焙** |
| LOD | 最低 LOD 也优先质量 | LOD 更激进 |
| 动画 | 最高保真混合；**body 与 neck correctives 开启** | 按 LOD 开关 correctives |
| 毛发 | LOD0 全量 **strand-based hair** | 优化 groom 设置 |
| **内存占用** | **平均 1–2 GB（5.7）** | **平均 < 100 MB** |

平台支持上限（官方表）：

| 平台 | 光线追踪 | 毛发 | 最佳 LOD | 最大贴图 |
|---|---|---|---|---|
| PC（Epic/Cinematic 画质） | 是 | **Strands + Cards** | 0 | **8192** |
| PC（Medium 及以下） | 否 | Strands + Cards | 0 | 8192 |
| Mac | 否 | Cards | 0 | 8192 |
| iOS/Android | 否 | Cards | 3 | 2048 |

- 皮肤 SSS：官方未给具体材质指令数。官方 LOD 表里有 **Animated Maps（LOD0/LOD1 = Yes）**，Skin Tool 的 animated maps 以 texture source 形式导出——这是皮肤细节（皱纹等）的主要成本来源之一。**具体 SSS shader 指令数/耗时未找到权威来源**。
- 眼球材质：官方 DNA 文档说明 MetaHuman 含多个 mesh（head + eyes + mouth 等），且 `FACIAL_L_Pupil`/`FACIAL_R_Pupil` 是**唯一会动态改变 scale 分量影响网格的 joint**。具体材质复杂度**未找到权威来源**。

来源：<https://dev.epicgames.com/documentation/metahuman/assembly?application_version=5.7>、<https://dev.epicgames.com/documentation/metahuman/platform-support-and-lod-specifications-for-metahumans>、<https://dev.epicgames.com/documentation/en-us/metahuman/metahuman-dna-rig-definition-and-rig-operation>

**2.4 单角色显存占用（关键数字）**

**官方数字（Cinematic vs Optimized）：**

- UE 5.7 Assembly 文档：**Cinematic = 1–2 GB**；**Optimized = < 100 MB**
- UE 5.5 Optimized MetaHuman 文档（旧）：**Cinematic = 2–3 GB**；**Optimized = < 100 MB**

来源：<https://dev.epicgames.com/documentation/metahuman/assembly?application_version=5.7>、<https://dev.epicgames.com/documentation/metahuman/optimized-metahuman-in-unreal-engine?application_version=5.0-5.5>

**毛发 Groom 的 VRAM 行为（重要坑，官方工程师确认）：**

Epic 论坛有开发者实测：50 个 MetaHuman NPC **全部只用 cards（不用 strand）**，groom 总 VRAM **约 800 MB**（约 400 MB 资产数据 + 400 MB 运行时 Hair buffers，约 5,366 个 buffer entry），跑在 RTX 3070 8GB 上占近 25% 显存预算。

Epic 工程师（Charles）官方回复要点：

- 「**There is no plan for cards to have streaming pool at this time**」——groom cards **没有流式池，全量常驻**
- 当前机制是：不再需要时必须解除引用，靠 GC 回收 groom component + groom asset
- Guides 数据在启用 hair simulation 或 RBF 插值时分配；Root 数据在 binding 方法为 skinning 时分配（用 rigid 则可省）
- 「**There is no existing code dedicated for crowd usage. We are working on this at the moment, but there is no ETA**」

换算：50 角色 ≈ 800 MB → **约 16 MB/角色**（cards-only，仅 groom 部分）。这是 LOD/距离无关的固定成本，做「一屏多人」时必须自己实现 pooling（按距离销毁/创建 groom component），引擎没有原生方案。

来源：<https://forums.unrealengine.com/t/groom-lod-data-remains-fully-resident-in-vram-regardless-of-distance-lod-level/2715458>

**2.5 编辑/制作侧硬件要求（顺带，供自建管线参考）**

| 项 | 要求 |
|---|---|
| MetaHuman Animator / MetaHuman Creator（编辑器内） | CPU/内存：**≥16 物理高性能核 + 32 GB RAM**；GPU：**≥RTX 3070 / RX 6800 XT / Apple M2 Ultra，8 GB VRAM** |
| MetaHuman Creator Assembly | 大贴图或启用 Virtual Textures 时内存**可能超过 32 GB** |
| Strand 渲染 | 需 **SM6** 渲染设置；M1 芯片 Mac **无法渲染 strands** |
| MetaHuman Animator | Windows 上需 **DX12 兼容显卡 + 默认 RHI 设为 DX12** |
| Markerless Motion Capture 插件 | **仅 Windows** |
| Realtime Animation（mono video 或 audio） | **仅 Windows 和 macOS** |

来源：<https://dev.epicgames.com/documentation/en-us/metahuman/metahuman-hardware-requirements-in-unreal-engine>

---

## 3. 面部驱动的输入接口

### 结论（1–3 行）

官方有四条驱动路径：① **Live Link Face**（iPhone/Android 实时，iOS 用 TrueDepth/ARKit；Android 限高通特定芯片）② **MetaHuman Animator 离线解算**（单目视频/深度/立体，需 Windows）③ **官方 Audio Driven Animation**（音频→口型，有离线与 realtime 两种解算器）④ **ARKit Face / ARKit 52 blendshape 通道**（`Use ARKit Face` 开关）。**硬约束：MetaHuman Animator 不支持 Linux**，「realtime animation from mono video or audio」也**只支持 Windows/macOS**——Linux 无头服务器跑不了官方的实时面部驱动。MetaHuman Animator **不再必须 iPhone 深度相机**（5.6 起支持单目摄像头/webcam），但深度模式仍需 iPhone 或立体相机对。

### 依据与来源

**3.1 四条官方驱动输入**

**(a) Live Link Face（实时，移动端）**

- iOS：`Live Link Face` app，**iPhone 12 或更新**（推荐 16 / 16 Pro）
- Android：`Live Link Face Android (Beta)`，**仅限特定高通芯片**，官方实测兼容机型：OnePlus 12 5G、ROG Phone 7 Ultimate、Samsung S23 Ultra、Samsung S24 USA/Canada/China、Samsung S24 Ultra、Sony Xperia 1 VI；兼容芯片：Snapdragon 8 Gen 1 / 8+ Gen 1 / 8 Gen 2 / 8 Gen 3 / 8 Elite；**Snapdragon 8s 系列不支持**
- 5.7 新增：iOS/Android 可用**外接相机**生成实时动画；iPad/Android 支持外接 USB 相机；iOS 支持从任意**机内相机**生成动画并录制；实时帧率提升，**高端设备可达 60 FPS**；iOS 设备**无 TrueDepth 相机也可用 MetaHuman Animator 模式**
- **Live Link Face 也用于游戏内**：可打包进 build，运行时建 Live Link 源（社区讨论：<https://forums.unrealengine.com/t/creating-a-new-live-link-source-on-game-start-up-packaged-game/2680349>）

来源：<https://dev.epicgames.com/documentation/metahuman/capture-device-requirements?application_version=5.6>、<https://dev.epicgames.com/documentation/metahuman/metahuman-5-7-release-notes?application_version=5.7&lang=en-US>

**(b) ARKit Face / ARKit 52 blendshape**

官方 Live Link 流程明确要求启用插件 `Live Link`、`Live Link Control Rig`、**`Apple ARKit`、`Apple ARKit Face Support`**，并在 MetaHuman Blueprint 上设置：

- **`ARKit Face Subj`**：选择设备
- **`Use ARKit Face`**：启用

**关于「ARKit 52」这个数字：Epic 官方文档未直接给出「52」这个计数**——官方用「ARKit Face」指代整套 ARKit 面部通道。第三方普遍把 ARKit 的 face blendshape 集合称作 52 个，且有社区工程专门做 MetaHuman↔ARKit 曲线映射（`ARKitRemap`、`unreal-audio2lipsync` 的「52-channel ARKit blendshapes」表述）。**「MetaHuman 原生支持 ARKit 52 blendshape」应标注为：官方支持 ARKit Face 通路（数字 52 未在 Epic 官方文档中找到权威表述）**，且注意 MetaHuman 自身 LOD0 有 **669 个 blendshape**，ARKit 52 只是**输入端**的一个子集接口。

来源：<https://dev.epicgames.com/documentation/metahuman/animating-metahumans-with-livelink-in-unreal-engine?application_version=5.0-5.5>、<https://github.com/Dylanyz/ARKitRemap>、<https://github.com/aaryansachdeva/unreal-audio2lipsync>

**(c) 官方 Audio Driven Animation（音频→口型，官方方案）**

Epic 官方文档《Audio Driven Animation》要点：

- 位于 **MetaHuman Animator** 内，「process audio into realistic facial animation. This can be done **in real time or offline**」
- 前置条件：**UE 5.6+** 项目、启用 MetaHuman Animator 插件、一个或多个 **SoundWave** 资产
- 在 **MetaHuman Performance 资产编辑器**里设 `Input Type = Audio` → 选 SoundWave → 选 Visualization Mesh → Process → 生成 Facial Rig 动画轨道
- 可导出 **Animation Sequence** 或 **Level Sequence**
- 解算参数：Downmix Channels、Audio Channel Index、**Generate Blinks**、**Head Movement**、Frames to Process、**Realtime Audio solver**（实时算法，**不产生头动**）、**Process Mask**（全脸 or 仅嘴部曲线，便于叠加替代 lip sync）、**Solve Overrides**（Mood：Auto Detect / Neutral / Happy(Confident/Excited/Playful) / Sad(Bored) / Fear(Confused) / Disgust / Anger / Surprise）
- 关键区分（原文）：「Although the MetaHuman Performance asset can be configured to generate animation from audio using the Realtime Audio Solver, **this is still an offline process** and is not the same as generating animation in real time from a MetaHuman Audio Live Link Source.」→ **真正的实时音频驱动要点是 Live Link Source（MetaHuman Audio Live Link Source）**，5.7 新增其 **Blueprint 接口**
- 也支持在 **UEFN** 使用（但不能从 performance 导出 level sequence）
- 支持**批量处理**（Content Browser 批量 Audio Driven Animation）

来源：<https://dev.epicgames.com/documentation/metahuman/audio-driven-animation?application_version=5.7>、<https://dev.epicgames.com/documentation/metahuman/metahuman-5-7-release-notes?application_version=5.7&lang=en-US>

**(d) 是否有 NVIDIA Audio2Face 官方/半官方方案**

**未找到权威来源**证明 Epic 与 NVIDIA 有官方集成的 Audio2Face → MetaHuman 通路。NVIDIA 侧有 **Audio2Face-3D**（license: other，见 <https://huggingface.co/nvidia/Audio2Face-3D-v2.3-Mark>）与 Audio2Emotion，第三方/社区有把其输出接 MetaHuman 的做法，但**未找到 Epic 或 NVIDIA 官方的「Audio2Face for MetaHuman」文档**。

- 授权：「是否需额外授权」——Audio2Face-3D 模型卡标注 `license: other`，**具体商用条款未找到权威结论**，需要直接查 NVIDIA 的模型许可与 NVIDIA AI Enterprise 条款；**未找到权威来源**给出确定答案。
- Linux：NVIDIA Audio2Face-3D 本身是 Linux 服务器侧的推理服务（NIM/微服务形态），**Linux 可跑**；但这与「UE 侧驱动 MetaHuman」是两件事。

**3.2 MetaHuman Animator 的输入要求（是否必须 iPhone 深度相机）**

**答案：不再必须。** 官方《Capture Device Requirements》分出两类：

**Realtime Animation（实时）输入：**

| 输入 | 要求 |
|---|---|
| iPhone | **iPhone 12 或更新**（推荐 16/16 Pro），装 Live Link Face iOS |
| Android | 限特定高通芯片，机型见上；Snapdragon 8s 不支持 |
| **单目视频相机（Webcam）** | **任意 Windows UVC 驱动支持的 USB 视频采集设备**；建议关掉自动对焦/自动曝光；**用软件虚拟相机的 webcam 需 Windows 11** |
| **音频（麦克风）** | 任意 Windows UVC 支持的 USB 音频采集设备 |

**Offline Animation（离线）输入：**

| 输入 | 要求 |
|---|---|
| iPhone（深度模式） | **iPhone 12 或更新**（推荐 12），可头戴或三脚架固定；**iPad 虽有深度传感器但未测试、不推荐、不支持** |
| **立体相机对（Stereo Camera Pairs）** | 任意可被 Epic 工具标定的**垂直对齐**立体相机对（垂直是唯一经过充分测试的构型）；支持可见光与红外；**必须头戴**（三脚架装法「very impractical」） |

**5.6 起的关键变化（CG Channel 报道 + 官方）**：MetaHuman Animator「previously required footage from stereo head-mounted cameras or iPhones – **now supports footage from mono cameras like webcams**. The toolset can also now generate facial animation – **both lip sync and head movement – solely from audio recordings**, as well as from video footage.」

来源：<https://dev.epicgames.com/documentation/metahuman/capture-device-requirements?application_version=5.6>、<https://www.cgchannel.com/2025/06/you-can-now-sell-metahumans-or-use-them-in-unity-or-godot/>

**3.3 Linux 无头服务器的硬约束（本节最重要）**

官方文档明确表格：

| MetaHuman 功能 | 平台限制 |
|---|---|
| MetaHuman Animator Markerless Motion Capture 插件 | **Only Supported on Windows** |
| MetaHuman Animator Realtime Animation from mono video or audio | **Only supported on Windows and macOS** |

《Hardware Requirements for MetaHuman Animator》页末结论句（**原文直引，这是本报告最关键的一句**）：

> "**MetaHuman Animator is currently not supported on macOS and Linux.**"

（注：这与 5.7 release notes 里「MetaHuman Creator 支持 Linux/macOS，**MetaHuman Animator 支持计划在未来版本**」一致——Animator 的 Linux 支持**尚未发布**。）

来源（Animator 硬件要求页，含上述原文）：<https://dev.epicgames.com/documentation/metahuman/hardware-requirements-for-animator?application_version=5.6&lang=en-US>
来源（平台限制表，含「Only Supported on Windows」/「Only supported on Windows and macOS」）：<https://dev.epicgames.com/documentation/en-us/metahuman/metahuman-hardware-requirements-in-unreal-engine>
来源（5.7 release notes 的 Linux 支持范围）：<https://dev.epicgames.com/documentation/metahuman/metahuman-5-7-release-notes?application_version=5.7&lang=en-US>

> **复核提示**：`https://dev.epicgames.com/documentation/metahuman/hardware-requirements?application_version=5.7`（无 `-in-unreal-engine` 后缀）返回 HTTP 200 但正文为空（JS 渲染），故本报告引用的是带完整后缀的 URL 与 5.6 版的 Animator 专页。

**MetaHuman Animator 的算力要求（若要在云端跑离线解算）：**

- 最低：i7-6700 / Ryzen 5 2500X（≥8 逻辑核）；**RTX 2070 / RX 5500 XT（≥8GB VRAM）**；每逻辑核 2GB 内存，**最少 32 GB**；SSD；**Windows 10 64-bit**；**DX12**
- 推荐：i9-12900 / Ryzen 9 5950X（≥16 物理核）；**RTX 3080 / RX 6800 XT（10GB VRAM）**；每逻辑核 4GB，**最少 64 GB**；NVMe
- **存储消耗**：iPhone 高质量 @60fps 素材 **约 800 MB/分钟**；立体相机 @60FPS 1440x1920 **约 45 GB/分钟**

来源：<https://dev.epicgames.com/documentation/metahuman/hardware-requirements-for-animator?application_version=5.6&lang=en-US>

> **注**：43–45 GB/分钟 的立体素材存储量意味着云端离线 Animator 方案的存储与上传带宽成本会非常夸张，这是它不适合做「实时交互」的直接原因之一。

---

## 4. MetaHuman 授权

### 结论（1–3 行）

**可以商用，也可以用于云端渲染并流式给终端用户**——2025 年 6 月起 MetaHuman 工具集适用**标准 UE EULA**，角色/服装可出售、可用于任意引擎（含 Unity/Godot）的商业项目；且 MetaHuman 角色与动画被归类为「**non-engine products**」，用在非 UE 引擎的游戏里**不产生 5% 分成**。**未找到**「禁止把 MetaHuman 作为服务提供给第三方」的条款；真正的硬限制是 **AI 相关**：不得用 MetaHuman 技术「building or enhancing any database or **training or testing any AI/ML/deep learning/neural network** or similar technology」。至于像素流服务是否算「产品」——**渲染出的视频/流媒体文件属 UE EULA 里的 Non-Engine Products，明确不产生 royalty**。

### 依据与来源

**4.1 商用与云端渲染**

2025-06 Epic 结束 Early Access 时同步改了授权（CG Channel 报道，引 Epic 官方 license 页）：

- 工具集改由**标准 Unreal Engine EULA** 覆盖 → **年收入 < 100 万美元**的美术/工作室**免费**使用
- MetaHuman 角色与服装**可在在线市场出售**，可用于**其他 DCC 应用或游戏引擎**的商业项目
- **唯一例外是 AI**：可用于「workflows that incorporate artificial intelligence technology」，但**不能用于训练或增强 AI 模型本身**
- 年收入 > 100 万美元且项目使用 MetaHuman 角色，需要 **UE 席位许可，$1,850/年**
- 因被归类为 **non-engine products**，在 Unity/Godot 等**非 UE 引擎**游戏中使用**不产生 5% 分成**

来源：<https://www.cgchannel.com/2025/06/you-can-now-sell-metahumans-or-use-them-in-unity-or-godot/>

Epic 官方 license FAQ 页（**注：该页为 JS 渲染，抓取只得到标题，正文未能取回**，故本条仅以 CG Channel 的转述为据，请以 Epic 原页为准）：<https://www.metahuman.com/en-US/license>、<https://www.metahuman.com/license>

**4.2 AI 相关禁止条款（原文摘录，通过社区引用获得）**

社区帖引用了 EULA 中关于生成式 AI 的段落：

> "While this Agreement is not intended to prevent you from exercising the rights in Downloaded Characters granted to you by Epic under the Epic Content License Agreement, there are certain things you may not do with the MetaHuman Technology. You may not do any of the following with respect to the MetaHuman Technology or any of its parts: … **(j) for the purpose of building or enhancing any database or training or testing any artificial intelligence, machine learning, deep learning, neural network or similar technology**;…"

该帖发帖人询问「用渲染出的 MetaHuman 线性内容做 deepfake 是否受此限制」，**该帖未看到 Epic 的官方答复**，因此**「渲染输出是否也受限」未找到权威来源**。稳妥解读：限制的对象是 **MetaHuman Technology**（技术本体），而输出内容受 Epic Content License Agreement 的 Linear Media/Rendered Video 条款约束（见 4.3）。**此段为 EULA 原文转引，权威性低于直读 EULA，建议上线前由法务直读 <https://www.unrealengine.com/eula/mhc>。**

来源：<https://forums.unrealengine.com/t/creating-deepfakes-with-metahumans-is-it-allowed/2378212>、EULA 原文入口：<https://www.unrealengine.com/eula/mhc?lang=en-US>

> **注意**：`https://www.unrealengine.com/eula/mhc` 抓取返回 **HTTP 403**，本报告未能直读原文，仅能引用二手转述。EULA 也要求登录/受邀才能访问（2021 年论坛帖已提到该链接对未登录用户是空白页）。

**4.3 像素流服务是否算「产品」/ 是否触发 5% royalty**

UE EULA 的 **Non-Engine Products** 条款（社区帖引用原文）：

> "i. Non-Engine Products (e.g., Rendered Video Files) … This means, for example, you will not owe us royalties for Distributing: **rendered video files (e.g., broadcast or streamed video files, cartoons, movies, or images) created using the Engine Code** (even if the video files include Starter Content)"

Epic Content License Agreement：

> "b. Linear Media (e.g., Rendered Video Files) — You may freely Distribute Licensed Content incorporated into rendered linear media products. This means, for example, you may freely Distribute **rendered video files (e.g., broadcast or streamed video files, cartoons, or movies) or images** created using Licensed Content."

→ 像素流送出去的**正是 streamed video files**，落在 Non-Engine Products / Linear Media 里，**官方口径下不产生 royalty**。

来源（转引 + 官方入口）：<https://forums.unrealengine.com/t/license-agreement-can-i-use-rendered-images-of-metahumans-elsewhere/1716398>、<https://www.unrealengine.com/en-US/eula/unreal>、<https://www.unrealengine.com/en-US/eula/content>

> **仍未找到权威来源的点**：Epic 官方是否有专门针对「把 UE 应用作为 SaaS / 像素流服务售卖」的定性说明。上面两条是间接推导（渲染视频文件 = Non-Engine Product），**不是 Epic 对像素流服务的直接表态**。若要落地上线，建议就「像素流 SaaS 是否需 UE 席位许可 / 是否触发 royalty」直接向 Epic 书面确认。年收入 > $1M 的席位许可价格：**$1,850/年**（来源同 CG Channel）。

**4.4 「禁止作为服务提供给第三方」条款**

**未找到权威来源**。检索未发现 MetaHuman/UE 授权中有「不得将 MetaHuman 作为服务提供给第三方」的表述。相反，第三方云渲染商业服务（Vagon Streams、Eagle 3D Streaming、腾讯云 CAR、天翼云实时云渲染等）公开销售基于 UE 的像素流服务，且 Epic 官方托管指南把这类服务商列为推荐选项（见 §5），可反证不存在此类禁令。

---

## 5. 像素流（Pixel Streaming）方案现状

### 结论（1–3 行）

**Pixel Streaming 2 从 UE 5.5 起引入，与原插件并存**（官方明确「both … will be shipped with Unreal Engine to give users time to migrate」），信令服务器 + WebRTC + （可选 SFU）架构不变，官方推荐**自建动态伸缩或采购第三方 PaaS**。**单卡并发上限的硬约束是 NVENC 编码会话数：消费级 GeForce 卡 12 路，专业/服务器卡 Unrestricted**；Epic 工程师的实战经验是「**多数人最终是 1 台机器 1 个 UE 实例**」，好一点的情况单机 4 实例。延迟：官方未给端到端数字（只给编码耗时），业界口径 **50–200ms（像素流）/ 60–80ms（腾讯云 CAR）**。Linux 无头（`-RenderOffscreen`）是官方推荐做法，**但 MetaHuman Animator 本身不支持 Linux**。

### 依据与来源

**5.1 推荐架构与版本**

Epic 官方《Pixel Streaming 2 Overview》：

- 「**From UE 5.5 onwards**, we introduced a layer that makes it easier for Epic to maintain WebRTC internally… We have decided to introduce a new plugin to provide a better transition phase… **For now, both the original Pixel Streaming plugin and the Pixel Streaming 2 plugin will be shipped with Unreal Engine** to give users time to migrate.」
- 兼容性：「Pixel Streaming 2 is **directly compatible with the existing Pixel Streaming infrastructure**」，建议用与引擎版本对应的仓库分支
- 变更：所有 Blueprint 节点有 PS2 版本（需手动重建重连，无 redirector）；C++ API 大改（**移除了所有 WebRTC 类型**）；设置可从 `.ini`/命令行/console 设，优先级 `.ini` < 命令行 < console
- **Pixel Streaming Player 功能已内置进 PS2**（不再需要额外插件）

来源：<https://dev.epicgames.com/documentation/en-us/unreal-engine/pixel-streaming-2-overview-in-unreal-engine>

**架构组件与端口（官方 Pixel Streaming Reference）：**

| 组件 | 端口 |
|---|---|
| Signalling Server host | 80 (HTTP) / 443 (HTTPS) / **8888**（UE 应用连入，`--streamerPort` + `-PixelStreamingPort`） |
| Matchmaker Server host | 90 (HTTP) / 9999（信令发消息） |
| SFU | **8889**（信令 ↔ SFU） |

> **注意**：官方同页指出「if you're hosting your own STUN or TURN server…」，但托管指南明确 **matchmaking server 已在 UE 5.5 弃用**——「we provided a simple matchmaking server… this matchmaking was not a dynamic scaling solution… so **we deprecated it in Unreal Engine 5.5**」。

**官方明确推荐的伸缩方式（原文）：**

> "For a production Pixel Streaming deployment, **we recommend a dynamic scaling solution**… Ideally, your scaling solution should provision a new Unreal Engine instance instantly whenever a user connects. … **While a complete, ready-made scaling solution is outside the scope of what we provide**, the Pixel Streaming repository contains all the essential components and libraries to build your own. … Alternatively, there are a number of **cloud-based solutions and service providers** who offer dynamic scaling solutions for Pixel Streaming."

**信令/Web 服务器定位（原文）：**

> "The signalling server, web server, and matchmaker server that accompany Pixel Streaming are a **reference implementation only**. We do not view them as being a complete solution for all cases, rather, **we encourage you to modify them**."

**SFU 状态（原文）：**

> "**At this time the SFU feature of Pixel Streaming is experimental.**" 采用 simulcast：UE 实例生成多分辨率流，SFU 按接收端网络选择。默认配 3 档（full / half / quarter 分辨率）。

来源：<https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-pixel-streaming-reference>、<https://dev.epicgames.com/documentation/en-us/unreal-engine/hosting-and-networking-guide-for-pixel-streaming-in-unreal-engine?application_version=5.6>

**支持的编码器（官方表，含实测编码耗时）：**

| 编码器 | 加速方式 | 1080p / 4K 编码速度 | 低码率画质 | 每 peer 的 CPU/GPU 开销 |
|---|---|---|---|---|
| **H.264** | GPU (NVIDIA/AMD/Apple M) | **~8.97ms / ~24.17ms** | 块状 | **每 peer 一个 GPU 编码会话，上限为 GPU 会话限制** |
| VP8 | CPU | ~10.5ms / ~25ms | 一般 | CPU 线性随 peer 数增长 |
| VP9 | CPU | ~15ms / ~50ms | 好 | CPU 线性随 peer 数增长 |
| **AV1** | GPU（**NVIDIA Ada Lovelace 或更新**） | **~8.98ms / ~15.8ms** | 最好 | 每 peer 一个 GPU 编码会话，上限为 GPU 会话限制 |

官方建议：**优先用 AV1**（若硬件支持），因为「achieves higher quality video at lower bitrates」。
测试环境：1080p 数据取自 **RTX 3060 + AMD 3900X**；AV1 取自 **NVIDIA RTX 6000 Ada**。
默认编码器：`PixelStreaming.Encoder.Codec = H264`；默认码率 `MaxBitrateVBR = 20000000`（20 Mbps）；默认 RateControl = **CBR**（官方钦定唯一推荐）；默认 H264 Profile = **BASELINE**；默认 WebRTC `MaxFps = 60`；默认 `StartBitrate = 10000000`（10 Mbps）。
默认 **`PixelStreaming.WebRTC.DisableAudioSync = true`**（关闭音视频同步以**改善延迟**）。

来源：<https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-pixel-streaming-reference>

**5.2 单 GPU 能承载几路并发（核心约束）**

**(a) 编码器会话数硬上限（NVIDIA 官方 matrix）**

NVIDIA 官方 Video Encode Support Matrix：消费级 **GeForce** 全系（含 RTX 30/40/50 系列）**Max # of concurrent sessions = 12**；而 **Professional（RTX/Quadro）与 Server（数据中心）为 `Unrestricted`（无限制）**。

来源：<https://developer.nvidia.com/video-encode-decode-support-matrix>

**(b) Epic 官方口径（有个内部矛盾，需注意）**

Pixel Streaming 托管指南原文：

> "If you create more than eight simulcast streams you may hit up against limits when using the H.264 hardware encoders on consumer GPUs that **often have a limit of eight encoding sessions**. In Pixel Streaming 2, **any streams beyond the 8th will automatically switch to software encoders.** This is unique to Nvidia hardware."

→**Epic 文档写的是 8，NVIDIA 当前 matrix 写的是 12**。这个差异很可能来自文档撰写时点的旧驱动策略。**两个数字都给，落地时必须实测确认。** 结论不变：**消费级卡有硬上限，超过就掉到软件编码（CPU 线性增长），专业/服务器卡无限制。**

来源：<https://dev.epicgames.com/documentation/en-us/unreal-engine/hosting-and-networking-guide-for-pixel-streaming-in-unreal-engine?application_version=5.6>

**(c) 实战并发经验（Epic 工程师本人）**

Epic 员工 Stephen Phillips 在官方论坛回复「50–500 并发」问题时：

> "**I've seen some applications run comfortably with 4 instances on a single machine, but in my honest experience most people will end up with 1 machine per 1 UE instance.** Additionally, **most self serve pixel streaming services out there are architected this way for simplicity.**"

多 GPU 机器需用 **`-graphicsadapter=[0 or 1]`** 指定 GPU（他本人没试过）。

同帖另一位回复（非 Epic 官方）建议 50–500 并发用 **RTX 6000 Ada**（高 VRAM、虚拟化支持、24/7 稳定性），「You'd typically run **one UE instance per GPU** to avoid encoding bottlenecks」。

来源：<https://unreal2.epic-prod-us2.discourse.cloud/t/best-setup-for-running-multiple-avatars-with-pixel-streaming-50-500-users/2636562>

**(d) 社区经验值（二手，仅作参考）**

同一帖的另一条回复（第三方）：

> "A consumer grade Nvidia card has a **hard limit of 8 concurrent video encoding sessions** simultaneously, whilst many professional cards do not have a hard limit. **I would be surprised if you could run 8 1920x1080 streams at once on a consumer card. Professional cards would likely tap out before 16 streams.**"

来源：<https://forums.unrealengine.com/t/using-pixel-streaming-2-for-web-service-client-isolation-and-performance-questions/2496269/3>

**综合判断（1080p60 / 720p30 区分）：**

| 场景 | 单卡并发（工程可落地估计） | 依据 |
|---|---|---|
| **1080p60，单 GPU（如 A10G/L4/RTX 4090）** | **1–4 路**（Epic 工程师经验） | Epic 论坛 |
| **1080p60，消费级卡理论上限** | 编码会话 ≤12（NVIDIA）/ Epic 文档写 8 以上掉软编 | NVIDIA matrix + Epic 文档 |
| **1080p60，专业卡理论上限** | 编码无上限，但**渲染/显存先成为瓶颈**；第三方估计「likely tap out before 16 streams」 | NVIDIA matrix + 社区 |
| **720p30** | **未找到权威来源**给出具体并发数字 | — |

> **重要**：**没有官方「单卡 X 路 1080p60 / Y 路 720p30」的权威数字。** 官方只给了编码耗时的单帧基准（H.264 1080p ~8.97ms/帧）和「编码会话数」这一离散上限。真实并发取决于 **GPU 渲染负载（MetaHuman 本身极重）、显存、CPU、NVENC 会话数**四者中最先到顶的那个——**必须实测**。Epic 工程师原话即为此意：「people always throw money at GPUs even if the GPU isn't the bottleneck」。

**5.3 端到端延迟**

**官方未给端到端延迟数字。** 官方能给的只有编码耗时（见上表：H.264 1080p ~8.97ms，AV1 1080p ~8.98ms）与一批降延迟的开关：

- `PixelStreaming.WebRTC.DisableAudioSync` 默认 **true**（「improves latency if synchronization is not required」）
- `PixelStreaming.WebRTC.DisableReceiveAudio` / `DisableTransmitAudio`（「If audio is not required can improve latency in some cases」）
- `PixelStreaming.WebRTC.DegradationPreference` 默认 `MAINTAIN_FRAMERATE`
- `PixelStreaming.DecoupleFramerate`（解耦 WebRTC 与应用的 FPS）
- 官方还提供了**内建延迟测试**：`PixelStreaming.DisableLatencyTester` 默认 `false`（即可用），「Disables the ability to trigger latency tests that pass through the Pixel Streaming Plugin pipeline」→ **即官方自带 latency tester，部署后应自己测而不是抄别人的数字**

来源：<https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-pixel-streaming-reference>

**业界口径（二手，媒体/厂商自述）：**

| 来源 | 延迟数字 | 性质 |
|---|---|---|
| Paraverse 平行云（腾讯云开发者社区，2025-11） | 像素流送 **网络时延 50ms–200ms**；实时云渲染 **20ms–200ms**，弱网自适应更好 | 第三方厂商对比文 |
| 腾讯云应用云渲染（CAR）产品文（2026-06） | **端到端 60–80ms** | 厂商自述（营销口径） |

来源：<https://cloud.tencent.cn/developer/article/2591885>、<https://cloud.tencent.cn/developer/article/2691721>

> **结论**：**「同区域」和「公网」的具体端到端延迟范围，未找到权威第三方式测量报告。** 可用的可信锚点是「数十毫秒到二百毫秒」这个量级，且**公网（尤其移动网络）比同区域差很多**。同区域/同 AZ 部署是唯一能把延迟压到可控的手段（这也是为什么云渲染厂商强调边缘节点）。

**5.4 Linux 无头部署（成熟度与坑）**

**成熟的部分：**

- `-RenderOffscreen` 是**官方推荐**：「Run the Unreal Engine application headless, without any visible rendering at all… **We therefore recommend always including this parameter**, unless you need to be able to see the rendered output from the Unreal Engine application locally」
- 配套官方参数：`-ForceRes` + `-ResX` / `-ResY`（「useful in a cloud deployment where there typically is no display resolution」）、`-AudioMixer`（无音频设备时强制软件混音）、`-Unattended`（抑制错误对话框，**「messages boxes can hang indefinitely」**，容器里必须加）、`-StdOut` + `-FullStdOutLogOutput`（SSH 下看日志）
- 平台支持：**Linux 是官方支持的 Pixel Streaming 平台**（Windows / Linux / Mac），且「The Pixel Streaming Plugin and the accompanying Signalling and Web Server have only been tested on Windows 10/11, **Ubuntu 18.04/20.04/22.04/24.04**, and MacOS Ventura 13.5.1」
- GPU 要求：需 **NVENC（NVIDIA）/ AMF（AMD）/ VideoToolbox（Apple）** 支持；否则报 *No compatible GPU found, or failed to load their respective encoder libraries*
- Epic 官方提供 Docker 镜像生态：`ghcr.io/epicgames/unreal-engine:runtime-pixel-streaming`（社区实践参考：<https://forums.unrealengine.com/t/how-to-run-unreal-engine-app-with-pixel-streaming-using-ghcr-io-epicgames-unreal-engine-runtime-pixel-streaming-in-docker/1934433>）
- 5.7 起 **MetaHuman Creator 插件本身也支持 Linux**，MetaHuman for Maya / for Houdini 也支持 Linux

**已知的坑：**

1. **`-RenderOffscreen` 不是可选项**：官方原文「If this application window is ever minimized, **the Pixel Streaming video and input capture will stop working**」
2. **`-Unattended` 必须加**：容器/无头环境里错误对话框会**无限挂起**
3. **启动时间对磁盘 IO 极敏感（实测案例）**：Epic 论坛一个 UE Pixel Streaming 应用从 OCI 迁到 Azure，**OCI 约 1 分 30 秒启动，Azure 约 3 分钟**。Epic 支持团队分析 utrace 后定位为**磁盘层面问题**：「Unreal Engine およびプラグインの DLL を読み込む速度の開きは 2 倍あります（具体的には、**Windows_LoadLibrary のイベントで、OCI は 12 秒、Azure は 24 秒**）」；且发现 Azure 侧还在从**远程 DDC 缓存取贴图**（本该本地 DDC 缓存）。**修复方向：优化 pak 文件顺序、确保 DDC 本地缓存。** 同一案例还提到 Azure 上**必须加 `-RenderOffscreen -ForceRes` 否则 fps 极低**（OCI 上不加也没事）
4. **MetaHuman Animator 不能在 Linux 跑**（见 §3.3）——若方案依赖 Animator 做实时驱动，Linux 无头服务器这条路**直接断了**
5. **SFU 仍是 experimental**（官方标注）
6. **Matchmaking server 已弃用（UE 5.5）**，官方不再提供现成伸缩方案

来源：<https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-pixel-streaming-reference>、<https://unreal2.epic-prod-us2.discourse.cloud/t/azure-unreal-engine/2680356>、<https://dev.epicgames.com/documentation/en-us/unreal-engine/hosting-and-networking-guide-for-pixel-streaming-in-unreal-engine?application_version=5.6>、<https://dev.epicgames.com/documentation/metahuman/metahuman-5-7-release-notes?application_version=5.7&lang=en-US>

---

## 6. 成本量级

### 结论（1–3 行）

裸 GPU 云主机（AWS g5/g6）约 **$0.98–$1.01/小时**起（1×A10G 或 1×L4，4 vCPU/16GB）；国内（阿里云 gn7i）按量约 **¥5.34–7.88/小时**（A10），腾讯云 GN7vw（T4）按**月**计费约 **¥3,528/月**。**「每路并发流每小时成本」有现成的商业化报价可以直接用**：天翼云实时云渲染「按需计费 **¥2.5 / 6.4 / 7.8 元/路/小时**（标准/高级/旗舰型）」，腾讯云 CAR 包月 **¥343–955/元/月/路**。**冷启动：UE 打包应用启动到可服务约 1.5–3 分钟**（实测案例），业界常用「预分配（preallocated）」把等待压到几秒——代价是 GPU 24/7 空转。

### 依据与来源

**6.1 AWS GPU 实例（按需，us-east-1，Linux）**

| 实例 | GPU | vCPU / RAM | 按需 $/小时 | 来源 |
|---|---|---|---|---|
| **g5.xlarge** | 1× A10G (24 GB) | 4 / 16 GB | **$1.0060** | DoiT Compute（Spot 最低 $0.4120） |
| **g5.2xlarge** | 1× A10G | 8 / 32 GB | **$1.2120** | DoiT |
| g5.4xlarge | 1× A10G | 16 / 64 GB | $1.6240 | DoiT |
| g5.12xlarge | 4× A10G | 48 / 192 GB | $5.6720 | DoiT |
| **g6.xlarge** | 1× L4 (24 GB) | 4 / 16 GB | **$0.978**（Wring）/ **$0.80**（VPSBenchmarks） | 见下 |
| g6.2xlarge | 1× L4 | 8 / 32 GB | $1.168 | Wring |
| g6.4xlarge | 1× L4 | 16 / 64 GB | $1.548 | Wring |
| g6.12xlarge | 4× L4 | 48 / 192 GB | $5.016 | Wring |
| g6.48xlarge | 8× L4 | 192 / 768 GB | $13.35 | Wring |
| g4dn.xlarge | 1× T4 | — | $0.526（家族最低） | Wring |

**g6.xlarge 价格有分歧**：Wring 报 **$0.978**，VPSBenchmarks 报 **$0.80**（VPSBenchmarks 自述「data shown is gathered on a best-effort basis and may not be completely accurate or up-to-date」）。**以 AWS 官方定价页为准**，本报告两个都给：<https://aws.amazon.com/ec2/pricing/>

Spot 价（DoiT，us-east-1 实测）：g5.xlarge 各 AZ **$0.4120–$0.5730**（省 43–59%）；g5.12xlarge Spot $3.2622。

来源：<https://www.doit.com/compute/compute/aws/us-east-1/g5.xlarge>、<https://wring.co/blog/aws-gpu-instance-pricing-guide>、<https://www.vpsbenchmarks.com/gpu_plans/amazon_aws/g6-xlarge>

> **注**：Wring 文章标注「March 15, 2026，Updated September 11, 2026」，VPSBenchmarks 页面无明确日期。DoiT 页面声明「not maintained by or affiliated with any of the compute or AI vendors… may not be completely accurate」。**这三个都不是 AWS 官方一手来源，务必以 <https://aws.amazon.com/ec2/pricing/> 复核。**

**6.2 阿里云（按量付费，元/小时）**

官方未直读定价页，以下来自阿里云开发者社区价格汇总（含 GPU 缓存型预留实例券价格，可反推）：**「零预付预留费用（每小时）」列即接近按量单价**。

| 实例 | vCPU / 内存 | 零预付预留 元/小时 | 半预付预留 元/小时 |
|---|---|---|---|
| **ecs.gn7i-c8g1.2xlarge**（A10） | 8 / 30 GiB | **5.899** | 2.809 |
| **ecs.gn7i-c16g1.4xlarge**（A10） | 16 / 60 GiB | **6.246** | 2.974 |
| **ecs.gn7i-c32g1.8xlarge**（A10） | 32 / 188 GiB | **8.235** | 3.922 |
| ecs.gn7i-c32g1.16xlarge | 64 / 376 GiB | 16.470 | 7.843 |
| ecs.gn7i-c32g1.32xlarge | 128 / 752 GiB | 32.941 | 15.686 |
| ecs.gn6v-c8g1.2xlarge（V100） | 8 / 32 GiB | 5.206 | 2.479 |
| ecs.gn6i-c4g1.xlarge（T4） | 4 / 15 GiB | 2.546 | 1.213 |
| ecs.gn6i-c8g1.2xlarge（T4） | 8 / 31 GiB | 3.066 | 1.460 |

另一处提到 **ecs.gn7i-c32g1.8xlarge 月付 ¥3,203.99（5 折）**——折算约 **¥4.45/小时**（按 720 小时），说明**包月比按量便宜约 45%**。

来源：<https://developer.aliyun.com/article/1697257>（价格汇总表，2025-12-29）、<https://developer.aliyun.com/article/1733531>（gn7i-c32g1.8xlarge 月付 ¥3,203.99，2026-05-10）

> **免责**：以上为**阿里云开发者社区用户投稿的价格汇总**，非阿里云官方定价页（原文有「版权声明：本文内容由阿里云实名注册用户自发贡献…不承担相应法律责任」）。**务必以 <https://www.aliyun.com/price/detail> 或 ECS 定价页复核。** 官方国际站定价入口：<https://www.alibabacloud.com/zh/product/ecs-pricing-list/en>

**6.3 腾讯云**

**GN7vw（Tesla T4 + vDWS + GRID driver，渲染型）——官方文档，按「月后付费」：**

| 机型 | vCPU | 内存 | GPU | 价格（元/月） |
|---|---|---|---|---|
| GN7vw.LARGE16 | 4 | 16 GB | 1/4 T4 | **1,047** |
| GN7vw.2XLARGE32 | 8 | 32 GB | 1/2 T4 | **1,874** |
| GN7vw.4XLARGE64 | 16 | 64 GB | 1 T4 | **3,528** |
| GN7vw.8XLARGE128 | 32 | 128 GB | 2 T4 | **7,056** |

本地 SSD 存储 **1 元/GB/月**。计费说明原文：「GPU 机型 GN7vw 实例是基于 NVIDIA Tesla T4 GPU 卡，配置了 vDWS License 服务器并安装 GRID driver 的渲染型实例，适用于图形图像处理场景（3D 渲染或视频编解码）」。

来源（腾讯云官方文档）：<https://cloud.tencent.cn/document/product/1108/55463>

**腾讯云应用云渲染（CAR）——官方文档，按「并发」售卖（1 路并发 = 1 个用户同时使用）：**

并发规格（官方）：

| 规格 | vCPU | 内存 | GPU 性能 | 显存 | 带宽 | 适用 |
|---|---|---|---|---|---|---|
| S 小型 | ≥4 核 | ≥8 GB | ≥2 TF SP / 30T INT | ≥4 G | ≤6 Mbps | 小型桌面应用 |
| M 中型 | ≥4 核 | ≥16 GB | ≥4 TF SP | ≥6 G | ≤8 Mbps | 中型桌面应用 |
| L 大型 | ≥10 核 | ≥32 GB | ≥8.1 TF SP | ≥12 G | ≤8 Mbps | 大型桌面应用 |
| L2 大型 | ≥10 核 | ≥40 GB | ≥13.45 TF SP | ≥11 GB | ≤8 Mbps | 大型桌面应用 |
| XL 超大型 | ≥12 核 | ≥44 GB | ≥16 TF SP | ≥24 G | ≤10 Mbps | 超大型桌面应用 |

官方原文强调：「**1路并发支持1个用户同时访问使用**」、「若峰值支持 1000 用户同时进入，可购买 1000 路包月或包天的 L/XL 型并发，超过时排队等待并发释放」。

**实际价格（官方文档页详情 + 社区活动价）：**

| 商品 | 计费 | 规格 | 活动价 | 原价 |
|---|---|---|---|---|
| 预付费包天并发 | 包天 | S | ¥17.2/天 | ¥172/天 |
| 预付费包天并发 | 包天 | M | ¥26.2/天 | ¥262/天 |
| 预付费包天并发 | 包天 | L | ¥37.7/天 | ¥377/天 |
| 预付费包天并发 | 包天 | XL | ¥47.8/天 | ¥478/天 |
| 预付费包月并发 | 包月 | S | **¥343/月** | ¥1,717/月 |
| 预付费包月并发 | 包月 | M | **¥524/月** | ¥2,620/月 |
| 预付费包月并发 | 包月 | L | **¥753/月** | ¥3,765/月 |
| 预付费包月并发 | 包月 | XL | **¥955/月** | ¥4,775/月 |
| 100 小时资源包（企业 5 折） | 资源包 | S（≤10 并发） | ¥846 | ¥1,692 |
| 100 小时资源包 | 资源包 | M | ¥1,156 | ¥2,312 |
| 100 小时资源包 | 资源包 | L | ¥1,824.5 | ¥3,649 |

来源（官方文档）：<https://cloud.tencent.cn/document/product/1547/72168>（2025-07-21 更新）；活动价明细见 <https://cloud.tencent.cn/developer/article/2691721>（2026-06-17，含 100 小时资源包）

> **国际站差异**：腾讯云国际站的 CAR 计费说明只列并发规格与计费周期，**按 `USD/concurrent user/month` 报价但不公开单价**（需联系销售）。国内站才给出上表 CNY 数字。来源：<https://www.tencentcloud.com/document/product/1158/49606>（2025-08-05 更新）

**6.4 天翼云实时云渲染（按路报价，最适合做「每路成本」锚点）**

官方文档《计费模式》（实时云渲染）：

| 服务类型 | 规格 | CPU | 内存 | GPU 性能 | 显存 | 计费方式 | 标准资费 |
|---|---|---|---|---|---|---|---|
| 渲染实例 标准型 | 三维应用主流云应用 | 8–12 核 | 16–24 G | ≥12 TF SP / 30T INT | 6 GB | 包年包月 | **1,180 元/路/月** |
| 渲染实例 标准型 | 同上 | 同上 | 同上 | 同上 | 同上 | **按需计费** | **2.5 元/路/小时** |
| 渲染实例 高级型 | 3A 级云游戏 | 16 核 | 16–24 G | ≥29 TF SP / 60T INT | 10 GB | 包年包月 | 3,100 元/路/月 |
| 渲染实例 高级型 | 同上 | 同上 | 同上 | 同上 | 同上 | **按需计费** | **6.4 元/路/小时** |
| 渲染实例 旗舰型 | 医学影像、数字孪生 | 24 核 | 32 G | ≥35 TF SP / 60T INT | 24 GB | 包年包月 | 3,800 元/路/月 |
| 渲染实例 旗舰型 | 同上 | 同上 | 同上 | 同上 | 同上 | **按需计费** | **7.8 元/路/小时** |

官方原文关键句：「**1 路渲染实例同一时刻最多可为 1 个终端提供应用接入**」。

来源（天翼云官方文档）：<https://www.ctyun.cn/document/10019425/10323628>（该产品页标注「文档停止维护」，但价格表完整）

**6.5 阿里云云渲染 GCS（按 R 实例计价，元/时）**

官方文档《计费模式与详细价格说明》：

| 规格 | 计算能力 | 配置 | 按量价格（元/时） |
|---|---|---|---|
| gcs.r1c1m1.1xlarge | UNGINE Superposition 3600+ | 12 核+ / 30GB+ | **7.059** |
| gcs.r2c1m1.1xlarge | UNGINE Superposition 8000+ | 10 核+ / 30GB+ | **8.953** |
| gcs.r2c2m2.1xlarge | UNGINE Superposition 8000+ | 20 核+ / 60GB+ | **12.237** |
| gcs.r1c1m1.4xlarge | US 3600+ ×4 | 48 核+ / 120GB+ | 26.831 |
| gcs.r2c1m1.4xlarge | US 8000+ ×4 | 40 核+ / 120GB+ | 34.406 |
| gcs.r2c2m2.2xlarge | US 8000+ ×2 | 40 核+ / 120GB+ | 24.005 |

官方定义：「渲染实例（R 实例）是面向实时 3D 渲染组合实例，实例计算资源包含：CPU 计算资源，GPU 计算资源（含处理器和显存），内存，网络带宽资源。」规格按 **UNGINE Superposition** 图形基准划分。

来源（阿里云官方文档）：<https://help.aliyun.com/zh/gcs/product-overview/billing-overview>（该页亦标注「云渲染（文档停止维护）」）

**6.6 「每路并发流每小时成本」估算范围**

**可直接引用的商业化报价（最可靠）：**

| 供应商 | 类型 | 每路每小时（折合） | 来源 |
|---|---|---|---|
| **天翼云** | 标准型 | **¥2.5** | 官方文档 |
| **天翼云** | 高级型（3A 云游戏） | **¥6.4** | 官方文档 |
| **天翼云** | 旗舰型（24GB 显存） | **¥7.8** | 官方文档 |
| **腾讯云 CAR** | M 型包月 ¥524/月 | **≈¥0.73**（720h） | 官方+活动价 |
| **腾讯云 CAR** | L 型包月 ¥753/月 | **≈¥1.05**（720h） | 官方+活动价 |
| **腾讯云 CAR** | XL 型包月 ¥955/月 | **≈¥1.33**（720h） | 官方+活动价 |
| **腾讯云 CAR** | L 型包天 ¥37.7/天 | **≈¥1.57**（24h） | 活动价 |
| **腾讯云 CAR** | L 型 100h 资源包 ¥1,824.5 | **≈¥18.2**（但含 ≤10 并发） | 活动价 |

**自建（裸机 + 自己实现伸缩/调度）的参考成本：**

- AWS **g5.xlarge $1.006/h ≈ ¥7.2/h**（按 7.2 汇率）——**若单卡只跑 1 路，就是 ¥7.2/路/小时**；若单卡跑 4 路，理论摊到 **¥1.8/路/小时**（但**前提是渲染负载撑得住**，MetaHuman 顶配几乎不可能）
- 阿里云 **gn7i-c8g1.2xlarge ¥5.899/h**（A10，8vCPU/30GB）——同样，单路即 ¥5.9/h
- 还必须叠加：**带宽/流量费（云渲染出口流量极贵，是隐性大项）、信令/Web 服务器、调度与监控、音视频运维人力、冗余**。腾讯云自己的对比文对此的表述是：「GPU 服务器采购/租赁、带宽、IDC/机房、音视频工程师、DevOps、监控告警、冗余备份…**小团队的隐性成本远超买 PaaS**」

**业界常见估算范围（结论）：**

- **用 PaaS/云渲染按路报价：约 ¥1–8 / 路 / 小时**（包月长挂载可低至 ~¥0.7–1.3，按需短时高峰 ¥2.5–7.8）
- **自建裸 GPU 机：硬件成本约 ¥5–8 / 路 / 小时**（若单卡 1 路），**摊薄到 4 路约 ¥1.5–2 / 路 / 小时**，另加带宽与人力

**未找到权威来源**的点：**没有权威第三方对「UE Pixel Streaming 每路并发成本」的独立测算报告。** 上述数字均来自供应商官方文档或厂商自述营销文，存在口径差异（是否含带宽、是否含 GPU 独占、规格档位不同）。参考：Wonderland Engine 的成本计算器（第三方，列出各 provider 单价，但本身是竞品营销工具，其结论倾向客户端渲染）：<https://wonderlandengine.com/pixel-streaming-cost-calculator/>

**6.7 弹性伸缩冷启动时间**

| 数字 | 场景 | 来源 |
|---|---|---|
| **约 1 分 30 秒** | UE Pixel Streaming 应用在 **OCI** 上启动 | Epic 论坛实测 + Epic 支持团队定位 |
| **约 3 分钟** | 同一应用在 **Azure** 上启动（**磁盘 IO 慢一倍**：`Windows_LoadLibrary` 事件 OCI 12 秒 vs Azure 24 秒） | 同上 |
| **「a few seconds」（数秒）** | **预分配（Preallocated App）**模式：应用 24/7 常驻，用户接入**无冷启动** | Eagle 3D Streaming 官方文档 |
| 预分配模式的代价 | 「Higher infrastructure cost due to streamer machines running 24/7」「Continuous GPU and CPU usage, **even when no users are connected**」 | 同上 |

**结论：UE 打包应用从启动到可服务，量级是 1.5–3 分钟**（且强烈依赖磁盘 IO；官方建议优化 pak 文件顺序 + 保证本地 DDC 缓存）。**要压到秒级只能靠预分配/热池，代价是 GPU 空转成本。**

来源：<https://unreal2.epic-prod-us2.discourse.cloud/t/azure-unreal-engine/2680356>、<https://docs.eagle3dstreaming.com/wiki/preallocated-app>

> **未找到权威来源**：**没有官方「UE 冷启动 N 秒」的承诺值。** 1.5–3 分钟来自一个具体案例（且是 Editor 而非打包版）。打包版 + pak 优化 + 本地 DDC 理论上更快，**必须实测**。腾讯云 CAR 自述「每分钟最多扩 50 个并发，排队机制内置」（<https://cloud.tencent.cn/developer/article/2691721>）——这是调度层扩容速率，不是单实例冷启动时间。

---

## 7. 国内合规相关

### 结论（1–3 行）

**实时音视频流本身不需要「网络文化经营许可证」**——贵州省文旅厅 2026-01 红头文件明确「**聊天类**等直播不属于网络表演，不属于《网络文化经营许可证》审批范围，无需申请办理」；但**数字人场景有一条独立的、极重要的新规**：《数字虚拟人信息服务管理办法（征求意见稿）》（2026-04-03 发布，意见截止 2026-05-06）要求**全程持续显示「数字人」标识**、**使用自然人敏感个人信息建模须取得单独同意且撤回后须删除并注销数字人**、**禁止向未成年人提供虚拟亲属/虚拟伴侣服务**。**把用户面部生物特征上传云端处理**：《个人信息保护法》第 28/29 条要求**单独同意**，第 55/56 条要求**事前个人信息保护影响评估且报告至少保存 3 年**；《人脸识别技术应用安全管理办法》（2025-06-01 施行）第 8 条更硬：「**除法律、行政法规另有规定或者取得个人单独同意外，人脸信息应当存储于人脸识别设备内，不得通过互联网对外传输**」，第 15 条还规定**存储量达 10 万人须 30 个工作日内向省级以上网信部门备案**。

### 依据与来源

**7.1 实时音视频流的资质**

**(a) 网络文化经营许可证（文网文）——聊天类/康养类不需要**

贵州省文化和旅游厅《关于规范〈网络文化经营许可证〉适用范围的函》（2026-01-14）原文：

> 「七、**电商类、教育类、医疗类、培训类、金融类、旅游类、美食类、体育类、聊天类等直播不属于网络表演，不属于《网络文化经营许可证》审批范围，无需申请办理《网络文化经营许可证》。**」
> 「八、在已取得网络文化许可的平台上开展网络表演活动的企业，无需再申请办理网络文化经营许可证。」

该函同时明确审批范围为六类：**网络表演、网络音乐、网络演出剧（节）目、网络艺术品、网络动漫和展览、比赛活动**；并定义「网络表演」为「**网络表演者以现场进行的文艺表演活动等为主要内容**…实时传播或者以音视频形式上载传播」。

→ **养老康养 App 的数字人助手，是功能型交互，不是「文艺表演活动」，不落在文网文范围。** 但**若数字人做才艺表演类直播，就要走文网文**。

来源：<https://whhly.guizhou.gov.cn/xwzx/tzgg/202601/t20260115_89301680.html>

**(b) 信息网络传播视听节目许可证（视听许可证 / AVSP）**

**未找到权威来源**给出「民营企业做实时音视频交互是否需要 AVSP」的确定答案。检索到的均是律所/咨询机构解读（如 <https://www.miibt.com/show-81-8318-1.html>、<https://www.huiyelaw.com/news-1639.html>），**权威性不足，不作结论**。可参考的官方文件：《互联网等信息网络传播视听节目管理办法》<https://www.gov.cn/zhengce/202507/content_7030155.htm>。**这一条建议直接向属地广电/网信部门书面咨询。**

**(c) ICP 备案 / ICP 经营许可证**

- **ICP 备案**（非经营性）：所有在中国境内提供互联网信息服务的网站/App 都需要 — 这是基础合规，**未找到权威来源**给出「App 备案」与「网站备案」的差异细节，建议按工信部现行 App 备案要求执行。
- **ICP 经营许可证**（增值电信业务经营许可证）：适用于**经营性**（向用户收费）的互联网信息服务。**具体到「数字人会员订阅」是否触发，未找到权威来源**，建议按经营性/非经营性边界向属地通信管理局确认。

**(d) 数字人直播/网络表演的专门规定**

**这是本节最重要的一条新规：**

**《数字虚拟人信息服务管理办法（征求意见稿）》**
- 发布机关：**国家互联网信息办公室**
- 发布日期：**2026 年 4 月 3 日**
- 意见反馈截止：**2026 年 5 月 6 日**（邮箱 `shuziren@cac.gov.cn`）
- 结构：**五章二十七条**（总则、权益保护、服务规范、监督检查和法律责任、附则）
- 施行日期：**第二十七条 空白「自 2026 年 月 日起施行」——即尚未确定施行日，仍处征求意见阶段**

**定义（第二十五条）：**

> 「数字虚拟人，是指存在于非物理世界，利用图形学、数字图像处理或者人工智能等技术，**借助真人驱动或者计算驱动，模拟人类外貌，具备声音、行为、交互能力或者性格等特征的虚拟数字形象**。」
> 「**真人驱动数字虚拟人**，是指通过动作捕捉技术**实时映射真人表情、动作和语音**的虚拟数字形象。」

→ **「用户面部驱动数字人」正好命中「真人驱动数字虚拟人」的定义。**

**四类责任主体（官方解读确认）：** 数字虚拟人信息服务**技术支持者**、**服务提供者**、**服务使用者**、**传播平台**。官方解读特别指出：「**首次提出了在数字虚拟人服务内容生产和运作管理中发挥重要作用的服务使用者的概念**，强调服务使用者需要在数字虚拟人身份告知、数据处理、内容审核、应急响应等方面**承担与服务提供者相同的责任义务**」——即**云渲染/数字人技术供应商（技术支持者）也被纳入监管**。

**对企业最关键的几条：**

| 条款 | 要求 |
|---|---|
| **第七条** | 使用自然人**敏感个人信息**用于建模、形象生成、场景构建，须**取得单独同意**并显著、清晰易懂、真实准确完整告知处理目的/必要性/对个人权益的影响；**未满 14 周岁须监护人单独同意**；**个人撤回同意后须删除个人信息消除影响，不得以任何形式留存或用于其他用途，除当事人另有约定外还应当注销数字虚拟人** |
| **第八条** | **未经特定自然人同意，不得提供足以识别特定自然人身份的数字虚拟人服务**，包括使用他人有一定社会知名度的笔名/艺名/网名/译名/字号/姓名简称，以及**使用与特定自然人高度相似的肖像或者声音** |
| **第十条** | **禁止诱导未成年人沉迷**；**不得向未成年人提供虚拟亲属、虚拟伴侣等虚拟亲密关系**、诱导过度消费、诱导信教的数字虚拟人服务；不得含可能引发未成年人模仿不安全行为等影响身心健康的信息 |
| **第十三条** | 「**自数字虚拟人服务开始，数字虚拟人服务提供者、服务使用者及提供网络信息内容传播服务的服务提供者应当在数字虚拟人展示区域全程持续显示含有『数字人』字样的显著提示标识，并符合国家人工智能生成合成内容标识有关规定**」 |
| 第十一条(五) | 不得「按法律、行政法规要求提供真实身份信息时，**利用数字虚拟人绕过人脸识别、语音识别等身份认证机制**」 |
| 第十一条(六) | 不得侵害**真人驱动数字虚拟人的真人驱动方**个人信息、自主择业等合法权益 |
| 第十五条 | 建立安全风险监测、预警、应急处置、**防沉迷提示**机制；发现违法活动及时身份动态核验、警示、限制功能、终止服务；**重大风险立即暂停或终止服务、注销数字虚拟人并消除影响** |
| 第十六条 | 服务提供者应与**技术支持者、服务使用者签订服务协议**，明确内容安全与数据收集/使用/存储规范 |
| 第二十一条 | 具有舆论属性或社会动员能力的，按《互联网信息服务算法推荐管理规定》履行**算法备案**；**技术支持者参照执行** |
| 第二十二条 | 具有舆论属性或社会动员能力的，按国家有关规定开展**安全评估** |
| 第二十六条 | 从事**医疗**、金融、新闻出版、电影等领域活动另有规定的，**应当同时符合其规定** |
| 第二十四条 | 罚则：警告、通报批评、限期改正；拒不改正或情节严重，责令停止提供相关服务，可并处 **1 万–10 万元**罚款；**涉及危害公民生命健康安全且有危害后果的，并处 10 万–20 万元**罚款 |

来源（全文）：<http://www.xinhuanet.com.cn/politics/20260403/f41c2154feb9429da3e0e9fa78353823/c.html>、官方解读：<http://www.fjwx.gov.cn/fg/20260407/3022005.html>、律所简报：<https://www.tahota.com/CN/article.aspx?mdid=C89553DC174781E4&KeyID=551aaac170d96078>

**配套：AI 生成内容标识**

《人工智能生成合成内容标识办法》由**四部门**联合印发，**2025 年 9 月 1 日起施行**，要求**显式标识 + 隐式标识**。

来源：<https://m.gmw.cn/2025-03/14/content_1303991453.htm>、<https://www.gov.cn/zhengce/zhengceku/202503/content_7016075.htm>（同批次政策）

**配套：《直播电商监督管理办法》**

已施行，明确**将数字人主播等生成内容纳入监管**：直播运营者使用人工智能等技术生成的人物图像、视频从事直播电商活动，应当按照国家有关规定**进行标识**，并**持续向消费者提示**；使用违法生成内容的，由**实际使用该内容的直播运营者承担责任**。

来源：<http://news.jcrb.com/jsxw/2025/202602/t20260204_7566366.html>（该页为 GBK 编码，抓取呈乱码，但标题与要点可辨；另一政策解读 PDF：<https://scjg.hld.gov.cn/zw/zfxxgk/fdzdgknr/lzyj/zcjd/202609/P020260922386044207081.pdf>）

**其他相关标准/动态：**

- 《广播电视和网络视听数字人身份标识规范》存在（百度百科条目，**正文 403 未能取回，权威性不足**）：<https://baike.baidu.com/item/广播电视和网络视听数字人身份标识规范>
- 「虚拟数字人安全技术标准」在征求意见（法治日报 2026-05-22）：<http://www.legaldaily.com.cn/IT/content/2026-05/22/content_9392655.html>
- 最高法《关于依法审理涉人工智能纠纷案件的意见》（2026-09）：<http://www.nxzfw.gov.cn/gnyw/202609/t20260908_1155113.html>

**7.2 人脸生物特征 / 敏感个人信息合规**

**(a) 是否敏感个人信息——是，PIPL 第 28 条明文列举「生物识别」**

《中华人民共和国个人信息保护法》**第二十八条**原文：

> 「敏感个人信息是一旦泄露或者非法使用，容易导致自然人的人格尊严受到侵害或者人身、财产安全受到危害的个人信息，包括**生物识别**、宗教信仰、特定身份、医疗健康、金融账户、行踪轨迹等信息，以及不满十四周岁未成年人的个人信息。
> 只有在具有**特定的目的和充分的必要性**，并采取**严格保护措施**的情形下，个人信息处理者方可处理敏感个人信息。」

→ **人脸信息属「生物识别」→ 敏感个人信息。** 注意：**「医疗健康」也在同一列举中**——康养 App 的健康档案同样是敏感个人信息，这是双重敏感。

来源：<https://www.spp.gov.cn/spp/fl/202108/t20210820_527244.shtml>（最高检门户网全文）

**(b) 具体义务——PIPL 第 29 / 30 / 55 / 56 条**

| 条款 | 原文要点 |
|---|---|
| **第二十九条** | 「处理敏感个人信息应当取得个人的**单独同意**；法律、行政法规规定处理敏感个人信息应当取得**书面同意**的，从其规定。」 |
| **第三十条** | 「个人信息处理者处理敏感个人信息的，除本法第十七条第一款规定的事项外，**还应当向个人告知处理敏感个人信息的必要性以及对个人权益的影响**。」 |
| **第五十五条** | 「有下列情形之一的，个人信息处理者应当**事前进行个人信息保护影响评估**，并对处理情况进行记录：（一）**处理敏感个人信息**；（二）利用个人信息进行自动化决策；（三）委托处理个人信息、向其他个人信息处理者提供个人信息、公开个人信息；（四）向境外提供个人信息；（五）其他对个人权益有重大影响的个人信息处理活动。」 |
| **第五十六条** | 影响评估应包括：处理目的/方式是否合法正当必要；对个人权益的影响及安全风险；保护措施是否合法有效并与风险程度相适应。「个人信息保护影响评估报告和处理情况记录应当**至少保存三年**。」 |
| **第十九条** | 「除法律、行政法规另有规定外，个人信息的**保存期限应当为实现处理目的所必要的最短时间**。」 |
| **第二十三条** | 向其他处理者提供个人信息，须告知接收方名称/联系方式/处理目的方式种类，并取得**单独同意**。 |
| **第五十一条** | 应采取内部管理制度、分类管理、加密/去标识化、操作权限与培训、安全事件应急预案等措施。 |
| **第五十二条** | 处理个人信息达到国家网信部门规定数量的，应**指定个人信息保护负责人**，公开其联系方式并报送履职部门。 |
| **第五十四条** | 「个人信息处理者应当**定期**对其处理个人信息遵守法律、行政法规的情况进行**合规审计**。」 |
| **第六十六条（罚则）** | 一般：责令改正、警告、没收违法所得、责令暂停或终止提供服务，拒不改正并处 **100 万元以下**罚款，直接责任人 **1 万–10 万元**；**情节严重**：省级以上部门责令改正、没收违法所得，并处 **5,000 万元以下或上一年度营业额 5% 以下**罚款，可责令暂停相关业务或停业整顿、吊销业务许可或营业执照，直接责任人 **10 万–100 万元**，并可**禁止一定期限内担任董监高及个人信息保护负责人**。 |

来源：<https://www.spp.gov.cn/spp/fl/202108/t20210820_527244.shtml>

**(c)《人脸识别技术应用安全管理办法》——最关键的一条**

- 发布机关：**国家网信办 + 公安部**，**令第 19 号**
- 成文日期：**2025 年 3 月 13 日**；**施行日期：2025 年 6 月 1 日**（第二十条）
- 制定依据：网络安全法、数据安全法、个人信息保护法、网络数据安全管理条例

**与会话式数字人直接冲突的条款：**

| 条款 | 原文要点（**对本项目最重要**） |
|---|---|
| **第八条** | 「**除法律、行政法规另有规定或者取得个人单独同意外，人脸信息应当存储于人脸识别设备内，不得通过互联网对外传输。**除法律、行政法规另有规定外，人脸信息的**保存期限不得超过实现处理目的所必需的最短时间**。」 |
| **第四条** | 「应用人脸识别技术处理人脸信息，应当具有**特定的目的和充分的必要性**，采取**对个人权益影响最小的方式**，并实施严格保护措施。」 |
| **第五条** | 处理前须以显著方式、清晰易懂语言告知：处理者名称/联系方式；**处理目的、处理方式、人脸信息保存期限**；**必要性以及对个人权益的影响**；个人行使权利的方式和程序。**「处理残疾人、老年人人脸信息的，还应当符合国家有关无障碍环境建设的规定。」** |
| **第六条** | 「基于个人同意处理人脸信息的，应当取得个人在**充分知情的前提下自愿、明确作出的单独同意**。」个人**有权撤回同意**，处理者应提供便捷撤回方式。 |
| **第七条** | **不满十四周岁未成年人**须取得父母或其他监护人同意，并**制定专门处理规则**。 |
| **第九条** | 「应用人脸识别技术处理人脸信息，应当**事前进行个人信息保护影响评估**，并对处理情况进行记录。」评估含四项内容（目的/方式合法正当必要；对个人权益影响及降低措施是否有效；泄露篡改丢失毁损或被非法获取出售使用的风险及可能危害；保护措施是否合法有效与风险相适应）。**「评估报告和处理情况记录应当至少保存 3 年。」** 目的/方式变化或发生重大安全事件的，**应当重新评估**。 |
| **第十条** | 「实现相同目的或者达到同等业务要求，存在其他非人脸识别技术方式的，**不得将人脸识别技术作为唯一验证方式**。个人不同意通过人脸信息进行身份验证的，应当提供其他合理、便捷的方式。」 |
| **第十二条** | 「任何组织和个人**不得以办理业务、提升服务质量等为由，误导、欺诈、胁迫个人接受人脸识别技术验证个人身份**。」 |
| **第十四条** | 系统应采取**数据加密、安全审计、访问控制、授权管理、入侵检测和防御**等措施；涉及等保/关基的按规定履行义务。 |
| **第十五条** | 「个人信息处理者应当在应用人脸识别技术处理的人脸信息**存储数量达到 10 万人之日起 30 个工作日内向所在地省级以上网信部门履行备案手续**。」备案材料含：处理者基本情况、**处理目的和处理方式**、**存储数量和安全保护措施**、**处理规则和操作规程**、**个人信息保护影响评估报告**。实质性变更 30 个工作日内变更备案；终止的 30 个工作日内注销备案。 |

**关键解读（务必注意术语边界）**：第十九条**定义**部分明确区分了「**人脸识别技术**」「**验证个人身份**（1:1 比对）」「**辨识特定个人**（1:多比对）」与「**人脸识别设备**」。**本办法的规制对象是「以人脸信息作为识别个体身份的个体生物特征识别技术」**（第十九条(三)），第二条还排除了「**为从事人脸识别技术研发、算法训练活动**」。

→ 本项目做的是**表情驱动（面部动作捕捉）**，目的**不是身份识别**。**这是一个非常关键的抗辩点**：严格按第十九条(三)的定义，「表情驱动」未必落入本办法的「人脸识别技术」。但：

1. **人脸信息本身仍是 PIPL 第 28 条的敏感个人信息（生物识别）**，PIPL 的义务**100% 适用**，与是否用于识别无关；
2. **第八条「人脸信息应当存储于人脸识别设备内，不得通过互联网对外传输」** 的文本主语是「人脸信息」而非「识别用途」——**解释上存在被适用于云上传的显著风险**，尤其对老年人这类需要强化保护的人群（第五条第 3 款专门点名老年人）；
3. 办法**未直接规定「不得上云」**，但**「不得通过互联网对外传输」的例外只有「法律、行政法规另有规定」或「取得个人单独同意」两条** —— 即**云上传必须建立在有效单独同意之上**，且这仍不足以免除 PIPL 的影响评估与最小化义务。

**结论**：把老人面部视频上传云端处理，属于**高风险区**，不是「拿个同意书就行」。**最稳妥的工程答案是端侧处理**（这也与仓库既定决策「3D 渲染只做端侧方案 A」一致）。

来源（全文）：<https://www.gov.cn/zhengce/zhengceku/202503/content_7016075.htm>

**(d) GB/T 35273《信息安全技术 个人信息安全规范》**

标准号 **ICS 35.030**，TC260 页面可查：<https://www.tc260.org.cn/upload/2025-03-15/1742009439794081593.pdf>（**抓取失败，未直读**）。该标准属推荐性国标，含**个人生物识别信息**的收集、存储、共享要求（例如生物识别信息原则上应与身份信息分开存储）。**具体条款号与文本未找到权威一手来源，不作引述。**

**(e) 是否有「必须本地存储/端侧处理」的强制规则**

- 《人脸识别技术应用安全管理办法》**第八条**是当前最强的相关条款：「人脸信息应当存储于人脸识别设备内，**不得通过互联网对外传输**」，例外为「法律、行政法规另有规定」或「取得个人单独同意」。→ **不是绝对禁止上云，但默认禁止，需单独同意方能例外。**
- **未找到**任何法规明文规定「数字人面部驱动必须端侧处理」。
- 但《数字虚拟人信息服务管理办法（征求意见稿）》**第七条(二)** 规定撤回同意后须删除并不得留存，**第七条**要求对敏感个人信息取得单独同意 —— 这些与「云上传 + 留存」的架构天然紧张。

**(f)《人工智能生成合成内容标识办法》**

- 印发：**四部门**（国家网信办、工信部、公安部、广电总局）
- **施行日期：2025 年 9 月 1 日**
- 要求：**显式标识 + 隐式标识**（生成合成内容需添加可见标识，并在文件元数据中嵌入隐式标识）
- 与数字人新规呼应：《数字虚拟人信息服务管理办法（征求意见稿）》第十三条要求「**全程持续显示含有『数字人』字样的显著提示标识**」，并「符合国家人工智能生成合成内容标识有关规定」

来源：<https://m.gmw.cn/2025-03/14/content_1303991453.htm>、<https://wxb.xzdw.gov.cn/wlcb/cbgz/202509/t20250902_601378.html>（**抓取失败，仅得标题**）、<https://login.12309.gov.cn:8443/spp/tt/202503/t20250314_690508.shtml>

---

## 对「给养老康养 App 做数字人」最关键的 3 个约束

### 约束一：把老人面部视频上传云端，在国内是**高风险合规动作**，不是「拿个同意书就行」

「人脸信息」= PIPL 第 28 条的**敏感个人信息（生物识别）**，需**单独同意**（第 29 条）+ 事前**个人信息保护影响评估**且报告**至少保存 3 年**（第 55/56 条）。更硬的是《人脸识别技术应用安全管理办法》（2025-06-01 施行）**第八条**：「**除法律、行政法规另有规定或者取得个人单独同意外，人脸信息应当存储于人脸识别设备内，不得通过互联网对外传输**」——**默认禁止上云，仅两条例外**。同时第五条第 3 款**专门点名老年人**（「处理残疾人、老年人人脸信息的，还应当符合国家有关无障碍环境建设的规定」），存储量达 **10 万人**须 30 个工作日内向**省级以上网信部门备案**（第十五条）。叠加《数字虚拟人信息服务管理办法（征求意见稿）》第七条（撤回同意后**须删除并注销数字人**）。

→ **端侧处理不是性能取舍，是合规主路径。** 这一条独立于成本与技术，且和仓库既定决策「只做端侧方案 A」正好一致——**这个决策从合规角度是被强支持的，不要因为云渲染效果好而动摇**。

### 约束二：UE5 + MetaHuman 云渲染的**实时面部驱动在 Linux 上跑不了**，且单卡并发极低，成本结构不成立

三重硬约束叠在一起：

1. **MetaHuman Animator 不支持 Linux**（官方：「currently not supported on macOS and Linux」；「Realtime Animation from mono video or audio: only supported on Windows and macOS」；5.7 才刚把 **MetaHuman Creator** 搬到 Linux，**Animator 的 Linux 支持仍是 planned**）→ 云端要么用 Windows GPU 实例（更贵、许可更复杂），要么放弃官方实时驱动方案。
2. **单卡并发低**：Epic 工程师的实战口径是「**多数人最终 1 台机器 1 个 UE 实例**」，好一点「单机 4 实例」；消费级卡还有 **NVENC 12 路（Epic 文档写 8 路）编码会话硬上限**，超了自动掉软件编码 → 直接烧 CPU。而 **MetaHuman Cinematic 装配单角色就占 1–2 GB 内存/显存**（官方数字），groom 还有 **~16 MB/角色且全量常驻、无流式卸载**（Epic 论坛实测 + Epic 工程师确认「no plan for cards to have streaming pool」）。
3. **成本**：每路每小时 **¥1–8**（PaaS 按路报价：天翼云 ¥2.5/6.4/7.8；腾讯云 CAR 包月折合 ¥0.73–1.33），加上 **1.5–3 分钟的冷启动**（要靠预分配/热池压到秒级，代价是 GPU 24/7 空转）。面向康养场景的用户规模与付费能力，这个单位经济**很难成立**。

→ 云渲染方案在此场景下**技术受阻（Linux/Animator）+ 成本不成立 + 合规劣化**，三条同时不成立。**仓库既定的「不做云渲染 B」是被充分支持的。**

### 约束三：新规把「数字人」变成受专门监管的品类，三条红线直接冲着康养场景来

《数字虚拟人信息服务管理办法（征求意见稿）》（2026-04-03，意见截止 2026-05-06）目前**仍是征求意见稿、施行日期空白**，但方向明确、且官方解读（国家互联网应急中心副主任撰稿）已定调，**应按生效标准提前设计**：

1. **强制身份告知**（第十三条）：「**全程持续显示含有『数字人』字样的显著提示标识**」——产品 UI 必须有常驻的「数字人」角标，不能只在首次进入时弹一次。这对适老化界面的视觉设计是新增的硬约束。
2. **严禁「虚拟亲属/虚拟伴侣」**（第十条）：「**不得向未成年人提供虚拟亲属、虚拟伴侣等虚拟亲密关系**、诱导过度消费…的数字虚拟人服务」。**注意文本主体是「未成年人」**，但同一逻辑在老人身上危险性更高——本项目自身的伦理红线「**不模拟已故亲属、不冒充真人**」与该条款同源。**「数字人陪伴老人」这个产品叙事必须与「虚拟亲属」严格切割**：不能叫「闺女」「老伴」，不能让老人产生「这是真人/这是我逝去的亲人」的认知。
3. **身份同一性风险**（第八条）：「**未经特定自然人同意，不得提供足以识别特定自然人身份的数字虚拟人服务**」，明确包括「使用与特定自然人**高度相似的肖像或者声音**」。→ **给老人定制「像某位家人」的数字人形象/声音，必须取得该特定自然人的同意**（不是老人同意就行）。另外第十一条(六)规定不得「侵害**真人驱动数字虚拟人的真人驱动方**个人信息、自主择业等合法权益」——若用真人（如子女）的脸驱动数字人给老人看，该真人的权益受专门保护。
4. 附加成本：第十五条要求建立**防沉迷提示**机制与内容导向管理制度；第二十一条要求**算法备案**（具有舆论属性或社会动员能力的，**技术支持者参照执行**）；第二十四条罚则中，**涉及危害公民生命健康安全且有危害后果的，罚款升至 10 万–20 万元**；第二十六条特别提示**医疗等领域另有规定时须同时符合**——与仓库既定的「不做诊断、只做生活提醒与依从性管理」医疗边界要求一致，**这条边界不能松**。

→ **行动建议**：把「常驻数字人标识」「禁止虚拟亲属叙事」「定制形象/声音须取得该自然人单独同意」「防沉迷机制」四条**作为产品设计约束前置**，而不是等法规生效后再补。

---

## 附：本报告中标注「未找到权威来源」的条目汇总

1. 三角面数（官方只公开顶点数）
2. 「1000+ 骨骼」说法（官方最高 713 joints @ LOD0）
3. 「ARKit 52 blendshape」的**官方**计数表述（官方只说「ARKit Face」，52 是第三方通称）
4. 皮肤 SSS shader 指令数/渲染耗时
5. 眼球材质复杂度量化
6. NVIDIA Audio2Face ↔ MetaHuman 的官方集成方案与确切商用授权条款
7. 「禁止把 MetaHuman 作为服务提供给第三方」的条款（未发现此类条款）
8. 官方/权威第三方对「像素流 SaaS 是否需 UE 席位许可或触发 royalty」的直接定性（仅有 Non-Engine Products 条款的间接推导）
9. 单卡 720p30 的具体并发路数
10. 同区域/公网端到端延迟的权威第三方式测量（仅有官方编码耗时 + 厂商自述 50–200ms / 60–80ms）
11. 民营企业做实时音视频交互是否需 AVSP（视听许可证）的确定答案
12. GB/T 35273 中生物识别信息条款的具体条文（标准原文未取回）
13. 阿里云/AWS 的**官方一手**定价（AWS 用三个第三方聚合站，阿里云用开发者社区投稿汇总）
14. 官方「UE 冷启动 N 秒」承诺值（1.5–3 分钟来自单个实测案例，且是 Editor 而非打包版）
15. `https://www.unrealengine.com/eula/mhc` 正文（抓取 HTTP 403；AI 相关禁止条款 (j) 为社区转引）
16. MetaHuman 官方 license FAQ 正文（`www.metahuman.com/license` 为 JS 渲染，抓取仅得标题）

## 附：本次调研中抓取失败/受限的链接

| URL | 状态 |
|---|---|
| <https://www.unrealengine.com/eula/mhc?lang=en-US> | HTTP 403 |
| <https://www.metahuman.com/license>、<https://www.metahuman.com/en-US/license> | HTTP 200 但正文 JS 渲染，仅得标题 |
| <https://www.strayspark.studio/blog/metahuman-2026-web-app-shutdown-migration-guide> | HTTP 403（Cloudflare） |
| <https://www.strayspark.studio/blog/pixel-streaming-ue5-cloud-gaming-demo> | HTTP 403 |
| <https://baike.baidu.com/item/广播电视和网络视听数字人身份标识规范> | HTTP 403（百度安全验证） |
| <https://github.com/smorchj/metahuman-to-glb> | fetch failed |
| <https://www.tc260.org.cn/upload/2025-03-15/1742009439794081593.pdf>（GB/T 35273） | 未取回 |
| <http://news.jcrb.com/jsxw/2025/202602/t20260204_7566366.html> | GBK 编码，呈乱码（要点可辨） |
| <https://wxb.xzdw.gov.cn/wlcb/cbgz/202509/t20250902_601378.html> | unsupported content type |

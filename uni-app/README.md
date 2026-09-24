# 比邻AI · uni-app 工程

面向老人的亲友陪伴康养 App —— 适老化高保真原型的 uni-app 实现。

设计源：`../比邻AI_UI设计流程与提示词.md` ＋ `../prototype/`（HTML/CSS 原型）。
本工程是该原型的 uni-app 落地版本，**零 npm 依赖**，HBuilderX 直接打开即可运行。

---

## 一、快速运行

### HBuilderX（推荐，零依赖）
1. HBuilderX → 文件 → 打开目录 → 选择本目录 `uni-app/`
2. 运行 → 运行到浏览器 / 运行到手机或模拟器 / 运行到小程序模拟器

无需 `npm install`。工程不含任何第三方运行时依赖，只用 uni-app 内置能力 + Vue 3。

### uni-app CLI
本目录就是标准 uni-app 源码结构（`pages.json` / `manifest.json` / `main.js` / `App.vue` / `uni.scss`），
可直接作为任意 uni-app CLI 工程（Vite 或 vue-cli 版）的 `src/` 使用：

```bash
npx degit dcloudio/uni-preset-vue#vite my-app
# 把本目录内容覆盖到 my-app/src/
cd my-app && npm i && npm run dev:h5
```

> 注意：`manifest.json` 里 `appid` 为空，发布到微信小程序或 App 前需在 HBuilderX 中重新获取。

---

## 二、目录结构

```
uni-app/
├── pages.json                 # 路由 + easycom 规则 + globalStyle
├── manifest.json              # 应用标识、平台配置（vueVersion: 3）
├── main.js                    # createSSRApp 入口
├── App.vue                    # ★ 设计 Token（CSS 变量）+ 全局基础样式
├── uni.scss                   # Token 的 SCSS 变量镜像（编译期计算用）
├── common/
│   ├── tokens.js              # Token 的 JS 镜像（供逻辑层读取）
│   ├── store.js               # 轻量全局状态（大字体模式 / 当前角色）+ 本地持久化
│   ├── icons.js               # 26 个 SVG 图标（内联 data URI，零图片资源）
│   └── base64.js              # data URI 编码工具
├── components/                # 8 个 bl-* 业务组件，经 easycom 自动注册
│   ├── bl-icon/               # SVG 图标（name + color + size）
│   ├── bl-navbar/             # 自绘导航栏（返回 / 标题 / 右侧动作）
│   ├── bl-tabbar/             # 自绘 TabBar（对话 · 日程 · 我的）
│   ├── bl-switch/             # 适老化开关（加大触控区）
│   ├── bl-slider/             # 数字人捏脸滑杆
│   ├── bl-chat-bubble/        # 聊天气泡（文本 / 语音波形）
│   ├── bl-plan-card/          # 日程计划卡
│   └── bl-role-card/          # 智能体角色卡（含选中态）
└── pages/                     # 11 个页面（与原型 11 页一一对应）
    ├── splash/                # ① 启动页
    ├── chats/                 # ② 会话列表
    ├── empty/                 # ⑩ 空态 / 首次使用
    ├── chat-detail/           # ③ 聊天详情
    ├── vision/                # ④ 视频通话
    ├── plans/                 # ⑤ 今日计划
    ├── calendar/              # ⑥ 日历
    ├── me/                    # ⑦ 我的
    ├── roles/                 # ⑧ 角色选择
    ├── face/                  # ⑨ 数字人 3D 捏脸
    └── tokens/                # ⑪ 设计规范速查
```

---

## 三、设计 Token —— 唯一数据源

Token 以 **4 份镜像**存在，改一处需同步其余，**核对基准是 `../prototype/tokens.json`**：

| 用途 | 位置 | 形态 |
|---|---|---|
| 运行时样式（主） | `App.vue` 的 `page { }` | CSS 自定义属性 `--bl-*` |
| 逻辑层读取 | `common/tokens.js` | JS 对象 |
| 编译期计算 | `uni.scss` | SCSS 变量 `$bl-*` |
| 原始设计源 | `../prototype/tokens.json` | JSON |

对应关系示例：

| 设计稿 | CSS 变量 | tokens.js | uni.scss | 原型 |
|---|---|---|---|---|
| 主色 `#07C160` | `--bl-primary` | `color.primary` | `$bl-primary` | `--color-primary` |
| 正文 `16px` | `--bl-font-body: 32rpx` | `fontSize.body: 32` | `$bl-font-body` | `--font-body: 16px` |
| 触控 `48px` | `--bl-touch: 96rpx` | `size.touch: 96` | `$bl-touch` | `--size-touch: 48px` |
| 列表行 `56px` | `--bl-row: 112rpx` | `size.row: 112` | `$bl-row` | `--size-row: 56px` |
| TabBar `56px` | `--bl-tabbar: 112rpx` | `size.tabbar: 112` | `$bl-tabbar` | `--size-tabbar: 56px` |
| 头像 `52px` | `--bl-avatar: 104rpx` | `size.avatar: 104` | `$bl-avatar` | `--size-avatar: 52px` |

### rpx 换算规则
设计稿按 **375px** 宽出图，uni-app 的 `750rpx = 屏幕宽`，因此：

```
1px（设计稿） = 2rpx        例：48px 触控 → 96rpx
```

- 正文最小 16px → **32rpx**（适老化底线，勿低于此值）
- 触控最小 48px → **96rpx**
- 禁用 px 硬编码尺寸，一律走 Token 变量

---

## 四、大字体模式（适老化核心）

规范里的「+ 大字体变体」，实现方式与原型完全一致：**只覆盖 Token，不动组件**。

- `App.vue` 里 `.bl-large { --bl-font-body: 40rpx; --bl-touch: 112rpx; --bl-row: 128rpx; ... }`
- 每个页面根节点绑定 `:class="{ 'bl-large': settings.largeFont }"`
- 开关在「我的 → 大字体模式」，`store.js` 用 `uni.setStorageSync('bl_large_font')` 持久化，
  `App.vue` 的 `onLaunch` 通过 `initSettings()` 读回

字号 / 触控尺寸提升：

| Token | 标准 | 大字体 |
|---|---|---|
| caption | 28rpx (14px) | 36rpx (18px) |
| body | 32rpx (16px) | 40rpx (20px) |
| title | 40rpx (20px) | 48rpx (24px) |
| display | 48rpx (24px) | 60rpx (30px) |
| huge | 56rpx (28px) | 68rpx (34px) |
| touch | 96rpx (48px) | 112rpx (56px) |
| row | 112rpx (56px) | 128rpx (64px) |
| avatar | 104rpx (52px) | 120rpx (60px) |

> ⚠️ 写新页面时**务必用 `var(--bl-*)` 而非硬编码 rpx**，否则该元素不会跟随大字体模式放大。
> 例如会话列表头像必须写 `width: var(--bl-avatar)`；写成 `104rpx` 会固定不变。

---

## 五、导航实现说明

`pages.json` 中**没有配置原生 `tabBar`**，全部页面 `navigationStyle: custom`：

- TabBar 由 `bl-tabbar` 自绘，切换用 `uni.reLaunch` 清栈，避免页面无限堆叠
- 导航栏由 `bl-navbar` 自绘，返回用 `uni.navigateBack`
- 好处：导航栏与 TabBar 同样受大字体 Token 控制，原生 tabBar 做不到

---

## 六、与 HTML 原型的差异

| 项 | 说明 |
|---|---|
| 页面数 | 原型 11 页 → 本工程 **11 页，已全部迁移** |
| 两个演示页的入口 | 原型用顶部工具栏切页；本工程走真实导航：⑪ 设计规范 = 我的 → 设计规范；⑩ 空态 = 设计规范 →「空态 / 首次使用」那一行 |
| 规范表实现 | 原型用 `<table>`，首列会被挤成「正文字 / 号」；本工程改用 flex 行，首列不再被压缩 |
| 图标 | 原型用外链/内联 SVG；本工程 26 个图标内联为 data URI，**零图片资源** |
| 状态管理 | 原型用全局变量；本工程用 `common/store.js`（`reactive`，不引入 Pinia） |


---

## 七、自检方式（可选）

若要脱离 HBuilderX 校验样式，可用 Vue SFC 编译器做离屏渲染：

- 用 `@vue/compiler-sfc` 的 `compileScript({ inlineTemplate: true })` 编译 `.vue`
- `isCustomElement` 放行 `view` / `scroll-view` / `image` / `bl-*` 等标签
- 渲染前把 `rpx` 按 `÷2` 换成 `px`、把 `page {` 换成 `:root, page, html, body {`
- 用 `createSSRApp` + `vue/server-renderer` 出 HTML，再用无头浏览器截图

> 离屏渲染里 `<switch>` `<slider>` 是未知标签会显示空白，`<image>` 的 SVG data URI 可能不解析 ——
> 这是校验环境限制，**真机 / 模拟器 / HBuilderX 内置浏览器均正常**。

截图存于 `../_shots/u3_*.png`（标准模式）与 `../_shots/u3L_*.png`（大字体模式）；
11 页总览见 `../_shots/_u3_sheet.png` 与 `../_shots/_u3L_sheet.png`。
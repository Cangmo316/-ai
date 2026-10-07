# 打包成安装包（Android APK）

## 现状

打包所需的**代码侧配置已经全部配好**，剩下的只有两件必须由你账号完成的事。

## 已经配好的

| 项 | 位置 | 内容 |
|---|---|---|
| 应用名称 / 版本 | `manifest.json` | 比邻AI · 1.0.0 (100) |
| Android 包名 | `manifest.json` | `com.bilin.ai` |
| 最低 / 目标 SDK | `manifest.json` | 21 / 34（覆盖 Android 5.0+） |
| CPU 架构 | `manifest.json` | arm64-v8a、armeabi-v7a |
| **权限** | `manifest.json` | 网络、录音、相机、读写媒体、震动（共 11 条，对应语音输入 / 摄像头 / 改头像） |
| **图标** | `static/app/` | 72 / 96 / 144 / 192 四档 |
| **启动图** | `static/app/` | 480×800 / 720×1280 / 1080×1920 三档 |
| 原生模块 | `manifest.json` | Push、Camera、Record |
| 打包参数 | `pack-configure.json` | 云打包 / 安心打包 / 混淆都已开启 |

图标由 `tools` 脚本从品牌印记（`common/icons.js` 的 `INK_BRAND`）生成，
不是手工切图——8 个尺寸手工做必然漏，而且从矢量生成才不会走样。

## 还差两件（只能你做）

### 1. 申请 DCloud appid（免费）

1. 打开 <https://dev.dcloud.net.cn/>，用你的账号登录（HBuilderX 里存的是 `1684863285@qq.com`）
2. 「应用」→「创建应用」→ 选 **uni-app**，名称填 `比邻AI`
3. 创建后会得到一个形如 `__UNI__A1B2C3D` 的 **AppID**

拿到后，把它填到两个地方：

```
uni-app/manifest.json          →  "appid": "__UNI__A1B2C3D"
uni-app/pack-configure.json    →  "appid": "__UNI__A1B2C3D"
```

### 2. 在 HBuilderX 里登录同一个账号

**菜单「工具 → 登录」**（或右上角头像）。云打包是按账号扣次数的，
不登录跑不了；免费额度用完需要在 DCloud 后台购买。

## 然后就可以打包了

告诉我 appid、并确认 HBuilderX 已登录，我执行：

```
HBuilderX\cli.exe pack \
  --project "E:\比邻AI\uni-app" \
  --platform android \
  --config "E:\比邻AI\uni-app\pack-configure.json" \
  --safemode true \
  --isconfusion true
```

产物（APK）会由 HBuilderX 输出，我再把它装到你手机上验证。

## 关于签名证书

`pack-configure.json` 里默认留了**云证书**路径（把 `certalias` / `certpassword` /
`storepassword` 三行删掉即可，DCloud 会发一个公共测试证书）。

- **自己测试用** → 云证书就够
- **要上架应用商店** → 必须自有证书，用 `keytool` 生成：

```
keytool -genkey -alias bilin -keyalg RSA -keysize 2048 -validity 36500 \
  -keystore bilin.keystore
```

生成后把三个值填回 `pack-configure.json`。**证书丢了就再也无法更新已上架的应用**，
一定要备份。

## 一个要提醒的体积问题

`static/avatar/` 下有 **两个** 模型：

```
QDoctor_60k.glb      38.78 MB   ← 代码里实际用的
QDoctor_hires.glb   306.24 MB   ← 只有本地看效果用，已被 .gitignore
```

打包会**把整个 static 目录打进包里**，所以现在打出来的 APK 会白带 306 MB。
打包前应当把它临时移走（它本来就不参与运行）：

```powershell
Move-Item uni-app\static\avatar\QDoctor_hires.glb E:\比邻AI\3D建模\04_Q版男医_高清\
```

要我来做这一步的话说一声。

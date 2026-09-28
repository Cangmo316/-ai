# 比邻AI · 家人端（最小版）

给子女/康复师用的**计划确认台**。它只做三件事：

1. **看**：待确认的计划（**含依据**：这条是照哪份指南来的）、当前生效计划与打卡、完成率、计划历史
2. **定**：确认（→ 生效）/ 驳回 / 生成新计划 / 转入调整
3. **查**：提醒到底发出去没有（区分"发了但他没做"与"根本没送到"）

**为什么产品上必须有它**：康养计划是"agent 生成 → **家属确认后生效**"（设计方案 §3.0 硬约束）。
没有这个页面，确认闸门只能用 curl 或 `npm run seed` 驱动。

## 怎么打开

二选一（都需要先把后端跑起来）：

```powershell
# ① 用 mock（不用 Python 环境，最快）
node tools/mock-server.mjs
# 浏览器打开 http://127.0.0.1:8787/family/

# ② 用真实服务端（推荐，能验证真实话术润色与知识库依据）
cd server; .\.venv\Scripts\python.exe run.py
# 浏览器打开 http://127.0.0.1:8000/family/
```

页面顶部填「后端地址」与「访问 token」（服务端 `AUTH_MODE=required` 时必须填 `API_TOKENS` 里的一串），
点连接即可。两个值都会存在浏览器本地，下次打开自动带上。

> ⚠️ 直接双击 `family/index.html` 打开**不行**：它用 ES module 加载 `uni-app/api/` 那一层，
> `file://` 协议下浏览器会以 CORS 为由拒绝加载模块。必须经由上面两个服务之一访问。

## 与老人端的关系

```
        ┌───────────────────────────┐
        │  uni-app/api/（唯一契约实现）│
        └───────┬───────────┬───────┘
                │           │
        老人端 App      家人端浏览器
     （uni-app/pages）  （family/）
```

家人端**不重复实现接口客户端**：`family/uni-shim.js` 给浏览器补一个最小的 `uni.request` /
`uni.getStorageSync`，然后直接 import 端侧那套 `api/plans.js`。
好处有两个：契约只有一份实现；家人端一旦跑通，反过来证明这层 api 是**前端无关**的。

## 隐私边界（刻意不做的事）

设计方案 §3.4：**子女端默认可见完成率，不可见聊天原文**。所以：

- `family/flows.js` 里**一个会话接口都没有**，并且有一条回归用例守着
  （`tools/test-family-flows.mjs` 会扫描源码，出现 `chat` 相关调用就失败）
- 想加"看聊天"，前提是先有**老人的授权与 consent 记录**（`consent_record` 还没做），
  不能顺手加

## 安全说明

- 静态页与 `/uni-app/api/*` 是**公开路径**（不需要 token）——HTML/JS 先拿到手，
  才有机会带着 token 去调接口。真正的数据接口一律要 token
- `family/` 与 `uni-app/api/` 之外的文件不会被托管（防目录穿越，已测）
- 这是**开发/内部使用**的控制台，不是面向公网的多租户后台：还没有账号体系与角色权限

## 测试

```powershell
node tools/test-family-flows.mjs   # 业务层：确认闸门、驳回、调整、完成率、隐私边界
node tools/test-family-ui.mjs      # 渲染冒烟：自带极简 DOM 垫片，跑真实渲染与点击
# 打真实服务端（会验证真实状态机与依据结构）
$env:BILIN_TEST_BASE_URL='http://127.0.0.1:8000'; $env:BILIN_TEST_API_TOKEN='你的token'
node tools/test-family-flows.mjs
```

`test-family-ui.mjs` 不能替代真浏览器验收：样式、布局、点击手感仍需人看一遍。

## 状态机速查（家属最容易被误解的一条）

| 状态 | 中文 | 还在执行吗 |
|---|---|---|
| `pending_confirm` | 等家里人确认 | ❌ 未确认不产生任何提醒 |
| `active` | 正在执行 | ✅ |
| `adjusting` | 调整中，等家里人确认 | ✅ **仍在执行**（不存在提醒真空） |
| `ended` / `rejected` | 已结束 / 家里人没同意 | ❌ |

最后一行是设计上的刻意选择（`server/app/plan/models.py` 有注释）：
确认新计划的那一刻才结束旧计划，否则"生成草稿"就会造成提醒中断。

'use strict'

/**
 * 比邻AI · uni-push 2.0 发送云函数（参考实现，需要你部署到自己的 uniCloud 空间）
 *
 * 为什么要有这个云函数（已核实官方文档）：
 *   uni-push 2.0 的服务端 SDK `uni-cloud-push` **只能跑在 uniCloud 云函数里**。
 *   自建服务器（我们的 FastAPI）想直连个推，官方文档明确要求改用老版 uni-push 1.0 的凭证体系。
 *   所以这里的做法是：FastAPI 把「cid + 标题 + 内容」POST 给这个云函数的 URL，
 *   由它调用 uniPush.sendMessage 真正发出去。**个推的 appkey/mastersecret 全程留在云函数侧，
 *   不进业务服务器**，业务侧只有一个 URL 和一个自定义 token。
 *
 * 部署步骤（详见同目录 README.md）：
 *   1. 在 HBuilderX 里新建云函数，选上 `uni-cloud-push` 扩展库（或直接上传本目录）
 *   2. 把下面的 APP_ID 换成你的 DCloud appid（形如 __UNI__XXXXXX）
 *   3. 把 TOKEN 换成一串随机字符串，并在服务端 .env 里配同一个值（UNIPUSH_TOKEN）
 *   4. 在 uniCloud 控制台把该云函数「URL 化」，把得到的地址填进服务端 .env 的 UNIPUSH_SEND_URL
 *
 * 请求体（服务端发来的）：
 *   { cid, title, content, force_notification, payload: { type, taskId, planItemId, level } }
 * 响应：
 *   成功 { code: 0, data: {...} }   失败 { code: 非0, msg: '原因' }
 */

// ⚠️ 换成你的 DCloud appid（开发者中心 → 应用 → appid）
const APP_ID = '__UNI__XXXXXX'

// ⚠️ 换成一串随机字符串，并与服务端 server/.env 的 UNIPUSH_TOKEN 保持一致
const TOKEN = process.env.UNIPUSH_TOKEN || 'please-change-this-token'

exports.main = async (event, context) => {
  // 这个 URL 是公开可访问的，所以必须校验来源；不带 token 或 token 不对直接拒绝
  const header = (context && context.headers) || {}
  const authorization = header.authorization || header.Authorization || ''
  const provided = String(authorization).replace(/^Bearer\s+/i, '').trim()
  if (!TOKEN || provided !== TOKEN) {
    return { code: 401, msg: 'unauthorized' }
  }

  const cid = String((event && event.cid) || '').trim()
  if (!cid) {
    return { code: 400, msg: 'cid is required' }
  }

  const uniPush = uniCloud.getPushManager({ appId: APP_ID })

  try {
    const result = await uniPush.sendMessage({
      push_clientid: cid,
      title: String(event.title || '比邻AI 提醒'),
      content: String(event.content || ''),
      // 在线时也创建通知栏消息：康养提醒必须"一定响"，
      // 不能因为老人恰好开着 App 就只在页面上闪一下（详见 server/app/schedule/channels.py）
      force_notification: event.force_notification !== false,
      payload: Object.assign({ type: 'reminder' }, event.payload || {})
    })
    return { code: 0, data: result }
  } catch (error) {
    // 把原始错误带回去，方便在业务服务端日志里定位（cid 失效、厂商通道没配等）
    return { code: 500, msg: (error && error.message) || String(error) }
  }
}

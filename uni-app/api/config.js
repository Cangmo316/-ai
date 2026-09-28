/**
 * 比邻AI · agent 接口层配置
 *
 * 纯 JS，无平台条件编译，可被 node 直接 import（供 tools/ 下的测试与工具复用）。
 */

/**
 * 默认后端地址。
 *
 * ⚠️ 三端各自的「本机」不是同一台机器，联调时按下面改：
 *   - HBuilderX 运行到浏览器（H5）：127.0.0.1 就是本机，默认值可直接用
 *   - 运行到 Android 模拟器：模拟器里的 127.0.0.1 指模拟器自身，需改 10.0.2.2
 *   - 运行到真机 / 微信开发者工具真机预览：需改成开发机局域网 IP，如 http://192.168.1.5:8787
 *   - 微信开发者工具：需在「详情 → 本地设置」勾选「不校验合法域名」
 *
 * 改法有两种，优先级从高到低：
 *   1) 运行期：setBaseURL('http://192.168.x.x:8787')（写入本地缓存，不用重新编译）
 *   2) 源码：直接改这个常量
 */
export const DEFAULT_BASE_URL = 'http://127.0.0.1:8787'

/** 本地缓存 key：运行期覆盖 baseURL 用 */
export const STORAGE_KEY_BASE_URL = 'bl_api_base'

/** 接口路径（与《比邻AI_项目设计方案.md》§4.3 的契约一致） */
export const ENDPOINTS = {
  chatStream: '/v1/chat/stream',
  chatSend: '/v1/chat/send',
  chatHistory: '/v1/chat/history'
}

/** 超时（ms）：首字节超时用看门狗实现，总超时只作用于非流式接口 */
export const TIMEOUT = {
  firstByte: 20000,
  total: 60000
}

/** 读取当前 baseURL（去掉结尾斜杠） */
export function getBaseURL() {
  let base = ''
  try {
    base = uni.getStorageSync(STORAGE_KEY_BASE_URL) || ''
  } catch (e) {
    base = ''
  }
  return String(base || DEFAULT_BASE_URL).replace(/\/+$/, '')
}

/** 运行期切换 baseURL（写本地缓存，下次启动仍生效） */
export function setBaseURL(url) {
  const value = String(url || '').replace(/\/+$/, '')
  try {
    if (value) uni.setStorageSync(STORAGE_KEY_BASE_URL, value)
    else uni.removeStorageSync(STORAGE_KEY_BASE_URL)
  } catch (e) {
    // 存储失败不影响本次会话，下次启动会回到默认值
  }
  return value || DEFAULT_BASE_URL
}

/** 拼接完整 URL：path 以 / 开头 */
export function resolveURL(path) {
  return getBaseURL() + path
}

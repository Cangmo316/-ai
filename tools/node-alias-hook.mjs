/**
 * 比邻AI · node 侧的模块解析垫片（只为测试服务，不参与 App 构建）
 *
 * 端侧代码用 uni-app 的 `@/` 别名和 `vue` 运行时，这两样在裸 node 里都没有。
 * 这里把它们补上，好让 stores/ 这类纯逻辑模块能直接跑单测——
 * 否则「流式生命周期 / 一键停止 / 降级兜底」这些最容易出错的分支
 * 只能靠 HBuilderX 里手点，回归成本极高。
 *
 * 用法（见 tools/test-chat-store.mjs）：
 *   import { register } from 'node:module'
 *   register('./node-alias-hook.mjs', import.meta.url)
 *   const store = await import('../uni-app/stores/chat.js')
 *
 * 注意：`vue` 被替换成极简桩（reactive 直接返回原对象）。
 * stores/chat.js 只用到 reactive，不需要真正的响应式；一旦它开始用 watch/computed，
 * 就必须扩这里的桩，否则测试会在 import 阶段就报错——这是有意为之的提醒。
 */

const APP_ROOT = new URL('../uni-app/', import.meta.url)

const VUE_STUB = 'data:text/javascript;charset=utf-8,' + encodeURIComponent([
  'export const reactive = (o) => o',
  'export const ref = (v) => ({ value: v })',
  'export const computed = (fn) => ({ get value() { return fn() } })',
  'export const watch = () => () => {}',
  'export const nextTick = (fn) => Promise.resolve().then(fn)',
  'export const onMounted = (fn) => { void fn }',
  'export default { reactive, ref, computed, watch, nextTick, onMounted }'
].join('\n'))

export function resolve(specifier, context, nextResolve) {
  if (specifier === 'vue') return { url: VUE_STUB, shortCircuit: true }
  if (specifier.startsWith('@/')) {
    return nextResolve(new URL(specifier.slice(2), APP_ROOT).href, context)
  }
  return nextResolve(specifier, context)
}

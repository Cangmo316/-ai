/**
 * 模块解析钩子，给纯 Node 跑的测试用：
 *   1. 裸模块名 `vue` → tests/vue-shim.mjs（工程零 npm 依赖，见 vue-shim.mjs）
 *   2. 路径别名 `@/xxx`  → 项目根下的 xxx（对齐 vite 配置里的 @ → uni-app 根目录）
 *
 * 由 vue-loader.mjs 通过 register() 装进来。
 */

import { pathToFileURL, fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
/** tests/ 的上一级就是 uni-app 根目录（Vite 里 @ 指向它） */
const ROOT = dirname(HERE)
const SHIM = pathToFileURL(join(HERE, 'vue-shim.mjs')).href

export function resolve(specifier, context, nextResolve) {
  if (specifier === 'vue') {
    return { url: SHIM, shortCircuit: true }
  }
  if (specifier.startsWith('@/')) {
    const target = pathToFileURL(join(ROOT, specifier.slice(2))).href
    return { url: target, shortCircuit: true }
  }
  return nextResolve(specifier, context)
}

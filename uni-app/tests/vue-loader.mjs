/**
 * 把 `import ... from 'vue'` 重定向到 tests/vue-shim.mjs。
 *
 * 用法：node --import ./tests/vue-loader.mjs tests/xxx.test.mjs
 * 原因见 vue-shim.mjs 顶部说明（工程零 npm 依赖，测试进程里补一个最小实现）。
 */

import { register } from 'node:module'
import { pathToFileURL } from 'node:url'

register('./vue-resolver.mjs', pathToFileURL(import.meta.filename))

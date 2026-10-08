/**
 * 测试专用的 `vue` 解析钩子。
 *
 * ## 为什么需要它
 *
 * `stores/` 下的计划类模块（daily.js / special.js）用了 `reactive()` 来让页面
 * 自动重渲染，但 uni-app 端是**零 npm 依赖**的工程——没有 node_modules，
 * 所以纯 Node 里 `import { reactive } from 'vue'` 会直接 ERR_MODULE_NOT_FOUND。
 * 既有的 roles.test.mjs 之所以能跑，是因为 roles.js 恰好没用 vue。
 *
 * ## 做法
 *
 * 用一个 loader 把 `vue` 这个裸模块名解析到这个 shim：
 *   node --import ./tests/vue-loader.mjs tests/special.test.mjs
 *
 * **不给工程加 node_modules**——那是为了这样一个测试去改变 App 端
 * "零依赖"的架构约定，代价太大。这里只在测试进程里补一个最小实现。
 *
 * ⚠️ 只实现了商店实际用到的那一个 API。将来哪个 store 用到别的 vue 能力
 * （computed / watch / ref…），要在这里补上，否则测试会以"函数不存在"失败——
 * 那时请补 shim，而不是给工程装 vue。
 */
export function reactive(target) {
  // 测试里直接读对象属性，不需要真的建立响应式依赖。
  // 恒等返回即可——数据流仍然走的是产品代码本身。
  return target
}

export function ref(value) {
  // 极简 ref：够 stores 里 `xxx.value` 的读写
  return { value }
}

export function computed(fn) {
  return { get value() { return fn() } }
}

export default { reactive, ref, computed }

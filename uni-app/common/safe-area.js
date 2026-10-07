/**
 * 比邻AI · 顶部安全间距
 *
 * ## 为什么需要它
 *
 * 需求：「所有界面最上面一栏都往下挪动一点，空出来一点，不然操作对部分机型不友好」。
 *
 * 而 **`env(safe-area-inset-top)` 在 App 端不可靠**：uni-app 的 WebView 默认不是
 * edge-to-edge，这个 CSS 变量在真机（荣耀 AAK-AN00 / Android 16 实测）返回 **0**。
 * 于是纯 CSS 方案下标题会直接顶到状态栏，挖孔屏上被摄像头压住、返回键难点。
 *
 * `uni.getSystemInfoSync().statusBarHeight` 才是 App 端拿得到的状态栏高度；
 * H5 端它可能是 0，此时回落 CSS 的 `env()`（浏览器里是真值）。
 *
 * ## 用法
 *
 *   · 组件/页面里要动态算：`const top = ref(topGap()); onMounted(() => top.value = topGap())`
 *   · 只想写死在样式里：用 `style.top: calc(<topGap()>px + 其他)`，
 *     或者直接用 `.bl-page-topgap` 这个全局类（见 App.vue）
 */

/** 状态栏之下再额外留的空白（px）。需求要求"往下挪一点、空出来一点"。 */
export const EXTRA_TOP_GAP = 10

/**
 * 取顶部让位高度（px，含额外留白）。
 *
 * @returns {number} 至少 `EXTRA_TOP_GAP * 2`，保证即使拿不到状态栏高度也不顶格
 */
export function topGap() {
  let statusBar = 0
  try {
    const info = typeof uni !== 'undefined' && uni.getSystemInfoSync ? uni.getSystemInfoSync() : null
    if (info && typeof info.statusBarHeight === 'number' && info.statusBarHeight > 0) {
      statusBar = info.statusBarHeight
    }
  } catch (e) {
    statusBar = 0
  }
  return Math.max(EXTRA_TOP_GAP, statusBar) + EXTRA_TOP_GAP
}

export default { topGap, EXTRA_TOP_GAP }

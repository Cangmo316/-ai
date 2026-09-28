/**
 * 比邻AI · 极简测试运行器（零依赖）
 *
 * 仓库约定：校验脚本一律 `node xxx.mjs` 直接跑，不引 jest/vitest。
 * 参考已有做法：server/app/knowledge/validate.mjs。
 */

const state = { pass: 0, fail: 0, failures: [] }

export function group(title) {
  console.log('')
  console.log(title)
}

export function test(name, fn) {
  try {
    fn()
    state.pass += 1
    console.log('  \u2713 ' + name)
  } catch (error) {
    state.fail += 1
    state.failures.push({ name, error })
    console.log('  \u2717 ' + name)
    console.log('      ' + (error && error.message ? error.message : String(error)))
  }
}

export async function testAsync(name, fn) {
  try {
    await fn()
    state.pass += 1
    console.log('  \u2713 ' + name)
  } catch (error) {
    state.fail += 1
    state.failures.push({ name, error })
    console.log('  \u2717 ' + name)
    console.log('      ' + (error && error.message ? error.message : String(error)))
  }
}

export function finish() {
  console.log('')
  console.log('通过 ' + state.pass + ' 项，失败 ' + state.fail + ' 项')
  if (state.fail > 0) {
    console.log('')
    console.log('失败清单：')
    state.failures.forEach((item) => {
      console.log('  - ' + item.name + '：' + (item.error && item.error.message))
    })
    process.exitCode = 1
  }
  return state
}

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/** 轮询等待条件成立，超时抛错（比固定 sleep 稳，也不会白等） */
export async function waitUntil(predicate, timeoutMs = 5000, label = '条件') {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (predicate()) return true
    await sleep(20)
  }
  throw new Error('等待超时（' + timeoutMs + 'ms）：' + label)
}

/**
 * 纯 JS Base64 编码（不依赖 btoa / Buffer）。
 * 小程序、App、H5 三端通用；本文件只用于编码纯 ASCII 的 SVG 字符串。
 */
const CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'

export function base64Encode(input) {
  let output = ''
  let i = 0
  while (i < input.length) {
    const c1 = input.charCodeAt(i++)
    const c2 = i < input.length ? input.charCodeAt(i++) : NaN
    const c3 = i < input.length ? input.charCodeAt(i++) : NaN

    const e1 = c1 >> 2
    const e2 = ((c1 & 3) << 4) | (isNaN(c2) ? 0 : c2 >> 4)
    const e3 = isNaN(c2) ? 64 : (((c2 & 15) << 2) | (isNaN(c3) ? 0 : c3 >> 6))
    const e4 = isNaN(c3) ? 64 : (c3 & 63)

    output += CHARS.charAt(e1) + CHARS.charAt(e2) +
      (e3 === 64 ? '=' : CHARS.charAt(e3)) +
      (e4 === 64 ? '=' : CHARS.charAt(e4))
  }
  return output
}

export default base64Encode
/**
 * 比邻AI · 病例病史接口
 *
 * 契约见 server/app/api/cases.py。要点：
 *  · 建病历时**用 multipart** 传文件（不走 base64：病历照片几百 KB，
 *    base64 平白多 33% 体积，与录音接口同一个理由）
 *  · 服务端自动解析：PDF 抽文本层、图片走识图。图片识别没配 key 时
 *    会返回 `extractStatus: failed` + 原因，**老人仍可手填**——识别是辅助不是前置
 *  · 扫描件 PDF 会返回 `extractStatus: scanned`，要如实提示"拍张照"
 */

import { ENDPOINTS, resolveURL } from './config.js'
import { request } from './request.js'

function authHeader(token) {
  return token ? { Authorization: 'Bearer ' + token } : {}
}

/** 病历类型下拉（不需要登录） */
export function fetchCaseTypes() {
  return request({ url: resolveURL(ENDPOINTS.caseTypes) })
}

/** 识图能力自检：拍照识别到底能不能用 */
export function fetchVisionStatus() {
  return request({ url: resolveURL(ENDPOINTS.visionStatus) })
}

/** 我的病例列表 */
export function fetchCases(token) {
  return request({
    url: resolveURL(ENDPOINTS.cases),
    header: authHeader(token)
  })
}

/** 病历详情（含解析出的全文） */
export function fetchCase(token, caseId) {
  return request({
    url: resolveURL(ENDPOINTS.cases) + '/' + encodeURIComponent(caseId || ''),
    header: authHeader(token)
  })
}

/**
 * 建一份病历。**用 multipart**：文字字段 + 多个文件。
 * @param {object} params
 * @param {string} [params.kind]      病历类型
 * @param {string} [params.title]
 * @param {string} [params.hospital]
 * @param {string} [params.visitDate]
 * @param {string} [params.diagnosis]
 * @param {string} [params.summary]
 * @param {string} [params.note]
 * @param {Array}  [params.files]     形如 [{ name, path, file }]，uni.uploadFile 的 files
 */
export function createCase(token, params = {}) {
  const formData = {
    kind: params.kind || 'other',
    title: params.title || '',
    hospital: params.hospital || '',
    visitDate: params.visitDate || '',
    diagnosis: params.diagnosis || '',
    summary: params.summary || '',
    note: params.note || ''
  }
  return uploadWithFiles(token, ENDPOINTS.cases, formData, params.files || [], 'files')
}

/** 给已有病历加附件 */
export function addCaseFile(token, caseId, filePath) {
  const url = ENDPOINTS.cases + '/' + encodeURIComponent(caseId || '') + '/files'
  return uploadWithFiles(token, url, {}, [{ name: 'file', uri: filePath }], 'file')
}

/** 改病历字段（老人自己修识别错的地方） */
export function updateCase(token, caseId, fields = {}) {
  return request({
    url: resolveURL(ENDPOINTS.cases) + '/' + encodeURIComponent(caseId || ''),
    method: 'PATCH',
    header: authHeader(token),
    data: fields
  })
}

/** 删病历（连同附件与磁盘原件） */
export function deleteCase(token, caseId) {
  return request({
    url: resolveURL(ENDPOINTS.cases) + '/' + encodeURIComponent(caseId || ''),
    method: 'DELETE',
    header: authHeader(token)
  })
}

/** 删一个附件 */
export function deleteCaseFile(token, caseId, fileId) {
  return request({
    url: resolveURL(ENDPOINTS.cases) + '/' + encodeURIComponent(caseId || '')
      + '/files/' + encodeURIComponent(fileId || ''),
    method: 'DELETE',
    header: authHeader(token)
  })
}

/** 原件地址（家属端查看原图用；H5 下直接可 img src） */
export function caseRawUrl(caseId, fileId) {
  return resolveURL(ENDPOINTS.cases) + '/' + encodeURIComponent(caseId || '')
    + '/files/' + encodeURIComponent(fileId || '') + '/raw'
}

/**
 * 用 `uni.uploadFile` 传 multipart。
 *
 * 为什么不走 `request`：`uni.request` 不支持文件，multipart 必须用 `uploadFile`。
 * 它返回的是字符串，要自己 JSON.parse。
 *
 * 只传 `files`（多文件字段）不传 `filePath`：两者同时给时
 * 各端行为不一致（H5 会重复发一次），统一走 `files` 最稳。
 */
function uploadWithFiles(token, path, formData, files, fieldName) {
  return new Promise((resolve, reject) => {
    const header = {}
    if (token) header.Authorization = 'Bearer ' + token

    const list = (files || [])
      .map((item) => ({
        name: fieldName,
        uri: item.uri || item.path || (item.file && (item.file.path || item.file.tempFilePath)) || ''
      }))
      .filter((item) => item.uri)

    uni.uploadFile({
      url: resolveURL(path),
      files: list,
      name: fieldName,
      formData,
      header,
      success(res) {
        let body = res.data
        if (typeof body === 'string') {
          try {
            body = JSON.parse(body)
          } catch (error) {
            reject(new Error('服务器返回的内容看不懂'))
            return
          }
        }
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(body)
          return
        }
        const message = (body && body.error && body.error.message) || '没存上，再试一次'
        reject(new Error(message))
      },
      fail() {
        reject(new Error('网络不太好，再试一次'))
      }
    })
  })
}

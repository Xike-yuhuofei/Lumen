import { apiFetch, apiUrl } from './http'

/** 资料库（Library）真实数据源 = 知识库（Knowledge Base）系统。
 *
 * Library 页面不维护平行数据模型，直接消费既有知识库 pipeline：
 * create/upload → 后台索引 → ready/error 状态 → RAG 检索。
 * 本模块只做薄封装，字段与后端 /api/v1/knowledge 契约保持一致。
 */

export type KbStatus =
  | 'ready'
  | 'processing'
  | 'initializing'
  | 'error'
  | 'needs_reindex'
  | 'unknown'
  | 'unavailable'

export interface KbProgress {
  stage?: string
  message?: string
  percent?: number
  current?: number
  total?: number
  error?: string
  task_id?: string
  timestamp?: string
  indexed_count?: number | null
  index_changed?: boolean | null
  index_action?: string | null
}

export interface KbInfo {
  id: string
  name: string
  is_default: boolean
  status: KbStatus
  statistics: {
    raw_documents: number
    images: number
    content_lists: number
    rag_initialized: boolean
    rag_provider: string
    needs_reindex: boolean
    active_match?: boolean
  }
  progress?: KbProgress | null
  metadata?: {
    name?: string
    created_at?: string
    last_updated?: string
    last_indexed_at?: string
    last_indexed_count?: number
    last_error?: string
    last_error_at?: string
    rag_provider?: string
    needs_reindex?: boolean
  } | null
}

export interface KbFile {
  name: string
  type: 'file' | 'folder'
  size?: number
  modified?: number
  mime_type?: string | null
}

export interface UploadResult {
  message: string
  files: string[]
  task_id: string
}

export interface CreateResult {
  message: string
  name: string
  files: string[]
  task_id: string
}

export interface SupportedFileTypes {
  extensions: string[]
  accept: string
  max_file_size_bytes: number
}

/** 知识库在 Lumen 里对应「资料库」这一产品入口。 */
export const LIBRARY_KB_NAME = '资料库'

export async function listKnowledgeBases(): Promise<KbInfo[]> {
  const response = await apiFetch(apiUrl('/api/v1/knowledge/list'), { cache: 'no-store' })
  if (!response.ok) {
    throw new Error(`加载知识库失败（${response.status}）`)
  }
  return (await response.json()) as KbInfo[]
}

export async function getKbInfo(kbName: string): Promise<KbInfo> {
  const response = await apiFetch(
    apiUrl(`/api/v1/knowledge/${encodeURIComponent(kbName)}`),
    { cache: 'no-store' },
  )
  if (!response.ok) {
    throw new Error(`加载知识库「${kbName}」失败（${response.status}）`)
  }
  return (await response.json()) as KbInfo
}

export async function getDefaultKb(): Promise<string | null> {
  try {
    const response = await apiFetch(apiUrl('/api/v1/knowledge/default'), { cache: 'no-store' })
    if (!response.ok) return null
    const data = (await response.json()) as { default_kb?: string | null }
    return data.default_kb || null
  } catch {
    return null
  }
}

export async function listKbFiles(kbName: string): Promise<KbFile[]> {
  const response = await apiFetch(
    apiUrl(`/api/v1/knowledge/${encodeURIComponent(kbName)}/files`),
    { cache: 'no-store' },
  )
  if (!response.ok) {
    throw new Error(`读取「${kbName}」文件列表失败（${response.status}）`)
  }
  const data = (await response.json()) as { files?: KbFile[] }
  return data.files ?? []
}

export async function getSupportedFileTypes(): Promise<SupportedFileTypes | null> {
  try {
    const response = await apiFetch(apiUrl('/api/v1/knowledge/supported-file-types'), {
      cache: 'no-store',
    })
    if (!response.ok) return null
    return (await response.json()) as SupportedFileTypes
  } catch {
    return null
  }
}

export async function createKnowledgeBase(
  name: string,
  files: File[],
): Promise<CreateResult> {
  const form = new FormData()
  form.append('name', name)
  form.append('rag_provider', 'llamaindex')
  files.forEach((file) => form.append('files', file, file.name))
  const response = await apiFetch(apiUrl('/api/v1/knowledge/create'), {
    method: 'POST',
    body: form,
    // 不手动设置 Content-Type：浏览器会带 boundary
  })
  const data = await readJsonError(response)
  return data as CreateResult
}

export async function uploadFilesToKb(
  kbName: string,
  files: File[],
): Promise<UploadResult> {
  const form = new FormData()
  files.forEach((file) => form.append('files', file, file.name))
  const response = await apiFetch(
    apiUrl(`/api/v1/knowledge/${encodeURIComponent(kbName)}/upload`),
    { method: 'POST', body: form },
  )
  const data = await readJsonError(response)
  return data as UploadResult
}

export async function deleteKbFile(kbName: string, path: string): Promise<void> {
  const response = await apiFetch(
    apiUrl(`/api/v1/knowledge/${encodeURIComponent(kbName)}/files/${encodeURIComponent(path)}`),
    { method: 'DELETE' },
  )
  if (!response.ok) {
    throw new Error(`删除失败（${response.status}）`)
  }
}

export async function retryKb(kbName: string): Promise<{ task_id: string | null }> {
  const response = await apiFetch(
    apiUrl(`/api/v1/knowledge/${encodeURIComponent(kbName)}/retry`),
    { method: 'POST' },
  )
  const data = await readJsonError(response)
  return data as { task_id: string | null }
}

export async function fetchKbFilePreview(kbName: string, path: string): Promise<string> {
  const response = await apiFetch(
    apiUrl(
      `/api/v1/knowledge/${encodeURIComponent(kbName)}/file-preview-text/${encodeURIComponent(path)}`,
    ),
    { cache: 'no-store' },
  )
  if (!response.ok) {
    throw new Error(`预览失败（${response.status}）`)
  }
  return response.text()
}

async function readJsonError(response: Response): Promise<unknown> {
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    // 非 JSON 响应（如代理错误页）
  }
  if (!response.ok) {
    const detail =
      (body as { detail?: string } | null)?.detail ||
      (body as { message?: string } | null)?.message ||
      `请求失败（${response.status}）`
    throw new Error(typeof detail === 'string' ? detail : '请求失败')
  }
  return body
}

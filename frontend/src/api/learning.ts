import { apiFetch, apiUrl, expectJson } from './http'

export interface LearningGoal {
  book_id: string
  name: string
  goal_name: string
  description: string
  modules_count: number
  kp_count: number
  current_stage: string
  avg_mastery_pct: number
  updated_at: number
}

export interface KnowledgePointStatus {
  id: string
  name: string
  type: string
  status: 'mastered' | 'learning' | 'new'
  mastery: number
}

export interface ModuleStatus {
  id: string
  name: string
  order: number
  mastered: number
  total: number
  knowledge_points: KnowledgePointStatus[]
}

export interface NextStep {
  action: string
  module_id: string
  module_name: string
  knowledge_point_id: string
  knowledge_point_name: string
  knowledge_point_type: string
  status: string
  gate: string
  mastery: number
  threshold: number
  reason: string
  pending_prompt: string
  pending_question: unknown
}

export interface GoalMap {
  book_id: string
  next: NextStep
  map: {
    counts: { mastered: number; learning: number; new: number; total: number }
    goal: { name: string; mastered: number; total: number }
    due_reviews: number
    complete: boolean
    modules: ModuleStatus[]
  }
}

export async function listLearningProgress(): Promise<LearningGoal[]> {
  const response = await apiFetch(apiUrl('/api/v1/learning/progress'), { cache: 'no-store' })
  const data = await expectJson<{ summaries?: LearningGoal[]; errors?: unknown[] }>(response)
  return data.summaries ?? []
}

export async function getLearningProgressMap(bookId: string, signal?: AbortSignal): Promise<GoalMap> {
  const response = await apiFetch(apiUrl(`/api/v1/learning/progress/${encodeURIComponent(bookId)}/map`), {
    cache: 'no-store',
    signal,
  })
  return expectJson<GoalMap>(response)
}

export async function createLearningGoal(
  title: string,
  description = '',
): Promise<{ book_id: string; goal_name: string }> {
  const response = await apiFetch(apiUrl('/api/v1/learning/goals'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, description }),
  })
  return expectJson<{ book_id: string; goal_name: string }>(response)
}

export async function renameLearningGoal(
  bookId: string,
  title: string,
): Promise<{ book_id: string; goal_name: string }> {
  const response = await apiFetch(apiUrl(`/api/v1/learning/goals/${encodeURIComponent(bookId)}`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
  return expectJson<{ book_id: string; goal_name: string }>(response)
}

export async function deleteLearningProgress(bookId: string): Promise<void> {
  const response = await apiFetch(apiUrl(`/api/v1/learning/progress/${encodeURIComponent(bookId)}`), {
    method: 'DELETE',
  })
  await expectJson<{ status: string }>(response)
}

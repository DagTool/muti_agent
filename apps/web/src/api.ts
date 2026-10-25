export type Project = { id: string; name: string; description: string; status: string; token_budget: number; tokens_used: number }
export type Requirement = { id: string; project_id: string; version: number; content: string }
export type Run = { id: string; project_id: string; requirement_id: string; status: string; mode: 'mock' | 'openai' }
export type Task = {
  id: string; project_id: string; run_id: string | null; title: string; role: string;
  status: string; attempt: number; correlation_id: string; result: string | null
}
export type Approval = {
  id: string; run_id: string; action: string; status: string;
  note: string | null; reviewed_by: string | null
}
export type Artifact = {
  id: string; project_id: string; run_id: string | null; task_id: string | null;
  kind: string; content: string
}
export type Activity = {
  id: string; action: string; resource_id: string; correlation_id: string; created_at: string
}
export type ModelUsage = {
  id: string; run_id: string; task_id: string; attempt: number; model: string;
  input_tokens: number; output_tokens: number; created_at: string
}
export type GeneratedFile = { path: string; content: string }
export type Actor = { user_id: string | null; role: 'owner' | 'member' | 'viewer'; workspace_id: string }
export type Member = { id: string; email: string; name: string; role: 'owner' | 'member' | 'viewer' }
export type Token = { id: string; created_at: string; expires_at: string; revoked_at: string | null }
export type IssuedToken = Token & { api_token: string }
export type CreatedMember = Member & { token_id: string; api_token: string; expires_at: string }

const baseUrl = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

export async function watchProject(
  key: string, projectId: string, onChange: () => void, signal: AbortSignal,
): Promise<void> {
  while (!signal.aborted) {
    try {
      const response = await fetch(`${baseUrl}/api/v1/projects/${projectId}/events`, {
        headers: { 'X-API-Key': key }, signal,
      })
      if (response.status === 401 || response.status === 403 || response.status === 404) return
      if (!response.ok || !response.body) throw new Error(`Event stream HTTP ${response.status}`)
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (!signal.aborted) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const frames = buffer.split('\n\n')
        buffer = frames.pop() ?? ''
        for (const frame of frames) {
          if (frame.startsWith('event: change\n')) onChange()
        }
      }
    } catch {
      if (signal.aborted) return
    }
    if (!signal.aborted) await new Promise(resolve => window.setTimeout(resolve, 2000))
  }
}

async function request<T>(key: string, path: string, method = 'GET', body?: object): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    method,
    headers: {
      'X-API-Key': key,
      ...(body ? { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) {
    let message = `HTTP ${response.status}`
    try {
      const data = await response.json()
      message = typeof data.detail === 'string' ? data.detail : message
    } catch { /* Keep status when response is not JSON. */ }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export const api = {
  me: (key: string) => request<Actor>(key, '/api/v1/auth/me'),
  members: (key: string) => request<Member[]>(key, '/api/v1/members'),
  createMember: (key: string, body: { email: string; name: string; role: Member['role'] }) =>
    request<CreatedMember>(key, '/api/v1/members', 'POST', body),
  memberTokens: (key: string, memberId: string) => request<Token[]>(key, `/api/v1/members/${memberId}/tokens`),
  createMemberToken: (key: string, memberId: string) => request<IssuedToken>(key, `/api/v1/members/${memberId}/tokens`, 'POST', {}),
  revokeToken: (key: string, tokenId: string) => request<{ status: string }>(key, `/api/v1/tokens/${tokenId}/revoke`, 'POST', {}),
  projects: (key: string) => request<Project[]>(key, '/api/v1/projects'),
  createProject: (key: string, body: { name: string; description: string }) =>
    request<Project>(key, '/api/v1/projects', 'POST', body),
  updateBudget: (key: string, projectId: string, tokenBudget: number) =>
    request<Project>(key, `/api/v1/projects/${projectId}/budget`, 'POST', { token_budget: tokenBudget }),
  requirements: (key: string, projectId: string) =>
    request<Requirement[]>(key, `/api/v1/projects/${projectId}/requirements`),
  createRequirement: (key: string, projectId: string, content: string) =>
    request<Requirement>(key, `/api/v1/projects/${projectId}/requirements`, 'POST', { content }),
  runs: (key: string, projectId: string) =>
    request<Run[]>(key, `/api/v1/projects/${projectId}/runs`),
  createRun: (key: string, projectId: string) =>
    request<Run>(key, `/api/v1/projects/${projectId}/runs`, 'POST', {}),
  cancelRun: (key: string, runId: string) =>
    request<Run>(key, `/api/v1/runs/${runId}/cancel`, 'POST', {}),
  resumeRun: (key: string, runId: string) =>
    request<Run>(key, `/api/v1/runs/${runId}/resume`, 'POST', {}),
  tasks: (key: string, projectId: string) =>
    request<Task[]>(key, `/api/v1/projects/${projectId}/tasks`),
  artifacts: (key: string, projectId: string) =>
    request<Artifact[]>(key, `/api/v1/projects/${projectId}/artifacts`),
  activity: (key: string, projectId: string) =>
    request<Activity[]>(key, `/api/v1/projects/${projectId}/activity`),
  modelUsage: (key: string, projectId: string) =>
    request<ModelUsage[]>(key, `/api/v1/projects/${projectId}/model-usage`),
  files: (key: string, runId: string) =>
    request<string[]>(key, `/api/v1/runs/${runId}/files`),
  file: (key: string, runId: string, path: string) =>
    request<GeneratedFile>(key, `/api/v1/runs/${runId}/file?path=${encodeURIComponent(path)}`),
  approvals: (key: string) => request<Approval[]>(key, '/api/v1/approvals?status=pending'),
  decide: (key: string, id: string, decision: 'approve' | 'reject') =>
    request<Approval>(key, `/api/v1/approvals/${id}/decision`, 'POST', { decision }),
}

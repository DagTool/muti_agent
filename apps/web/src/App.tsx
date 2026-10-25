import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, watchProject, type Activity, type Actor, type Approval, type Artifact, type GeneratedFile, type Member, type ModelUsage, type Project, type Requirement, type Run, type Task, type Token } from './api'

const statusNames: Record<string, string> = {
  active: 'Đang hoạt động', ready: 'Sẵn sàng', running: 'Đang chạy', completed: 'Hoàn tất',
  cancelled: 'Đã hủy', blocked: 'Bị chặn', awaiting_scope_approval: 'Chờ duyệt phạm vi',
  awaiting_handover_approval: 'Chờ duyệt bàn giao',
}

function shortId(id: string) { return id.slice(0, 8) }
function statusName(value: string) { return statusNames[value] ?? value.replaceAll('_', ' ') }

function App() {
  const [apiKey, setApiKey] = useState('')
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState<string | null>(null)
  const [requirements, setRequirements] = useState<Requirement[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [activity, setActivity] = useState<Activity[]>([])
  const [modelUsage, setModelUsage] = useState<ModelUsage[]>([])
  const [files, setFiles] = useState<string[]>([])
  const [preview, setPreview] = useState<GeneratedFile | null>(null)
  const [projectName, setProjectName] = useState('')
  const [projectDescription, setProjectDescription] = useState('')
  const [requirementText, setRequirementText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [connected, setConnected] = useState(false)
  const [actor, setActor] = useState<Actor | null>(null)
  const [members, setMembers] = useState<Member[]>([])
  const [memberTokens, setMemberTokens] = useState<Token[]>([])
  const [selectedMemberId, setSelectedMemberId] = useState<string | null>(null)
  const [issuedToken, setIssuedToken] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!apiKey) { setConnected(false); setActor(null); return }
    try {
      const [projectList, approvalList, identity] = await Promise.all([
        api.projects(apiKey), api.approvals(apiKey), api.me(apiKey),
      ])
      setProjects(projectList)
      setApprovals(approvalList)
      setActor(identity)
      setMembers(identity.role === 'owner' ? await api.members(apiKey) : [])
      setConnected(true)
      setError('')
      if (projectId) {
        const [reqList, runList, taskList, artifactList, activityList, usageList] = await Promise.all([
          api.requirements(apiKey, projectId), api.runs(apiKey, projectId),
          api.tasks(apiKey, projectId), api.artifacts(apiKey, projectId), api.activity(apiKey, projectId),
          api.modelUsage(apiKey, projectId),
        ])
        setRequirements(reqList)
        setRuns(runList)
        setTasks(taskList)
        setArtifacts(artifactList)
        setActivity(activityList)
        setModelUsage(usageList)
        const latestOpenaiRun = runList.find(run => run.mode === 'openai')
        setFiles(latestOpenaiRun ? await api.files(apiKey, latestOpenaiRun.id).catch(() => []) : [])
      }
    } catch (cause) {
      setConnected(false)
      setActor(null)
      setMembers([])
      setError(cause instanceof Error ? cause.message : 'Không tải được dữ liệu')
    }
  }, [apiKey, projectId])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 30000)
    const controller = new AbortController()
    if (apiKey && projectId) {
      void watchProject(apiKey, projectId, () => { void refresh() }, controller.signal)
    }
    return () => { window.clearInterval(timer); controller.abort() }
  }, [apiKey, projectId, refresh])

  useEffect(() => { setPreview(null); setFiles([]) }, [projectId])
  useEffect(() => { setIssuedToken(null); setSelectedMemberId(null); setMemberTokens([]) }, [apiKey])

  async function perform(action: () => Promise<void>) {
    setBusy(true)
    setError('')
    try { await action(); await refresh() }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Thao tác thất bại') }
    finally { setBusy(false) }
  }

  function createProject(event: FormEvent) {
    event.preventDefault()
    if (!projectName.trim()) return
    void perform(async () => {
      const created = await api.createProject(apiKey, {
        name: projectName.trim(), description: projectDescription.trim(),
      })
      setProjectId(created.id)
      setProjectName('')
      setProjectDescription('')
    })
  }

  function createRequirement(event: FormEvent) {
    event.preventDefault()
    if (!projectId || requirementText.trim().length < 10) return
    void perform(async () => {
      await api.createRequirement(apiKey, projectId, requirementText.trim())
      setRequirementText('')
    })
  }

  function createMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    void perform(async () => {
      const created = await api.createMember(apiKey, {
        email: String(data.get('email')).trim(),
        name: String(data.get('name')).trim(),
        role: String(data.get('role')) as Member['role'],
      })
      setIssuedToken(created.api_token)
      setSelectedMemberId(created.id)
      setMemberTokens(await api.memberTokens(apiKey, created.id))
      form.reset()
    })
  }

  function selectMember(memberId: string) {
    setSelectedMemberId(memberId)
    setIssuedToken(null)
    setMemberTokens([])
    void api.memberTokens(apiKey, memberId).then(setMemberTokens).catch(cause => {
      setError(cause instanceof Error ? cause.message : 'Không tải được token')
    })
  }

  const selected = projects.find(project => project.id === projectId)
  const projectApprovals = approvals.filter(approval => runs.some(run => run.id === approval.run_id))
  const latestRequirement = requirements[0]
  const latestOpenaiRun = runs.find(run => run.mode === 'openai')
  const canWrite = actor?.role === 'owner' || actor?.role === 'member'
  const isOwner = actor?.role === 'owner'

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark">AF</div><div><strong>AgentForge AI</strong><small>CONTROL PLANE</small></div></div>
        <div className="sidebar-section-label">WORKSPACE</div>
        <div className="workspace-card"><span className="workspace-dot" />Local development <span className="chevron">⌄</span></div>
        <div className="sidebar-section-label projects-label">PROJECTS <span>{projects.length}</span></div>
        <div className="project-list">
          {projects.length === 0 && <p className="sidebar-empty">Chưa có dự án</p>}
          {projects.map(project => (
            <button className={`project-link ${projectId === project.id ? 'selected' : ''}`}
              key={project.id} onClick={() => setProjectId(project.id)}>
              <span className="project-avatar">{project.name.slice(0, 1).toUpperCase()}</span>
              <span className="project-link-text">{project.name}</span>
            </button>
          ))}
        </div>
        <form className="new-project" onSubmit={createProject}>
          <div className="sidebar-section-label">NEW PROJECT</div>
          <input aria-label="Tên dự án" placeholder="Tên dự án" value={projectName}
            onChange={event => setProjectName(event.target.value)} maxLength={200} />
          <input aria-label="Mô tả dự án" placeholder="Mô tả ngắn" value={projectDescription}
            onChange={event => setProjectDescription(event.target.value)} maxLength={10000} />
          <button className="button secondary full" disabled={!canWrite || busy || !projectName.trim()} type="submit">+ Tạo dự án</button>
        </form>
        <div className="sidebar-footer">Prototype v0.2 <span>·</span> Local only</div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="breadcrumb">Workspace <span>/</span> {selected?.name ?? 'Overview'}</div>
          <div className="topbar-right">
            <span className={`connection ${connected ? 'online' : ''}`}><i />{connected ? `${actor?.role ?? ''} · API connected` : 'API disconnected'}</span>
            <input aria-label="API key" className="key-input" type="password" placeholder="Nhập API key từ .env"
              autoComplete="off" value={apiKey} onChange={event => setApiKey(event.target.value)} />
          </div>
        </header>

        <div className="content">
          <div className="page-heading">
            <div><div className="eyebrow">PROJECT CONTROL</div><h1>{selected?.name ?? 'Tổng quan workspace'}</h1>
              <p>{selected?.description || 'Tạo một dự án và nhập yêu cầu để bắt đầu workflow có phê duyệt.'}</p></div>
            <button className="button ghost" onClick={() => void refresh()} disabled={!apiKey || busy}>↻ Làm mới</button>
          </div>

          <div className="notice"><span className="notice-icon">i</span><div><strong>Chế độ chạy</strong><span>Mỗi run hiển thị chế độ mock hoặc OpenAI. Chế độ OpenAI tạo mã và QA kiểm thử trong Docker; kết quả cần được xem lại trước khi bàn giao.</span></div></div>
          {error && <div className="error" role="alert">{error}</div>}

          {isOwner && <details className="panel member-panel">
            <summary><span><span className="eyebrow">WORKSPACE ACCESS</span><strong>Thành viên và API token</strong></span><span className="count">{members.length}</span></summary>
            <form className="member-form" onSubmit={createMember}>
              <input name="email" type="email" placeholder="Email" aria-label="Email thành viên" required />
              <input name="name" placeholder="Tên" aria-label="Tên thành viên" required />
              <select name="role" aria-label="Vai trò"><option value="member">Member</option><option value="viewer">Viewer</option><option value="owner">Owner</option></select>
              <button className="button secondary" disabled={busy}>Thêm thành viên</button>
            </form>
            <div className="member-list">{members.map(member => <button key={member.id} className={`member-item ${selectedMemberId === member.id ? 'active' : ''}`} onClick={() => selectMember(member.id)}>
              <strong>{member.name}</strong><span>{member.email} · {member.role}</span>
            </button>)}</div>
            {selectedMemberId && <div className="token-panel">
              <div className="token-heading"><strong>Token của {members.find(member => member.id === selectedMemberId)?.name ?? 'thành viên'}</strong>
                <button className="button secondary" disabled={busy} onClick={() => void perform(async () => {
                  const created = await api.createMemberToken(apiKey, selectedMemberId)
                  setIssuedToken(created.api_token)
                  setMemberTokens(await api.memberTokens(apiKey, selectedMemberId))
                })}>Cấp token mới</button></div>
              {issuedToken && <div className="issued-token"><span>Chỉ hiển thị một lần. Hãy sao chép và lưu an toàn.</span><code>{issuedToken}</code><button className="text-button" onClick={() => setIssuedToken(null)}>Ẩn token</button></div>}
              {memberTokens.map(token => <div className="token-row" key={token.id}>
                <span>#{shortId(token.id)} · hết hạn {new Date(token.expires_at).toLocaleDateString('vi-VN')} · {token.revoked_at ? 'đã thu hồi' : 'đang hiệu lực'}</span>
                {!token.revoked_at && <button className="text-button" disabled={busy} onClick={() => void perform(async () => {
                  await api.revokeToken(apiKey, token.id)
                  setIssuedToken(null)
                  setMemberTokens(await api.memberTokens(apiKey, selectedMemberId))
                })}>Thu hồi</button>}
              </div>)}
            </div>}
          </details>}

          {!selected ? (
            <section className="empty-state"><div className="empty-symbol">◇</div><h2>Chọn dự án để bắt đầu</h2><p>Chọn một dự án trong danh sách hoặc tạo dự án mới bằng biểu mẫu ở thanh điều hướng.</p></section>
          ) : (
            <>
              <div className="metrics">
                <div className="metric"><span>Runs</span><strong>{runs.length}</strong><small>workflow đã tạo</small></div>
                <div className="metric"><span>Tasks</span><strong>{tasks.length}</strong><small>{tasks.filter(task => task.status === 'completed').length} hoàn tất</small></div>
                <div className="metric"><span>Approvals</span><strong>{projectApprovals.length}</strong><small>đang chờ quyết định</small></div>
                <div className="metric"><span>Artifacts</span><strong>{artifacts.length}</strong><small>tài liệu & báo cáo</small></div>
                <div className="metric"><span>Model tokens</span><strong>{selected.tokens_used.toLocaleString('vi-VN')}</strong><small>giới hạn {selected.token_budget.toLocaleString('vi-VN')}</small></div>
              </div>

              <div className="grid-main">
                <div className="column">
                  <section className="panel">
                    <div className="panel-heading"><div><div className="eyebrow">01 / DEFINE</div><h2>Yêu cầu dự án</h2></div><span className="count">v{latestRequirement?.version ?? 0}</span></div>
                    {latestRequirement && <div className="latest-requirement"><strong>Phiên bản mới nhất</strong><p>{latestRequirement.content}</p></div>}
                    <form onSubmit={createRequirement}>
                      <label htmlFor="requirement">Thêm phiên bản yêu cầu</label>
                      <textarea id="requirement" rows={5} placeholder="Mô tả sản phẩm, hành vi mong muốn và tiêu chí nghiệm thu..." disabled={!canWrite}
                        value={requirementText} onChange={event => setRequirementText(event.target.value)} />
                      <div className="form-actions"><span>Tối thiểu 10 ký tự</span><button className="button primary" disabled={!canWrite || busy || requirementText.trim().length < 10}>Lưu yêu cầu</button></div>
                    </form>
                  </section>

                  <section className="panel">
                    <div className="panel-heading"><div><div className="eyebrow">02 / EXECUTE</div><h2>Workflow runs</h2></div><button className="button primary" disabled={!canWrite || busy || !latestRequirement}
                      onClick={() => void perform(async () => { await api.createRun(apiKey, selected.id) })}>+ Tạo run</button></div>
                    {runs.length === 0 ? <p className="muted">Chưa có run. Lưu yêu cầu rồi tạo run đầu tiên.</p> :
                      <div className="run-list">{runs.map(run => <div className="run-row" key={run.id}>
                        <div><strong>Run {shortId(run.id)}</strong><small>Requirement {shortId(run.requirement_id)} · {run.mode === 'openai' ? 'OpenAI' : 'Mock'}</small></div>
                        <div className="row-actions"><span className={`badge ${run.status}`}>{statusName(run.status)}</span>
                          {canWrite && run.status === 'blocked' && run.mode === 'openai' && <button className="text-button" disabled={busy}
                            onClick={() => void perform(async () => { await api.resumeRun(apiKey, run.id) })}>Thử lại</button>}
                          {canWrite && !['completed', 'cancelled'].includes(run.status) && <button className="text-button" disabled={busy}
                            onClick={() => void perform(async () => { await api.cancelRun(apiKey, run.id) })}>Hủy</button>}</div>
                      </div>)}</div>}
                  </section>

                  <section className="panel">
                    <div className="panel-heading"><div><div className="eyebrow">03 / TRACK</div><h2>Task board</h2></div><span className="count">{tasks.length}</span></div>
                    {tasks.length === 0 ? <p className="muted">Task sẽ xuất hiện khi run bắt đầu.</p> :
                      <div className="task-list">{tasks.map(task => <div className="task-row" key={task.id}>
                        <div className="task-role">{{pm: 'PM', architect: 'ARC', developer: 'DEV', qa: 'QA'}[task.role] ?? task.role.slice(0, 3).toUpperCase()}</div>
                        <div className="task-body"><strong>{task.title}</strong><small>#{shortId(task.id)} · correlation {shortId(task.correlation_id)}</small>{task.result && <p>{task.result}</p>}</div>
                        <span className={`badge ${task.status}`}>{statusName(task.status)}</span>
                      </div>)}</div>}
                  </section>
                </div>

                <div className="column side-column">
                  <section className="panel">
                    <div className="panel-heading"><div><div className="eyebrow">MODEL USAGE</div><h2>Ngân sách token</h2></div></div>
                    <p className="muted">Đã dùng {selected.tokens_used.toLocaleString('vi-VN')} / {selected.token_budget.toLocaleString('vi-VN')} token. Giới hạn mềm: cuộc gọi đang chạy có thể vượt mức đặt.</p>
                    {isOwner && <form className="budget-form" key={`${selected.id}:${selected.token_budget}`} onSubmit={event => {
                      event.preventDefault()
                      const value = Number(new FormData(event.currentTarget).get('tokenBudget'))
                      if (!Number.isInteger(value) || value < 1000) return
                      void perform(async () => { await api.updateBudget(apiKey, selected.id, value) })
                    }}>
                      <input name="tokenBudget" type="number" min="1000" max="10000000" defaultValue={selected.token_budget} aria-label="Giới hạn token" />
                      <button className="button secondary" disabled={busy}>Cập nhật</button>
                    </form>}
                    {modelUsage.length > 0 && <div className="usage-list">{modelUsage.slice(0, 5).map(item => <div key={item.id}>
                      <strong>{item.model}</strong><span>{(item.input_tokens + item.output_tokens).toLocaleString('vi-VN')} token</span>
                    </div>)}</div>}
                  </section>
                  <section className="panel approval-panel">
                    <div className="panel-heading"><div><div className="eyebrow">HUMAN GATE</div><h2>Chờ phê duyệt</h2></div><span className="count amber">{projectApprovals.length}</span></div>
                    {projectApprovals.length === 0 ? <p className="muted">Không có quyết định đang chờ.</p> : projectApprovals.map(approval =>
                      <div className="approval-card" key={approval.id}>
                        <div className="approval-icon">!</div><strong>{approval.action === 'scope' ? 'Duyệt phạm vi' : 'Duyệt bàn giao'}</strong>
                        <p>Run {shortId(approval.run_id)} · {approval.action === 'scope' ? 'Xem bản nháp phạm vi trước khi giao việc.' : 'Xem báo cáo QA trước khi hoàn tất.'}</p>
                        {isOwner ? <div className="approval-actions">
                          <button className="button primary" disabled={busy} onClick={() => void perform(async () => { await api.decide(apiKey, approval.id, 'approve') })}>Duyệt</button>
                          <button className="button secondary" disabled={busy} onClick={() => void perform(async () => { await api.decide(apiKey, approval.id, 'reject') })}>Từ chối</button>
                        </div> : <p>Chỉ owner được phê duyệt.</p>}
                      </div>) }
                  </section>

                  <section className="panel">
                    <div className="panel-heading"><div><div className="eyebrow">OUTPUT</div><h2>Artifacts</h2></div><span className="count">{artifacts.length}</span></div>
                    {artifacts.length === 0 ? <p className="muted">Chưa có artifact.</p> : artifacts.map(artifact =>
                      <details className="artifact" key={artifact.id}><summary><span className="artifact-icon">▤</span><span><strong>{artifact.kind.replaceAll('_', ' ')}</strong><small>Run {artifact.run_id ? shortId(artifact.run_id) : '—'}</small></span><span className="chevron">⌄</span></summary><pre>{artifact.content}</pre></details>) }
                  </section>

                  {latestOpenaiRun && <section className="panel">
                    <div className="panel-heading"><div><div className="eyebrow">SOURCE</div><h2>Mã đã sinh</h2></div><span className="count">{files.length}</span></div>
                    {files.length === 0 ? <p className="muted">Chưa có file cho run gần nhất.</p> : <div className="file-list">{files.map(path =>
                      <button key={path} className="file-link" onClick={() => void perform(async () => { setPreview(await api.file(apiKey, latestOpenaiRun.id, path)) })}>{path}</button>
                    )}</div>}
                    {preview && <div className="file-preview"><strong>{preview.path}</strong><pre>{preview.content}</pre></div>}
                  </section>}

                  <section className="panel">
                    <div className="panel-heading"><div><div className="eyebrow">TRACE</div><h2>Hoạt động</h2></div><span className="count">{activity.length}</span></div>
                    {activity.length === 0 ? <p className="muted">Chưa có hoạt động.</p> :
                      <ol className="activity-list">{activity.map(item => <li key={item.id}>
                        <span className="activity-dot" /><div><strong>{item.action.replaceAll('.', ' · ')}</strong>
                          <small>{new Date(item.created_at).toLocaleString('vi-VN')} · #{shortId(item.resource_id)}</small></div>
                      </li>)}</ol>}
                  </section>
                </div>
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  )
}

export default App

import { createContext, useContext, useEffect, useState } from 'react'
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Activity, ArrowUpRight, FileText, FolderOpen, LayoutDashboard, LogOut, MessageSquare, Plus, Search, Send, Settings, ShieldCheck, Sparkles, Trash2, UploadCloud, BookOpen, RefreshCw } from 'lucide-react'
import Chat from './Chat'
import api, { sessionHeaders, setCsrfToken } from './services/api'

const Auth = createContext(null)
const useAuth = () => useContext(Auth)
function Protected({ children }) { const { user } = useAuth(); return user ? children : <Navigate to="/login" replace /> }
function Shell({ children }) {
  const { user, logout, logoutError } = useAuth()
  const links = [["Overview", "/app", LayoutDashboard], ["Documents", "/app/documents", FolderOpen], ["AI chat", "/app/chat", MessageSquare], ["Summaries", "/app/summaries", BookOpen], ["History", "/app/history", Activity], ["Settings", "/app/settings", Settings]]
  const { pathname } = useLocation()
  const current = links.find(([, path]) => path === pathname)
  return <div className="app-shell">
    <aside className="sidebar">
      <Link className="brand" to="/app" aria-label="Paperwise overview">
        <span className="brand-mark"><Sparkles size={19}/></span>
        <span>paperwise<span className="brand-dot">.</span><small>DOCUMENT INTELLIGENCE</small></span>
      </Link>
      <div className="sidebar-content">
        <div className="workspace"><span className="workspace-icon">{user?.name?.[0]?.toUpperCase() || 'W'}</span><span><b>{user?.name || 'Your workspace'}</b><small>Personal workspace</small></span></div>
        <div className="nav-label">WORKSPACE</div>
        <nav aria-label="Workspace">
          {links.map(([label, path, Icon]) => <NavLink key={path} to={path} end={path === '/app'}
            title={label} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <Icon size={17}/><span>{label}</span>
          </NavLink>)}
        </nav>
      </div>
      <div className="sidebar-bottom">
        <div className="secure-note"><ShieldCheck size={16}/><span><b>Your files stay yours</b><small>Private and securely indexed</small></span></div>
        <div className="profile-chip"><div className="avatar">{user?.name?.[0]?.toUpperCase() || 'U'}</div><span><b>{user?.name || 'Account'}</b><small>{user?.email || ''}</small></span></div>
        {logoutError && <p role="alert">{logoutError}</p>}
        <button className="nav-item logout" onClick={logout} title="Sign out"><LogOut size={17}/><span>Sign out</span></button>
      </div>
    </aside>
    <main className="main-area">
      <header className="topbar">
        <div className="breadcrumb">Workspace <span>/</span> <b>{current?.[0] || 'Overview'}</b></div>
        <div className="top-actions"><span className="status-pill"><i/> All systems normal</span><button className="icon-button" title="Search"><Search size={17}/></button><div className="avatar small-avatar">{user?.name?.[0]?.toUpperCase() || 'U'}</div></div>
      </header>
      <section className="page-content">{children}</section>
    </main>
  </div>
}
function PageTitle({eyebrow,title,subtitle,action}) { return <div className="page-title"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{subtitle}</p></div>{action}</div> }
function Dashboard() {
  const [data,setData]=useState(null); const [error,setError]=useState('')
  useEffect(()=>{api.get('/dashboard/summary').then(r=>setData(r.data)).catch(e=>setError(e.response?.data?.error||'Could not load dashboard'))},[])
  return <><PageTitle eyebrow="YOUR WORKSPACE" title="Good to see you." subtitle="Your documents, organized and ready for a conversation." action={<Link className="button primary" to="/app/chat"><Plus size={16}/> Attach PDFs in chat</Link>}/>{error&&<div className="alert">{error}</div>}<div className="stat-grid">{[["Total documents",data?.total_documents??'—',FileText,data?.total_documents === 0 ? "No documents yet" : "Files in your library"],["Ready to chat",data?.ready_documents??'—',Sparkles,"AI indexed documents"],["Conversations",data?.total_conversations??'—',MessageSquare,"Your recent sessions"]].map(([label,value,Icon,hint])=><article className="stat-card" key={label}><div className="stat-top"><span>{label}</span><Icon size={18}/></div><strong>{value}</strong><small>{hint}</small></article>)}</div><div className="section-heading"><div><h2>Recent documents</h2><p>Your latest uploads and processing status</p></div><Link className="text-link" to="/app/documents">View all <ArrowUpRight size={14}/></Link></div><div className="panel table-panel">{data?.recent_documents?.length?<table><thead><tr><th>DOCUMENT</th><th>TYPE</th><th>STATUS</th><th>ADDED</th></tr></thead><tbody>{data.recent_documents.map(d=><tr key={d.id}><td><FileText className="file-icon" size={17}/><b>{d.name}</b></td><td>{d.type.toUpperCase()}</td><td><span className={`badge ${d.status}`}>{d.status}</span></td><td>{new Date(d.created_at).toLocaleDateString()}</td></tr>)}</tbody></table>:<Empty icon={FileText} title="Your library starts here" body="Upload a document and Paperwise will make it ready to search and chat." action={<Link className="button primary" to="/app/chat"><UploadCloud size={16}/> Attach PDFs in chat</Link>}/>}</div><div className="tip-card"><span className="tip-icon"><Sparkles size={18}/></span><div><b>A little tip</b><p>Ask a focused question to get the most useful answer. Paperwise cites the documents it uses so you can check the source.</p></div><Link to="/app/chat" className="text-link">Start a chat <ArrowUpRight size={14}/></Link></div></>
}
function Empty({icon:Icon,title,body,action}) { return <div className="empty-state"><span><Icon size={23}/></span><h3>{title}</h3><p>{body}</p>{action}</div> }
function Documents() {
  const [docs,setDocs]=useState([]),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[query,setQuery]=useState(()=>new URLSearchParams(window.location.search).get('q')||'')
  const load=()=>api.get('/documents',{params:{q:query}}).then(r=>setDocs(r.data)).catch(e=>setMessage(e.response?.data?.error||'Could not load documents'))
  useEffect(()=>{load()},[query])
  async function upload(files){if(!files?.length)return;setBusy(true);setMessage('');try{const form=new FormData();[...files].forEach(f=>form.append('files',f));const {data}=await api.post('/documents',form,{headers:{'Content-Type':'multipart/form-data'}});const failed=data.filter(x=>x.error||x.status==='failed');setMessage(failed.length?`${failed.map(file => (file.name || 'File') + ' - ' + (file.error || 'Processing failed.')).join(' ')}`:`Uploaded ${data.length} file(s).`);load()}catch(e){setMessage(e.response?.data?.error||'Upload failed.')}finally{setBusy(false)}}
  async function remove(id){try{await api.delete(`/documents/${id}`);setDocs(docs.filter(d=>d.id!==id))}catch(e){setMessage(e.response?.data?.error||'Could not delete document')}}
  async function retry(id){setDocs(rows=>rows.map(doc=>doc.id===id?{...doc,status:'processing',error:null}:doc));setMessage('');try{const {data}=await api.post(`/documents/${id}/reprocess`);setDocs(rows=>rows.map(doc=>doc.id===id?data:doc));setMessage(data.status==='ready'?'Document processed and ready to chat.':data.error||'Processing failed.')}catch(e){setMessage(e.response?.data?.error||'Could not reprocess document.')}}
  return <><PageTitle eyebrow="YOUR LIBRARY" title="Documents" subtitle="Add files, track processing, and manage your knowledge base." action={<label className="button primary upload-button"><UploadCloud size={16}/>{busy?'Uploading…':'Upload files'}<input type="file" multiple accept=".pdf,.docx,.txt" onChange={e=>upload(e.target.files)}/></label>}/><div className="upload-zone" onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();upload(e.dataTransfer.files)}}><span className="upload-icon"><UploadCloud size={22}/></span><div><b>Drop your files here</b><p>PDF, DOCX or TXT · up to 16 MB per upload</p></div><label className="button secondary">Browse files<input type="file" multiple accept=".pdf,.docx,.txt" onChange={e=>upload(e.target.files)}/></label></div>{message&&<div className="alert">{message}</div>}<div className="filter-row"><div className="search-input"><Search size={16}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search documents"/></div><span className="muted">{docs.length} {docs.length===1?'document':'documents'}</span></div><div className="panel table-panel">{docs.length?<table><thead><tr><th>DOCUMENT</th><th>SIZE</th><th>STATUS</th><th>UPLOADED</th><th/></tr></thead><tbody>{docs.map(d=><tr key={d.id}><td><FileText className="file-icon" size={17}/><div><b>{d.name}</b><small className="cell-sub">{d.type.toUpperCase()}</small></div></td><td>{(d.size/1024).toFixed(0)} KB</td><td><span className={`badge ${d.status}`}>{d.status}</span>{d.error&&<small className="cell-sub error-text">{d.error}</small>}</td><td>{new Date(d.created_at).toLocaleDateString()}</td><td className="row-actions">{d.status==='failed'&&<button className="icon-button" onClick={()=>retry(d.id)} title="Retry processing"><RefreshCw size={15}/></button>}<button className="icon-button danger" onClick={()=>remove(d.id)} title="Delete document"><Trash2 size={15}/></button></td></tr>)}</tbody></table>:<Empty icon={FolderOpen} title="No documents yet" body="Upload your first PDF, DOCX or TXT file to get started."/>}</div></>
}
function History() {
  const [rows, setRows] = useState([])
  useEffect(() => { api.get('/chat/conversations').then(response => setRows(response.data)) }, [])
  return <>
    <PageTitle eyebrow="PAST CONVERSATIONS" title="Chat history" subtitle="Pick up where you left off."/>
    <div className="panel table-panel history-panel">
      {rows.length ? <table>
        <thead><tr><th>CONVERSATION</th><th>STARTED</th><th aria-label="Action"/></tr></thead>
        <tbody>{rows.map(conversation => {
          const select = () => sessionStorage.setItem('conversation', conversation.id)
          return <tr key={conversation.id}>
            <td><Link className="history-title" to="/app/chat" onClick={select}><MessageSquare className="file-icon" size={17}/><b>{conversation.title}</b></Link></td>
            <td>{new Date(conversation.created_at).toLocaleDateString()}</td>
            <td><Link className="text-link" to="/app/chat" onClick={select} aria-label={`Open ${conversation.title}`}>Open <ArrowUpRight size={14}/></Link></td>
          </tr>
        })}</tbody>
      </table> : <Empty icon={MessageSquare} title="No conversations yet" body="Your saved conversations will show up here." action={<Link className="button primary" to="/app/chat">Start a chat</Link>}/>}
    </div>
  </>
}
function Summaries(){const [docs,setDocs]=useState([]),[selected,setSelected]=useState(''),[detailed,setDetailed]=useState(false),[summary,setSummary]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');useEffect(()=>{api.get('/documents').then(r=>setDocs(r.data.filter(d=>d.status==='ready'))).catch(()=>setError('Could not load documents.'))},[]);async function create(){if(!selected)return;setBusy(true);setError('');setSummary('');try{const {data}=await api.post('/ai/summarize',{document_id:Number(selected),detailed});setSummary(data.summary)}catch(e){setError(e.response?.data?.error||'Could not create summary.')}finally{setBusy(false)}}return <><PageTitle eyebrow="DOCUMENT INSIGHTS" title="Summaries" subtitle="Turn a long document into clear key points."/><div className="panel settings-card summary-panel"><div className="panel-heading"><h2>Summarize a document</h2><p>Summaries are generated from the actual extracted text in your file.</p></div>{docs.length?<><label className="summary-label">DOCUMENT<select value={selected} onChange={e=>setSelected(e.target.value)}><option value="">Choose a processed document</option>{docs.map(d=><option key={d.id} value={d.id}>{d.name}</option>)}</select></label><label className="check-label"><input type="checkbox" checked={detailed} onChange={e=>setDetailed(e.target.checked)}/> Detailed summary with key points and definitions</label><button className="button primary" disabled={!selected||busy} onClick={create}><Sparkles size={15}/>{busy?'Creating summary…':'Create summary'}</button></>:<Empty icon={BookOpen} title="No processed documents" body="Upload a document and wait for processing before requesting a summary." action={<Link className="button primary" to="/app/documents">Go to documents</Link>}/>}</div>{error&&<div className="alert">{error}</div>}{summary&&<article className="panel summary-result"><div className="message-label"><SPARKLE_LABEL/> GENERATED FROM YOUR DOCUMENT</div><h2>{docs.find(d=>String(d.id)===selected)?.name}</h2><div className="summary-text">{summary}</div></article>}</>}
function SettingsPage(){const {user}=useAuth();return <><PageTitle eyebrow="YOUR ACCOUNT" title="Settings" subtitle="Your profile and workspace security."/><div className="settings-grid"><div className="panel settings-card"><div className="panel-heading"><h2>Profile</h2><p>Account information for this workspace</p></div><div className="profile-large"><div className="avatar large">{user?.name?.[0]?.toUpperCase()||'U'}</div><div><b>{user?.name}</b><p>{user?.email}</p></div></div><div className="info-row"><span>Full name</span><b>{user?.name}</b></div><div className="info-row"><span>Email address</span><b>{user?.email}</b></div></div><div className="panel settings-card"><div className="panel-heading"><h2>Privacy & security</h2><p>How your documents are handled</p></div><div className="privacy-row"><ShieldCheck size={19}/><div><b>Private to your account</b><p>Your documents and conversations are scoped to your account.</p></div></div><div className="privacy-row"><Sparkles size={19}/><div><b>Grounded AI answers</b><p>Responses use retrieved excerpts and include source references.</p></div></div></div></div></>}
function AuthPage({mode}){const [name,setName]=useState(''),[email,setEmail]=useState(''),[password,setPassword]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);const {login}=useAuth();const navigate=useNavigate();async function submit(e){e.preventDefault();setBusy(true);setError('');try{await login(mode==='register'?'/auth/register':'/auth/login',{...(mode==='register'?{name}:{}),email,password});navigate('/app')}catch(e){setError(e.response?.data?.error||'Could not connect to the server.')}finally{setBusy(false)}}return <div className="auth-page"><div className="auth-decoration"><Link className="brand" to="/"><span className="brand-mark"><Sparkles size={19}/></span><span>paperwise<span className="brand-dot">.</span><small>DOCUMENT INTELLIGENCE</small></span></Link><div className="auth-quote"><span>“</span><h2>Your knowledge is already in your documents. Let’s make it easier to find.</h2><p>PRIVATE BY DESIGN · GROUNDED IN YOUR SOURCES</p></div><div className="auth-foot">Thoughtful answers start with the right context.</div></div><div className="auth-form-wrap"><form className="auth-form" onSubmit={submit}><div className="eyebrow">{mode==='register'?'GET STARTED':'WELCOME BACK'}</div><h1>{mode==='register'?'Create your account':'Sign in to Paperwise'}</h1><p>{mode==='register'?'Your documents, ready for a conversation.':'Pick up where your documents left off.'}</p>{error&&<div className="alert">{error}</div>}{mode==='register'&&<label>Full name<input required value={name} onChange={e=>setName(e.target.value)} placeholder="Your name"/></label>}<label>Email address<input required type="email" value={email} onChange={e=>setEmail(e.target.value)} placeholder="you@example.com"/></label><label>Password<input required minLength="8" type="password" value={password} onChange={e=>setPassword(e.target.value)} placeholder="At least 8 characters"/></label><button className="button primary full auth-submit" disabled={busy}>{busy?'Please wait…':mode==='register'?'Create account':'Sign in'}<ArrowUpRight size={16}/></button><div className="auth-switch">{mode==='register'?'Already have an account?':'New to Paperwise?'} <Link to={mode==='register'?'/login':'/register'}>{mode==='register'?'Sign in':'Create an account'}</Link></div><div className="auth-note"><ShieldCheck size={14}/> Your workspace is private and encrypted in transit.</div></form></div></div>}
function Landing(){return <div className="landing"><nav className="landing-nav"><Link className="brand" to="/"><span className="brand-mark"><Sparkles size={19}/></span><span>paperwise<span className="brand-dot">.</span><small>DOCUMENT INTELLIGENCE</small></span></Link><div><Link to="/login" className="landing-login">Sign in</Link><Link to="/register" className="button primary">Get started <ArrowUpRight size={15}/></Link></div></nav><section className="hero"><div className="hero-copy"><div className="hero-tag"><span/> YOUR DOCUMENTS, IN CONVERSATION</div><h1>Good answers<br/>start <em>with context.</em></h1><p>Bring your documents together and ask what matters. Get clear answers grounded in your own files, with sources you can follow.</p><div className="hero-actions"><Link className="button primary large-button" to="/register">Get started for free <ArrowUpRight size={16}/></Link><span>No credit card required</span></div><div className="hero-trust"><ShieldCheck size={15}/> Private by design <i/> Source-backed answers <i/> Your files stay yours</div></div><div className="hero-art"><div className="ambient ambient-one"/><div className="ambient ambient-two"/><div className="mock-window"><div className="mock-head"><div className="mock-dots"><i/><i/><i/></div><span>paperwise / your workspace</span><Sparkles size={15}/></div><div className="mock-sidebar"><div className="mock-nav active"><LayoutDashboard size={13}/> Overview</div><div className="mock-nav"><FolderOpen size={13}/> Documents</div><div className="mock-nav"><MessageSquare size={13}/> AI chat</div><div className="mock-mini-label">YOUR LIBRARY</div><div className="mock-file"><span className="mini-pdf">PDF</span><span>Q3 strategy brief</span></div><div className="mock-file"><span className="mini-doc">DOC</span><span>Customer interviews</span></div><div className="mock-file"><span className="mini-txt">TXT</span><span>Launch notes</span></div></div><div className="mock-content"><div className="mock-welcome">Your knowledge, ready.</div><div className="mock-metrics"><div><small>DOCUMENTS</small><b>12</b></div><div><small>READY TO CHAT</small><b>10</b></div></div><div className="mock-chat"><div className="mock-avatar"><Sparkles size={12}/></div><div><small>YOUR QUESTION</small><p>What are our key priorities for Q3?</p></div></div><div className="mock-answer"><div className="mock-answer-label"><Sparkles size={13}/> PAPERWISE <span>· grounded in 3 sources</span></div><p>Based on your strategy brief, the main priorities are improving customer retention, expanding the self-service experience, and reducing onboarding time.</p><div className="mock-source"><FileText size={12}/> Q3 strategy brief <span>p. 4</span></div></div><div className="mock-input">Ask a question about your documents… <span><Send size={12}/></span></div></div></div><div className="float-card float-source"><span className="float-icon"><FileText size={15}/></span><span><b>Source found</b><small>Q3 strategy brief · p. 4</small></span><span className="float-check">✓</span></div><div className="float-card float-private"><ShieldCheck size={15}/><span>Your files stay yours</span></div></div></section><section className="landing-bottom"><div><span className="bottom-mark">01</span><span><b>Bring your files</b><small>PDF, Word, and plain text.</small></span></div><div><span className="bottom-mark">02</span><span><b>Ask in plain language</b><small>No searching page by page.</small></span></div><div><span className="bottom-mark">03</span><span><b>Check every source</b><small>Answers point back to your files.</small></span></div><span className="landing-footnote">MADE FOR THINKING CLEARLY</span></section></div>}

function SPARKLE_LABEL(){return <Sparkles size={12}/>}
export default function App() {
  const [user, setUser] = useState(null)
  const [checkingSession, setCheckingSession] = useState(true)
  const [logoutError, setLogoutError] = useState('')
  const { pathname } = useLocation()

  useEffect(() => {
    const controller = new AbortController()
    localStorage.removeItem('access_token')
    api.get('/auth/me', { headers: sessionHeaders, signal: controller.signal })
      .then(({ data: { csrf_token, ...profile } }) => {
        setCsrfToken(csrf_token)
        setUser(profile)
      })
      .catch(() => {})
      .finally(() => {
        if (!controller.signal.aborted) setCheckingSession(false)
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const id = api.interceptors.response.use(undefined, error => {
      if (error.response?.status === 401 && !error.config?.url?.startsWith('/auth/')) {
        setCsrfToken(null)
        setUser(null)
      }
      return Promise.reject(error)
    })
    return () => api.interceptors.response.eject(id)
  }, [])

  async function login(path, body) {
    const { data } = await api.post(path, body, { headers: sessionHeaders })
    setCsrfToken(data.csrf_token)
    setLogoutError('')
    setUser(data.user)
  }

  async function logout() {
    try {
      await api.post('/auth/logout')
    } catch (error) {
      if (error.response?.status !== 401) {
        setLogoutError('Could not sign out. Try again.')
        return
      }
    }
    setCsrfToken(null)
    setUser(null)
    setLogoutError('')
  }

  if (checkingSession && pathname !== '/') return <p role="status">Checking your session?</p>

  return (
    <Auth.Provider value={{ user, login, logout, logoutError }}>
      <Routes>
        <Route path="/" element={user ? <Navigate to="/app" /> : <Landing />} />
        <Route path="/login" element={user ? <Navigate to="/app" /> : <AuthPage key="login" mode="login" />} />
        <Route path="/register" element={user ? <Navigate to="/app" /> : <AuthPage key="register" mode="register" />} />
        <Route path="/app" element={<Protected><Shell><Dashboard /></Shell></Protected>} />
        <Route path="/app/documents" element={<Protected><Shell><Documents /></Shell></Protected>} />
        <Route path="/app/chat" element={<Protected><Shell><Chat PageTitle={PageTitle} Empty={Empty} /></Shell></Protected>} />
        <Route path="/app/summaries" element={<Protected><Shell><Summaries /></Shell></Protected>} />
        <Route path="/app/history" element={<Protected><Shell><History /></Shell></Protected>} />
        <Route path="/app/settings" element={<Protected><Shell><SettingsPage /></Shell></Protected>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Auth.Provider>
  )
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { FileText, MessageSquare, Paperclip, Plus, RefreshCw, Send, Sparkles, Trash2, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import api from './services/api'
import { documentStatus, isProcessing, prepareUploads, useDocumentPolling } from './services/documentJobs'

const conversationsUrl = '/chat/conversations'
const attachmentUrl = id => `${conversationsUrl}/${id}/attachments`
const messageFor = (error, fallback) => error.response?.data?.error || fallback
const sizeLabel = bytes => bytes >= 1024 ** 2 ? `${(bytes / 1024 ** 2).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`

export default function Chat({ PageTitle, Empty }) {
  const [conversations, setConversations] = useState([])
  const [active, setActive] = useState(null)
  const [messages, setMessages] = useState([])
  const [attachments, setAttachments] = useState([])
  const [pending, setPending] = useState([])
  const [library, setLibrary] = useState(null)
  const [question, setQuestion] = useState('')
  const [operation, setOperation] = useState('loading')
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(null)
  const [deleting, setDeleting] = useState(0)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState('')
  const filePicker = useRef(null)
  const dragDepth = useRef(0)
  const messageEnd = useRef(null)
  const hiddenDocuments = useRef(new Set())
  const locked = Boolean(operation)
  const navigating = locked || uploading || deleting > 0
  const refreshAttachments = useCallback(rows =>
    setAttachments(rows.filter(row => !hiddenDocuments.current.has(row.id))), [])
  useDocumentPolling(active ? attachmentUrl(active) : null,
    !uploading && attachments.some(isProcessing), refreshAttachments)

  useEffect(() => {
    async function load() {
      try {
        const { data } = await api.get(conversationsUrl)
        setConversations(data)
        const requested = Number(sessionStorage.getItem('conversation'))
        const selected = data.find(row => row.id === requested) || data[0]
        if (selected) await open(selected.id)
      } catch (err) {
        setError(messageFor(err, 'Could not load conversations.'))
      } finally {
        setOperation('')
      }
    }
    load()
  }, [])

  useEffect(() => { messageEnd.current?.scrollIntoView?.({ block: 'nearest' }) }, [messages, operation])

  async function open(id) {
    setOperation('loading')
    setError('')
    try {
      const { data } = await api.get(`${conversationsUrl}/${id}`)
      setActive(id)
      setMessages(data.messages || [])
      setAttachments(data.attachments || [])
      setPending([])
      setLibrary(null)
      sessionStorage.setItem('conversation', id)
    } catch (err) {
      setError(messageFor(err, 'Could not load this conversation.'))
    } finally {
      setOperation('')
    }
  }

  async function create() {
    const { data } = await api.post(conversationsUrl, {})
    setActive(data.id)
    setMessages([])
    setAttachments([])
    setPending([])
    setLibrary(null)
    setConversations(rows => [data, ...rows])
    sessionStorage.setItem('conversation', data.id)
    return data.id
  }

  async function perform(name, action, fallback) {
    if (locked) return
    setOperation(name)
    setError('')
    try {
      await action()
    } catch (err) {
      setError(messageFor(err, fallback))
    } finally {
      setOperation('')
    }
  }

  function updateAttachment(document) {
    setAttachments(rows => [...rows.filter(row => row.id !== document.id), document])
  }

  function upload(files) {
    if (!files?.length || locked || uploading) return
    const entries = prepareUploads(files, true)
    const valid = entries.filter(entry => !entry.error)
    setPending(entries)
    if (!valid.length) return
    setUploading(true)
    setUploadProgress(null)
    setError('')
    return (async () => {
      try {
        const id = active || await create()
        setPending(entries)
        if (!valid.length) return
        const form = new FormData()
        valid.forEach(entry => form.append('files', entry.file))
        const { data } = await api.post(attachmentUrl(id), form, {
          onUploadProgress: event => {
            if (event.total) setUploadProgress(Math.floor(100 * event.loaded / event.total))
            if (event.total && event.loaded >= event.total) {
              setPending(rows => rows.map(row => row.error ? row : { ...row, status: 'uploaded' }))
            }
          },
        })
        let resultIndex = 0
        const rejected = []
        for (const entry of entries) {
          if (entry.error) {
            rejected.push(entry)
            continue
          }
          const result = data[resultIndex++]
          if (result?.id) updateAttachment(result)
          else rejected.push({ ...entry, status: 'failed', error: result?.error || 'Upload failed.' })
        }
        setPending(rejected)
      } catch (err) {
        const reason = messageFor(err, 'Upload failed. Select the files to retry.')
        setPending(entries.map(entry => ({ ...entry, status: 'failed', error: entry.error || reason })))
      } finally {
        setUploading(false)
      }
    })()
  }

  function send(event) {
    event.preventDefault()
    const content = question.trim()
    if (!content || (uploading && !active)) return
    return perform('sending', async () => {
      const id = active || await create()
      setQuestion('')
      setMessages(rows => [...rows, { role: 'user', content }])
      try {
        const { data } = await api.post(`${conversationsUrl}/${id}/messages`, { question: content })
        setMessages(rows => [...rows.slice(0, -1), data.user_message, data.answer])
        api.get(conversationsUrl).then(response => setConversations(response.data)).catch(() => {})
      } catch (err) {
        setMessages(rows => rows.slice(0, -1))
        setQuestion(value => value || content)
        throw err
      }
    }, 'Could not send your question.')
  }

  function viewPdf(documentId, pageNumber) {
    const tab = window.open('', '_blank')
    if (!tab) { setError('Allow pop-ups to open this PDF.'); return }
    tab.opener = null
    api.get(`/documents/${documentId}/pdf`, { responseType: 'blob' }).then(({ data }) => {
      const url = URL.createObjectURL(data)
      tab.location.replace(pageNumber ? `${url}#page=${pageNumber}` : url)
      setTimeout(() => URL.revokeObjectURL(url), 300000)
    }).catch(() => { tab.close(); setError('This PDF is unavailable.') })
  }

  function rename(conversation) {
    const title = window.prompt('Rename conversation', conversation.title)?.trim()
    if (!title) return
    perform('saving', async () => {
      const { data } = await api.patch(`${conversationsUrl}/${conversation.id}`, { title })
      setConversations(rows => rows.map(row => row.id === data.id ? data : row))
    }, 'Could not rename conversation.')
  }

  function removeConversation(conversation) {
    if (!window.confirm(`Delete “${conversation.title}”?`)) return
    perform('saving', async () => {
      await api.delete(`${conversationsUrl}/${conversation.id}`)
      setConversations(rows => rows.filter(row => row.id !== conversation.id))
      if (active === conversation.id) {
        sessionStorage.removeItem('conversation')
        setActive(null)
        setMessages([])
        setAttachments([])
        setPending([])
        setLibrary(null)
      }
    }, 'Could not delete conversation.')
  }

  async function deletePdf(document) {
    if (!window.confirm(`Permanently delete “${document.name}” from your library and every conversation?`)) return
    hiddenDocuments.current.add(document.id)
    setAttachments(rows => rows.filter(row => row.id !== document.id))
    setDeleting(count => count + 1)
    try {
      await api.delete(`/documents/${document.id}`)
      setLibrary(rows => rows?.filter(row => row.id !== document.id) ?? null)
    } catch (err) {
      hiddenDocuments.current.delete(document.id)
      updateAttachment(document)
      setError(messageFor(err, 'Could not delete this PDF.'))
    } finally {
      setDeleting(count => count - 1)
    }
  }

  return <>
    <PageTitle eyebrow="YOUR ASSISTANT" title="AI chat" subtitle="Ask a general question or attach PDFs to chat with them." />
    <div className="chat-layout">
      <aside className="chat-list">
        <button className="button primary full" disabled={navigating} onClick={() => perform('saving', create, 'Could not create a conversation.')}>
          <Plus size={15} /> New conversation
        </button>
        <div className="nav-label">RECENT</div>
        {conversations.map(conversation => <div key={conversation.id} className={`conversation-row ${active === conversation.id ? 'selected' : ''}`}>
          <button className="conversation-item" disabled={navigating} onClick={() => open(conversation.id)}><MessageSquare size={15} /><span>{conversation.title}</span></button>
          <button className="conversation-action" disabled={locked} title="Rename conversation" onClick={() => rename(conversation)}>···</button>
          <button className="conversation-action delete-action" disabled={navigating} title="Delete conversation" onClick={() => removeConversation(conversation)}><Trash2 size={14} /></button>
        </div>)}
      </aside>
      <div className="chat-panel">
        <div className="chat-messages">
          {operation === 'loading' && <p role="status">Loading conversation…</p>}
          {!messages.length && operation !== 'loading' && <Empty icon={Sparkles} title="Ask Paperwise anything" body="Ask a question or attach PDFs using the paperclip." />}
          {messages.map((message, index) => <div className={`message ${message.role}`} key={message.id || `pending-message-${index}`}>
            <span className="message-avatar">{message.role === 'assistant' ? <Sparkles size={15} /> : 'Y'}</span>
            <div>
              <div className="message-label">{message.role === 'user' ? 'YOU' : message.sources?.length ? 'PAPERWISE · PDF SOURCES' : 'PAPERWISE'}</div>
              <div className="message-body">{message.role === 'assistant'
                ? <ReactMarkdown remarkPlugins={[remarkGfm]} disallowedElements={['img']}>{message.content}</ReactMarkdown>
                : message.content}
              </div>
              {message.sources?.length > 0 && <div className="source-list">{message.sources.map(source =>
                source.page_number ? <button type="button" className="source-chip" key={source.index} onClick={() => viewPdf(source.document_id, source.page_number)}>
                  <FileText size={13} />{source.document_name} · page {source.page_number}
                </button> : <span className="source-chip" key={source.index}><FileText size={13} />{source.document_name}</span>)}</div>}
            </div>
          </div>)}
          {operation === 'sending' && <div className="typing" role="status" aria-label="Generating response"><i /><i /><i /></div>}
          <div ref={messageEnd} />
        </div>
        <form className={`chat-composer ${dragging ? 'chat-dragging' : ''}`} onSubmit={send}
          onDragEnter={event => { if (!event.dataTransfer.types.includes('Files')) return; event.preventDefault(); dragDepth.current++; setDragging(true) }}
          onDragOver={event => { if (event.dataTransfer.types.includes('Files')) event.preventDefault() }}
          onDragLeave={() => { dragDepth.current = Math.max(0, dragDepth.current - 1); if (!dragDepth.current) setDragging(false) }}
          onDrop={event => { event.preventDefault(); dragDepth.current = 0; setDragging(false); upload(event.dataTransfer.files) }}>
          {error && <div role="alert" className="alert">{error}</div>}
          {uploading && <p className="attachment-progress" role="status">
            <RefreshCw size={14} /> {uploadProgress === 100 ? 'Saving PDFs…' : 'Uploading PDFs…'}
            {uploadProgress !== null && <progress max="100" value={uploadProgress} aria-label="PDF transfer progress" />}
          </p>}
          {deleting > 0 && <p role="status">Removing PDF…</p>}
          {attachments.some(isProcessing) && <p role="status">You can ask general questions while PDFs are processing.</p>}
          {dragging && <p className="attachment-progress">Drop PDFs here to attach them</p>}
          {(attachments.length > 0 || pending.length > 0) && <ul className="chat-attachments" aria-label="Attached PDFs">
            {[...attachments, ...pending].map(doc => <li className="chat-attachment" key={doc.id || `pending-${doc.index}`}>
              <FileText size={18} aria-hidden="true" />
              <div className="attachment-info">
                {doc.id && doc.status === 'ready' ? <button className="attachment-name" type="button" title={doc.name} onClick={() => viewPdf(doc.id)}>{doc.name}</button>
                  : <span className="attachment-name" title={doc.name}>{doc.name}</span>}
                <small>{sizeLabel(doc.size)} · {documentStatus(doc.status)}</small>
                {doc.error && <small className="error-text">{doc.error}</small>}
              </div>
              {doc.id && doc.status === 'failed' && <button type="button" className="icon-button" aria-label={`Retry ${doc.name}`} disabled={locked} onClick={() => perform('uploading', async () => {
                const { data } = await api.post(`/documents/${doc.id}/reprocess`)
                updateAttachment(data)
              }, 'Could not retry this PDF.')}><RefreshCw size={15} /></button>}
              {doc.id && <button type="button" className="icon-button danger" aria-label={`Permanently delete ${doc.name}`} title="Delete from library and all conversations" disabled={locked} onClick={() => deletePdf(doc)}><Trash2 size={15} /></button>}
              <button type="button" className="icon-button" aria-label={`Remove ${doc.name}`} disabled={locked} onClick={() => doc.id
                ? perform('saving', async () => { await api.delete(`${attachmentUrl(active)}/${doc.id}`); setAttachments(rows => rows.filter(row => row.id !== doc.id)) }, 'Could not remove this PDF.')
                : setPending(rows => rows.filter(row => row.index !== doc.index))}><X size={16} /></button>
            </li>)}
          </ul>}
          {library && <div className="chat-library">
            <label>Attach from your library <select disabled={locked} value="" onChange={event => {
              const documentId = event.target.value
              if (!documentId) return
              perform('saving', async () => {
                const id = active || await create()
                const { data } = await api.put(`${attachmentUrl(id)}/${documentId}`)
                updateAttachment(data)
                setLibrary(null)
              }, 'Could not attach this PDF.')
            }}><option value="">Choose a PDF</option>{library.filter(doc => !attachments.some(row => row.id === doc.id)).map(doc => <option key={doc.id} value={doc.id}>{doc.name}</option>)}</select></label>
          </div>}
          <div className="chat-input-row">
            <input hidden type="file" multiple accept=".pdf,application/pdf" ref={filePicker} aria-label="Choose PDF attachments" onChange={event => { upload(event.target.files); event.target.value = '' }} />
            <button type="button" className="icon-button chat-attach-button" aria-label="Attach PDFs" title="Attach PDFs" disabled={locked || uploading} onClick={() => filePicker.current?.click()}><Paperclip size={20} /></button>
            <textarea value={question} onChange={event => setQuestion(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) send(event) }} aria-label="Your question" placeholder="Ask a question…" maxLength={4000} rows="1" />
            <button className="send-button" disabled={!question.trim() || locked || (uploading && !active)} aria-label="Send" title="Send"><Send size={16} /></button>
          </div>
          <button type="button" className="chat-library-toggle" disabled={locked} onClick={() => library ? setLibrary(null) : perform('loading-library', async () => { const { data } = await api.get('/documents?type=pdf'); setLibrary(data) }, 'Could not load your PDFs.')}>
            {library ? 'Close library picker' : 'Attach from library'}
          </button>
        </form>
      </div>
    </div>
  </>
}

import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:5000/api',
  withCredentials: true,
})

let csrfToken = null
export const sessionHeaders = { 'X-Paperwise-Session': 'cookie' }

export function setCsrfToken(token) {
  csrfToken = token
}

export async function streamMessage(path, question, signal, onDelta) {
  let body
  try {
    const response = await api.post(path, { question }, {
      adapter: 'fetch',
      responseType: 'stream',
      headers: { Accept: 'application/x-ndjson' },
      signal,
    })
    body = response.data
  } catch (error) {
    if (!error.response) throw error
    const data = await new Response(error.response.data).json().catch(() => null)
    throw new Error(data?.error || 'Could not send your question.')
  }
  const reader = body.pipeThrough(new TextDecoderStream()).getReader()
  let pending = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) throw new Error('The response ended early. Please retry.')
      pending += value
      let newline
      while ((newline = pending.indexOf('\n')) >= 0) {
        const event = JSON.parse(pending.slice(0, newline))
        pending = pending.slice(newline + 1)
        if (event.type === 'delta') onDelta(event.content)
        if (event.type === 'done') return event
        if (event.type === 'error') throw new Error(event.error)
      }
    }
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

api.interceptors.request.use((config) => {
  if (csrfToken && ['post', 'put', 'patch', 'delete'].includes(config.method)) {
    config.headers['X-CSRF-TOKEN'] = csrfToken
  }
  return config
})

export default api

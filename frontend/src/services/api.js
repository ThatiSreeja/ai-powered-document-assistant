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

api.interceptors.request.use((config) => {
  if (csrfToken && ['post', 'put', 'patch', 'delete'].includes(config.method)) {
    config.headers['X-CSRF-TOKEN'] = csrfToken
  }
  return config
})

export default api

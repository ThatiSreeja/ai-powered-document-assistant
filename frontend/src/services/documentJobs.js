import { useEffect } from 'react'
import api from './api'

export const isProcessing = document => ['uploaded', 'processing', 'extracting', 'embedding', 'indexing'].includes(document.status)

export const documentStatus = status => ({
  uploading: 'Uploading',
  uploaded: 'Uploaded',
  processing: 'Processing',
  extracting: 'Extracting text',
  embedding: 'Generating embeddings',
  indexing: 'Indexing document',
  ready: 'Ready',
  failed: 'Failed',
})[status] || status

export function prepareUploads(files, pdfOnly = false) {
  const seen = new Set()
  let count = 0
  let bytes = 0
  return Array.from(files, (file, index) => {
    const key = JSON.stringify([file.name, file.size, file.lastModified, file.type])
    let error = null
    const validType = pdfOnly ? /\.pdf$/i : /\.(pdf|docx|txt)$/i
    if (!validType.test(file.name)) error = pdfOnly ? 'Only PDFs can be attached.' : 'Choose a PDF, DOCX, or TXT file.'
    else if (!file.size) error = 'This file is empty.'
    else if (seen.has(key)) error = 'This file was already selected.'
    else if (count === 10) error = 'Choose up to 10 files per upload.'
    else if (bytes + file.size >= 16 * 1024 ** 2) error = 'The combined upload must be under 16 MB.'
    if (!error) {
      seen.add(key)
      count++
      bytes += file.size
    }
    return { file, index, name: file.name, size: file.size, status: error ? 'failed' : 'uploading', error }
  })
}

export function useDocumentPolling(url, enabled, onUpdate, query = '') {
  useEffect(() => {
    if (!url || !enabled) return
    const controller = new AbortController()
    let timer
    async function poll() {
      try {
        const { data } = await api.get(url, { signal: controller.signal, params: { q: query } })
        if (!controller.signal.aborted) onUpdate(data)
      } catch {
        // A temporary network error should leave the last known stage visible.
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(poll, 2500)
      }
    }
    timer = setTimeout(poll, 2500)
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [url, enabled, onUpdate, query])
}

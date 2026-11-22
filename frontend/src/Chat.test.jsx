import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import Chat from './Chat'
import api from './services/api'

vi.mock('./services/api', () => ({ default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }))

afterEach(() => {
  cleanup()
  sessionStorage.clear()
  vi.restoreAllMocks()
})

it('keeps chat usable during transfer and polls attachment processing', async () => {
  const conversation = { id: 1, title: 'Test chat' }
  const document = { id: 2, name: 'guide.pdf', size: 5, status: 'uploaded' }
  let finishUpload
  const uploadResponse = new Promise(resolve => { finishUpload = resolve })
  api.get.mockImplementation(async url => {
    if (url.endsWith('/attachments')) return { data: [{ ...document, status: 'ready' }] }
    if (url.endsWith('/1')) return { data: { messages: [], attachments: [] } }
    return { data: [conversation] }
  })
  api.post.mockImplementation((url, _body, options) => {
    if (url.endsWith('/attachments')) {
      options.onUploadProgress({ loaded: 5, total: 10 })
      return uploadResponse
    }
    return Promise.resolve({ data: {
      user_message: { id: 1, role: 'user', content: 'Hello' },
      answer: { id: 2, role: 'assistant', content: 'Hi there!' },
    } })
  })
  render(<Chat PageTitle={() => null} Empty={() => null} />)
  await screen.findByRole('button', { name: 'Test chat' })
  fireEvent.change(screen.getByLabelText('Choose PDF attachments'), {
    target: { files: [new File(['%PDF-'], 'guide.pdf', { type: 'application/pdf' })] },
  })
  expect(await screen.findByRole('progressbar')).toHaveProperty('value', 50)
  fireEvent.change(screen.getByLabelText('Your question'), { target: { value: 'Hello' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
  expect(await screen.findByText('Hi there!')).toBeTruthy()
  finishUpload({ data: [document] })
  expect(await screen.findByText(/can ask general questions/i)).toBeTruthy()
  expect(await screen.findByRole('button', { name: 'guide.pdf' }, { timeout: 5000 })).toBeTruthy()
})

import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from './App'

vi.mock('./services/api', () => ({
  default: {
    get: vi.fn().mockRejectedValue({ response: { status: 401 } }),
    interceptors: { response: { use: vi.fn(), eject: vi.fn() } },
  },
  sessionHeaders: {},
  setCsrfToken: vi.fn(),
}))

afterEach(() => { cleanup(); localStorage.clear() })

describe('Paperwise entry experience', () => {
  it('shows the landing page and signup action when signed out', () => {
    render(<MemoryRouter><App /></MemoryRouter>)
    expect(screen.getByText(/Good answers/i)).toBeTruthy()
    expect(screen.getByRole('link', { name: /Get started for free/i })).toBeTruthy()
  })

  it('protects workspace routes when signed out', async () => {
    render(<MemoryRouter initialEntries={['/app']}><App /></MemoryRouter>)
    expect(await screen.findByText(/Sign in to Paperwise/i)).toBeTruthy()
  })
})

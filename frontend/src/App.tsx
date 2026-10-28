import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { ProjectsPage } from './pages/ProjectsPage'
import { ShortsPage } from './pages/ShortsPage'
import { EditorPage } from './pages/EditorPage'

const AssetsPlaceholder: React.FC = () => (
  <div style={{ padding: '24px 32px' }}>
    <h1 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text)', marginBottom: '8px' }}>
      Assets
    </h1>
    <p style={{ color: 'var(--muted)', fontSize: '13px' }}>Asset library and stock media search.</p>
  </div>
)

const TemplatesPlaceholder: React.FC = () => (
  <div style={{ padding: '24px 32px' }}>
    <h1 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text)', marginBottom: '8px' }}>
      Templates
    </h1>
    <p style={{ color: 'var(--muted)', fontSize: '13px' }}>Caption and editing presets.</p>
  </div>
)

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<Navigate to="/projects" replace />} />
          <Route path="projects" element={<ProjectsPage />} />
          <Route path="projects/:videoId" element={<ShortsPage />} />
          <Route path="shorts" element={<ShortsPage />} />
          <Route path="assets" element={<AssetsPlaceholder />} />
          <Route path="templates" element={<TemplatesPlaceholder />} />
        </Route>
        <Route path="/editor/:timelineId" element={<EditorPage />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App

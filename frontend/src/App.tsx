import { useEffect, useState } from 'react'
import { NewProject } from './pages/NewProject'
import { DebugPage } from './pages/DebugPage'
import { api } from './api'
import './index.css'

type NavTab = 'new-project' | 'projects' | 'caption-styles' | 'settings' | 'debug'

export function App() {
  const [activeTab, setActiveTab] = useState<NavTab>(() => {
    if (window.location.pathname === '/debug') return 'debug'
    if (window.location.pathname === '/projects') return 'projects'
    return 'new-project'
  })

  // Synchronize browser history / URL
  useEffect(() => {
    const handlePopState = () => {
      if (window.location.pathname === '/debug') {
        setActiveTab('debug')
      } else if (window.location.pathname === '/projects') {
        setActiveTab('projects')
      } else {
        setActiveTab('new-project')
      }
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  const handleTabChange = (tab: NavTab) => {
    setActiveTab(tab)
    const targetUrl =
      tab === 'debug' ? '/debug' : tab === 'projects' ? '/projects' : '/'
    window.history.pushState({}, '', targetUrl)
  }

  return (
    <div className="app-container">
      {/* 220px Left Sidebar */}
      <aside className="sidebar" aria-label="Main Navigation">
        <div className="logo" tabIndex={0}>
          <span>ClipForge</span>
          <span className="logo-accent">AI</span>
        </div>

        <nav>
          <ul className="nav-list">
            <li>
              <button
                type="button"
                className={`nav-item ${activeTab === 'new-project' ? 'active' : ''}`}
                id="nav-new-project-btn"
                onClick={() => handleTabChange('new-project')}
              >
                <span className="nav-item-icon">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="12" y1="8" x2="12" y2="16" />
                    <line x1="8" y1="12" x2="16" y2="12" />
                  </svg>
                </span>
                <span>New project</span>
              </button>
            </li>

            <li>
              <button
                type="button"
                className={`nav-item ${activeTab === 'projects' ? 'active' : ''}`}
                id="nav-projects-btn"
                onClick={() => handleTabChange('projects')}
              >
                <span className="nav-item-icon">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                  </svg>
                </span>
                <span>Projects</span>
              </button>
            </li>

            <li>
              <button
                type="button"
                className={`nav-item ${activeTab === 'caption-styles' ? 'active' : ''}`}
                id="nav-caption-styles-btn"
                onClick={() => handleTabChange('caption-styles')}
              >
                <span className="nav-item-icon">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M4 7V4h16v3" />
                    <path d="M9 20h6" />
                    <path d="M12 4v16" />
                  </svg>
                </span>
                <span>Caption styles</span>
              </button>
            </li>

            <li>
              <button
                type="button"
                className={`nav-item ${activeTab === 'settings' ? 'active' : ''}`}
                id="nav-settings-btn"
                onClick={() => handleTabChange('settings')}
              >
                <span className="nav-item-icon">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="3" />
                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
                  </svg>
                </span>
                <span>Settings</span>
              </button>
            </li>
          </ul>
        </nav>

        <div className="sidebar-footer">
          <button
            type="button"
            className={`nav-item ${activeTab === 'debug' ? 'active' : ''}`}
            id="nav-debug-console-btn"
            style={{ fontSize: '12px' }}
            onClick={() => handleTabChange('debug')}
          >
            <span className="nav-item-icon">&#x2699;</span>
            <span>Debug Console</span>
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="main-content" id="main-content-region">
        {activeTab === 'new-project' && <NewProject />}

        {activeTab === 'projects' && (
          <div>
            <header className="page-header">
              <h1 className="page-title">Projects</h1>
              <p className="page-subtitle">Manage your imported videos and clip generation history.</p>
            </header>
            <div className="card">
              <p style={{ color: 'var(--muted)' }}>
                Your project history is also shown in the Recent projects section under{' '}
                <a
                  href="/"
                  style={{ color: 'var(--accent)', textDecoration: 'underline' }}
                  onClick={(e) => {
                    e.preventDefault()
                    handleTabChange('new-project')
                  }}
                >
                  New project
                </a>
                .
              </p>
            </div>
          </div>
        )}

        {activeTab === 'caption-styles' && (
          <div>
            <header className="page-header">
              <h1 className="page-title">Caption styles</h1>
              <p className="page-subtitle">Customize typographic fonts, karaoke highlights, and animations.</p>
            </header>
            <div className="card">
              <p style={{ color: 'var(--muted)' }}>
                Preset styles are loaded directly from <code>/api/presets</code> during clip editing.
              </p>
            </div>
          </div>
        )}

        {activeTab === 'settings' && (
          <div>
            <header className="page-header">
              <h1 className="page-title">Settings</h1>
              <p className="page-subtitle">Configure backend connectivity, API keys, and preferences.</p>
            </header>
            <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <strong>Backend URL:</strong> <code>{api.getBaseUrl()}</code>
              </div>
              <div>
                <strong>API Key:</strong>{' '}
                <code>{import.meta.env.VITE_API_KEY ? 'Configured in .env' : 'None (Open mode)'}</code>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'debug' && <DebugPage />}
      </main>
    </div>
  )
}

export default App

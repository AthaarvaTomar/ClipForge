import React from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { Folder, Film, Layers, LayoutTemplate } from 'lucide-react'

export const AppShell: React.FC = () => {
  const location = useLocation()
  const isEditor = location.pathname.startsWith('/editor')

  return (
    <div className="app-shell">
      {/* 232px Left Sidebar */}
      <aside className="sidebar" aria-label="Main Navigation">
        <div>
          {/* Logo Mark + Title */}
          <div className="sidebar-header">
            <svg
              width="20"
              height="20"
              viewBox="0 0 20 20"
              aria-hidden="true"
              className="logo-svg"
            >
              <rect width="20" height="20" rx="5" fill="#3F6BF0" />
              <path
                d="M6 14l8-8M6 6h4M10 14h4"
                stroke="#fff"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
            <span className="logo-text">ClipForge</span>
          </div>

          {/* Navigation Items */}
          <nav className="sidebar-nav">
            <NavLink
              to="/projects"
              className={({ isActive }) =>
                `nav-link ${isActive || location.pathname === '/' ? 'active' : ''}`
              }
              id="nav-item-projects"
            >
              <Folder size={16} strokeWidth={1.5} aria-hidden="true" />
              <span>Projects</span>
            </NavLink>

            <NavLink
              to="/shorts"
              className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
              id="nav-item-shorts"
            >
              <Film size={16} strokeWidth={1.5} aria-hidden="true" />
              <span>Shorts</span>
            </NavLink>

            <NavLink
              to="/assets"
              className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
              id="nav-item-assets"
            >
              <Layers size={16} strokeWidth={1.5} aria-hidden="true" />
              <span>Assets</span>
            </NavLink>

            <NavLink
              to="/templates"
              className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
              id="nav-item-templates"
            >
              <LayoutTemplate size={16} strokeWidth={1.5} aria-hidden="true" />
              <span>Templates</span>
            </NavLink>
          </nav>
        </div>

        {/* Storage Meter at the Bottom */}
        <div className="sidebar-footer">
          <div className="storage-labels">
            <span className="storage-title">Storage</span>
            <span className="storage-value mono">18.4 / 50 GB</span>
          </div>
          <div
            className="storage-bar-track"
            role="progressbar"
            aria-valuenow={18.4}
            aria-valuemin={0}
            aria-valuemax={50}
            aria-label="Storage usage"
          >
            <div className="storage-bar-fill" style={{ width: '36.8%' }} />
          </div>
        </div>
      </aside>

      {/* Main Viewport */}
      <main className="main-viewport" id="main-content">
        {isEditor && (
          <div className="desktop-only-warning" aria-live="polite">
            <p>Open on a larger screen (min width 1100px) to access the Timeline Editor.</p>
          </div>
        )}
        <Outlet />
      </main>
    </div>
  )
}

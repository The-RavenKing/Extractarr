import { useState, useEffect } from 'react';
import { Settings, RefreshCw, Power, Activity, HardDrive, Server, Video, Tv, Clock, Terminal, Shield, Save, Music, Sun, Moon, Coffee, ExternalLink, Download } from 'lucide-react';
import logo from './assets/logo2.png';

interface LogEntry {
  ts: number;
  msg: string;
  level: string;
}

interface WorkflowState {
  running: boolean;
  status: string;
  percent: number;
  message: string;
  start_time: number | null;
  end_time: number | null;
  exit_code: number | null;
  logs: LogEntry[];
}

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [status, setStatus] = useState<WorkflowState | null>(null);
  const [config, setConfig] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [importLoading, setImportLoading] = useState(false);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [theme, setTheme] = useState(localStorage.getItem('theme') || 'dark');

  useEffect(() => {
    if (theme === 'light') {
      document.body.classList.add('light-theme');
    } else {
      document.body.classList.remove('light-theme');
    }
    localStorage.setItem('theme', theme);
  }, [theme]);

  const toggleTheme = () => setTheme(theme === 'dark' ? 'light' : 'dark');

  useEffect(() => {
    fetchStatus();
    fetchConfig();
    const interval = setInterval(fetchStatus, 3000);
    return () => clearInterval(interval);
  }, []);

  const fetchStatus = async () => {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      setStatus(data);
    } catch (e) {
      console.error("Failed to fetch status", e);
    }
  };

  const fetchConfig = async () => {
    try {
      const res = await fetch('/api/config');
      const data = await res.json();
      setConfig(data);
    } catch (e) {
      console.error("Failed to fetch config", e);
    }
  };

  const handleRun = async () => {
    try {
      setLoading(true);
      await fetch('/api/run', { method: 'POST' });
      fetchStatus();
    } catch (e) {
      console.error("Failed to run workflow", e);
    } finally {
      setLoading(false);
    }
  };

  const handleTriggerImports = async () => {
    try {
      setImportLoading(true);
      await fetch('/api/trigger-imports', { method: 'POST' });
      fetchStatus();
    } catch (e) {
      console.error("Failed to trigger imports", e);
    } finally {
      setImportLoading(false);
    }
  };

  const handleInputChange = (path: string, value: any) => {
    const newConfig = { ...config };
    const parts = path.split('.');
    let current = newConfig;
    for (let i = 0; i < parts.length - 1; i++) {
      current = current[parts[i]];
    }
    current[parts[parts.length - 1]] = value;
    setConfig(newConfig);
  };

  const saveSettings = async () => {
    try {
      setLoading(true);
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      if (res.ok) {
        setSaveStatus('Settings saved successfully!');
        setTimeout(() => setSaveStatus(null), 3000);
      }
    } catch (e) {
      setSaveStatus('Failed to save settings');
    } finally {
      setLoading(false);
    }
  };

  const renderDashboard = () => (
    <div className="tab-content fade-in">
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-header">
            <Activity className="stat-icon" />
            <span>Workflow Status</span>
          </div>
          <div className={`stat-value ${status?.running ? 'active' : ''}`}>
            {status?.running ? 'Running' : 'Idle'}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-header">
            <RefreshCw className="stat-icon" />
            <span>Last Exit Code</span>
          </div>
          <div className="stat-value">{status?.exit_code !== null ? status?.exit_code : 'N/A'}</div>
        </div>
        <div className="stat-card">
          <div className="stat-header">
            <Terminal className="stat-icon" />
            <span>Current Step</span>
          </div>
          <div className="stat-value small">{status?.message || 'Ready'}</div>
        </div>
      </div>

      <div className="progress-section card">
        <div className="progress-info">
          <h3>Current Progress</h3>
          <span>{status?.percent || 0}%</span>
        </div>
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${status?.percent || 0}%` }}></div>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          <button className="run-button" disabled={status?.running || loading} onClick={handleRun} style={{ flex: 1 }}>
            {status?.running ? 'Running...' : 'Run Workflow Now'}
          </button>
          <button className="run-button" disabled={status?.running || importLoading} onClick={handleTriggerImports} style={{ flex: 1, background: 'var(--accent-secondary, #6366f1)' }}>
            <Download size={16} style={{ display: 'inline', marginRight: '0.4rem', verticalAlign: 'middle' }} />
            {(status?.running && status?.message?.includes('Arr')) ? 'Triggering...' : 'Trigger Arr Imports'}
          </button>
        </div>
      </div>

      <div className="logs-section card">
        <div className="logs-header">
          <h3>Activity Logs</h3>
          <button className="clear-logs">Clear Logs</button>
        </div>
        <div className="logs-content">
          {status?.logs.length === 0 ? (
            <div className="no-logs">No activity to show</div>
          ) : (
            status?.logs.map((log, i) => (
              <div key={i} className={`log-entry ${log.level}`}>
                <span className="log-ts">[{new Date(log.ts * 1000).toLocaleTimeString()}]</span>
                <span className="log-msg">{log.msg}</span>
              </div>
            )).reverse()
          )}
        </div>
      </div>
    </div>
  );

  const renderSettings = () => (
    <div className="tab-content fade-in">
      <div className="settings-grid">
        {/* SFTP SECTION */}
        <div className="settings-card card">
          <h3><Server /> SFTP & Remote</h3>
          <div className="form-group">
            <label>Host</label>
            <input type="text" value={config?.sftp_host || ''} onChange={(e) => handleInputChange('sftp_host', e.target.value)} />
          </div>
          <div className="form-group">
            <label>Port</label>
            <input type="number" value={config?.sftp_port || 22} onChange={(e) => handleInputChange('sftp_port', parseInt(e.target.value))} />
          </div>
          <div className="form-group">
            <label>User</label>
            <input type="text" value={config?.sftp_user || ''} onChange={(e) => handleInputChange('sftp_user', e.target.value)} />
          </div>
          <div className="form-group">
            <label>Password</label>
            <input type="password" value={config?.sftp_pass || ''} placeholder="********" onChange={(e) => handleInputChange('sftp_pass', e.target.value)} />
          </div>
          <div className="form-group">
            <label>Remote Root Path</label>
            <input type="text" value={config?.remote_path || ''} onChange={(e) => handleInputChange('remote_path', e.target.value)} />
          </div>
          <div className="form-group">
            <label>SFTP Host Key (Optional)</label>
            <input type="text" value={config?.sftp_host_key || ''} onChange={(e) => handleInputChange('sftp_host_key', e.target.value)} />
          </div>
        </div>

        {/* SMB AUTH SECTION */}
        <div className="settings-card card">
          <h3><Shield /> SMB Authentication (Windows)</h3>
          <div className="form-group">
            <label>SMB Username</label>
            <input type="text" value={config?.smb_user || ''} onChange={(e) => handleInputChange('smb_user', e.target.value)} />
          </div>
          <div className="form-group">
            <label>SMB Password</label>
            <input type="password" value={config?.smb_pass || ''} placeholder="********" onChange={(e) => handleInputChange('smb_pass', e.target.value)} />
          </div>
          <p className="hint text-xs opacity-60 mt-2">Required if your local paths are network shares (e.g. \\192.168.1.x\Share)</p>
        </div>

        {/* LOCAL PATHS SECTION */}
        <div className="settings-card card">
          <h3><HardDrive /> Lifecycle Paths</h3>
          <div className="form-group">
            <label>Stage 1: Initial Download Area</label>
            <input type="text" value={config?.local_download_path || ''} onChange={(e) => handleInputChange('local_download_path', e.target.value)} />
          </div>
          <div className="form-row">
             <div className="form-group">
                <label>TV Staging</label>
                <input type="text" value={config?.paths?.tv_source || ''} onChange={(e) => handleInputChange('paths.tv_source', e.target.value)} />
             </div>
             <div className="form-group">
                <label>TV Import (Final)</label>
                <input type="text" value={config?.paths?.tv_import || ''} onChange={(e) => handleInputChange('paths.tv_import', e.target.value)} />
             </div>
          </div>
          <div className="form-row">
             <div className="form-group">
                <label>Movies Staging</label>
                <input type="text" value={config?.paths?.movies_source || ''} onChange={(e) => handleInputChange('paths.movies_source', e.target.value)} />
             </div>
             <div className="form-group">
                <label>Movies Import (Final)</label>
                <input type="text" value={config?.paths?.movies_import || ''} onChange={(e) => handleInputChange('paths.movies_import', e.target.value)} />
             </div>
          </div>
          <div className="form-row">
             <div className="form-group">
                <label>Music Staging</label>
                <input type="text" value={config?.paths?.music_source || ''} onChange={(e) => handleInputChange('paths.music_source', e.target.value)} />
             </div>
             <div className="form-group">
                <label>Music Import (Final)</label>
                <input type="text" value={config?.paths?.music_import || ''} onChange={(e) => handleInputChange('paths.music_import', e.target.value)} />
             </div>
          </div>
        </div>

        {/* APP TRIGGERS */}
        <div className="settings-card card">
          <h3><Shield /> App API Triggers</h3>
          <div className="app-trigger-group">
            <div className="trigger-header"><Tv size={16}/> Sonarr</div>
            <input type="text" placeholder="URL" value={config?.sonarr?.url || ''} onChange={(e) => handleInputChange('sonarr.url', e.target.value)} />
            <input type="password" placeholder="API Key" value={config?.sonarr?.api_key || ''} onChange={(e) => handleInputChange('sonarr.api_key', e.target.value)} />
            <label className="checkbox-label"><input type="checkbox" checked={config?.sonarr?.enabled} onChange={(e) => handleInputChange('sonarr.enabled', e.target.checked)} /> Enabled</label>
          </div>
          <div className="app-trigger-group mt-2">
            <div className="trigger-header"><Video size={16}/> Radarr</div>
            <input type="text" placeholder="URL" value={config?.radarr?.url || ''} onChange={(e) => handleInputChange('radarr.url', e.target.value)} />
            <input type="password" placeholder="API Key" value={config?.radarr?.api_key || ''} onChange={(e) => handleInputChange('radarr.api_key', e.target.value)} />
            <label className="checkbox-label"><input type="checkbox" checked={config?.radarr?.enabled} onChange={(e) => handleInputChange('radarr.enabled', e.target.checked)} /> Enabled</label>
          </div>
          <div className="app-trigger-group mt-2">
            <div className="trigger-header"><Music size={16}/> Lidarr</div>
            <input type="text" placeholder="URL" value={config?.lidarr?.url || ''} onChange={(e) => handleInputChange('lidarr.url', e.target.value)} />
            <input type="password" placeholder="API Key" value={config?.lidarr?.api_key || ''} onChange={(e) => handleInputChange('lidarr.api_key', e.target.value)} />
            <label className="checkbox-label"><input type="checkbox" checked={config?.lidarr?.enabled} onChange={(e) => handleInputChange('lidarr.enabled', e.target.checked)} /> Enabled</label>
          </div>
        </div>

        {/* TORRENT CLIENT */}
        <div className="settings-card card">
          <h3><RefreshCw /> Torrent Cleanup</h3>
          <div className="form-group">
            <label>Client Type</label>
            <select value={config?.torrent_client?.client_type} onChange={(e) => handleInputChange('torrent_client.client_type', e.target.value)}>
              <option value="Deluge">Deluge</option>
              <option value="qBittorrent">qBittorrent</option>
            </select>
          </div>
          {config?.torrent_client?.client_type === 'Deluge' ? (
            <div className="form-row">
              <div className="form-group">
                <label>Deluge Host</label>
                <input type="text" value={config?.torrent_client?.deluge_host || ''} onChange={(e) => handleInputChange('torrent_client.deluge_host', e.target.value)} />
              </div>
              <div className="form-group">
                <label>Deluge Port</label>
                <input type="text" value={config?.torrent_client?.deluge_port || ''} onChange={(e) => handleInputChange('torrent_client.deluge_port', e.target.value)} />
              </div>
            </div>
          ) : (
            <>
              <div className="form-group">
                <label>qBit URL</label>
                <input type="text" value={config?.torrent_client?.qbit_url || ''} onChange={(e) => handleInputChange('torrent_client.qbit_url', e.target.value)} />
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label>qBit User</label>
                  <input type="text" value={config?.torrent_client?.qbit_user || ''} onChange={(e) => handleInputChange('torrent_client.qbit_user', e.target.value)} />
                </div>
                <div className="form-group">
                  <label>qBit Pass</label>
                  <input type="password" value={config?.torrent_client?.qbit_pass || ''} placeholder="********" onChange={(e) => handleInputChange('torrent_client.qbit_pass', e.target.value)} />
                </div>
              </div>
              <div className="form-row">
                <div className="form-group">
                  <label>Max Seed Time (Days)</label>
                  <input type="number" value={config?.torrent_client?.max_seed_time || 14} onChange={(e) => handleInputChange('torrent_client.max_seed_time', parseInt(e.target.value))} />
                </div>
                <div className="form-group">
                  <label>Max Seed Ratio</label>
                  <input type="number" step="0.1" value={config?.torrent_client?.max_seed_ratio || 2.0} onChange={(e) => handleInputChange('torrent_client.max_seed_ratio', parseFloat(e.target.value))} />
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      <div className="settings-actions">
        {saveStatus && <span className="save-msg fade-in">{saveStatus}</span>}
        <button className="save-button" disabled={loading} onClick={saveSettings}>
          <Save size={18} /> Save All Settings
        </button>
      </div>
    </div>
  );

  const renderSchedule = () => (
    <div className="tab-content fade-in">
      <div className="settings-card card max-w-2xl mx-auto">
        <h3><Clock /> Automation Schedule</h3>
        <div className="form-group">
          <label className="checkbox-label mb-4">
            <input 
              type="checkbox" 
              checked={config?.enable_scheduling} 
              onChange={(e) => handleInputChange('enable_scheduling', e.target.checked)} 
            />
            <span className="ml-2 font-medium">Enable Daily Automated Run</span>
          </label>
        </div>
        
        <div className="form-group">
          <label>Daily Execution Time (24h format)</label>
          <input 
            type="time" 
            value={config?.schedule_time || '01:00'} 
            onChange={(e) => handleInputChange('schedule_time', e.target.value)}
            disabled={!config?.enable_scheduling}
          />
        </div>

        <div className="form-group">
          <label>Windows Task Name</label>
          <input 
            type="text" 
            value={config?.task_name || 'DailyExtractarr'} 
            onChange={(e) => handleInputChange('task_name', e.target.value)}
            disabled={!config?.enable_scheduling}
          />
        </div>

        <p className="hint text-xs opacity-60 mt-4">
          When enabled, the server will attempt to register/update a scheduled task on the host system to run the workflow daily at the specified time.
        </p>

        <div className="settings-actions mt-6">
          <button className="save-button" disabled={loading} onClick={saveSettings}>
            <Save size={18} /> Save Schedule Settings
          </button>
        </div>
      </div>
    </div>
  );

  const renderContent = () => {
    switch (activeTab) {
      case 'dashboard': return renderDashboard();
      case 'settings': return renderSettings();
      case 'schedule': return renderSchedule();
      default: return renderDashboard();
    }
  };

  return (
    <div className="app-container">
      <nav className="sidebar">
        <div className="logo">
          <img src={logo} alt="Extractarr Logo" className="logo-img" />
        </div>
        <div className="nav-items">
          <button className={`nav-item ${activeTab === 'dashboard' ? 'active' : ''}`} onClick={() => setActiveTab('dashboard')}>
            <Activity size={20} /> <span>Dashboard</span>
          </button>
          <button className={`nav-item ${activeTab === 'settings' ? 'active' : ''}`} onClick={() => setActiveTab('settings')}>
            <Settings size={20} /> <span>Settings</span>
          </button>
          <button className={`nav-item ${activeTab === 'schedule' ? 'active' : ''}`} onClick={() => setActiveTab('schedule')}>
            <Clock size={20} /> <span>Schedule</span>
          </button>
        </div>
        <div className="sidebar-bottom-section">
          <div className="sidebar-footer">
            <button className="theme-toggle" onClick={toggleTheme}>
              {theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />}
              <span>{theme === 'dark' ? 'Light Mode' : 'Dark Mode'}</span>
            </button>
            <button className="power-button">
              <Power size={20} /> Restart Server
            </button>
          </div>
          <div className="support-section">
            <a href="https://buymeacoffee.com/Nat20labs" target="_blank" rel="noopener noreferrer" className="support-link nav-item">
              <Coffee size={20} /> <span>Support Creator</span>
            </a>
          </div>
        </div>
      </nav>

      <main className="main-content">
        <header className="top-header">
          <h2>{activeTab.charAt(0).toUpperCase() + activeTab.slice(1)}</h2>
          <div className="user-profile">
            <span>Admin</span>
          </div>
        </header>
        {renderContent()}
      </main>

      <div className="mobile-support-footer">
        <a href="https://buymeacoffee.com/Nat20labs" target="_blank" rel="noopener noreferrer" className="support-link nav-item">
          <Coffee size={20} /> <span>Support Creator</span>
        </a>
      </div>
    </div>
  );
}

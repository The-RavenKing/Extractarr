import { useEffect, useState } from 'react';
import {
  Activity,
  Clock,
  Coffee,
  Download,
  HardDrive,
  Lock,
  Moon,
  Music,
  RefreshCw,
  Save,
  Server,
  Settings,
  Shield,
  Sun,
  Terminal,
  Tv,
  Video,
} from 'lucide-react';
import logo from './assets/logo-optimized.webp';

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

interface MediaPaths {
  tv_source: string;
  tv_import: string;
  movies_source: string;
  movies_import: string;
  music_source: string;
  music_import: string;
}

interface MediaAppServer {
  url: string;
  api_key: string;
  enabled: boolean;
}

interface TorrentClientSettings {
  client_type: string;
  deluge_host: string;
  deluge_port: string;
  qbit_url: string;
  qbit_user: string;
  qbit_pass: string;
  max_seed_time: number;
  max_seed_ratio: number;
}

interface WebSettings {
  auth_enabled: boolean;
  username: string;
  password: string;
  host: string;
  port: number;
}

interface ExtractarrConfig {
  sftp_host: string;
  sftp_port: number;
  sftp_user: string;
  sftp_pass: string;
  remote_path: string;
  sftp_host_key: string;
  local_download_path: string;
  smb_user: string;
  smb_pass: string;
  paths: MediaPaths;
  torrent_client: TorrentClientSettings;
  sonarr: MediaAppServer;
  radarr: MediaAppServer;
  lidarr: MediaAppServer;
  enable_scheduling: boolean;
  schedule_time: string;
  task_name: string;
  web: WebSettings;
}

interface AuthStatus {
  auth_enabled: boolean;
  authenticated: boolean;
  username: string;
  require_password_change: boolean;
}

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [status, setStatus] = useState<WorkflowState | null>(null);
  const [config, setConfig] = useState<ExtractarrConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [importLoading, setImportLoading] = useState(false);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [theme, setTheme] = useState(localStorage.getItem('theme') || 'dark');
  const [authChecked, setAuthChecked] = useState(false);
  const [authEnabled, setAuthEnabled] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [requirePasswordChange, setRequirePasswordChange] = useState(false);
  const [currentUser, setCurrentUser] = useState('');
  const [loginLoading, setLoginLoading] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loginForm, setLoginForm] = useState({ username: 'admin', password: '' });
  const [passwordForm, setPasswordForm] = useState({ currentPassword: '', newPassword: '', confirmPassword: '' });
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ type: 'error' | 'success'; message: string } | null>(null);

  useEffect(() => {
    if (theme === 'light') {
      document.body.classList.add('light-theme');
    } else {
      document.body.classList.remove('light-theme');
    }
    localStorage.setItem('theme', theme);
  }, [theme]);

  useEffect(() => {
    fetchAuthStatus();
  }, []);

  useEffect(() => {
    if (!authenticated || requirePasswordChange) {
      return;
    }

    fetchStatus();
    fetchConfig();
    const interval = setInterval(fetchStatus, 3000);
    return () => clearInterval(interval);
  }, [authenticated, requirePasswordChange]);

  const toggleTheme = () => setTheme(theme === 'dark' ? 'light' : 'dark');

  const showNotice = (type: 'error' | 'success', message: string) => {
    setNotice({ type, message });
    window.setTimeout(() => setNotice(null), 4000);
  };

  const apiFetch = async (path: string, init?: RequestInit) => {
    const res = await fetch(path, {
      credentials: 'include',
      ...init,
      headers: {
        ...(init?.headers || {}),
      },
    });

    if (res.status === 401) {
      setAuthenticated(false);
      setCurrentUser('');
      throw new Error('Authentication required');
    }

    return res;
  };

  const fetchAuthStatus = async () => {
    try {
      const res = await fetch('/api/auth/status', { credentials: 'include' });
      const data: AuthStatus = await res.json();
      setAuthEnabled(data.auth_enabled);
      setAuthenticated(data.authenticated);
      setRequirePasswordChange(data.require_password_change);
      setCurrentUser(data.username || '');
      if (data.username) {
        setLoginForm((prev) => ({ ...prev, username: data.username }));
      }
    } catch (e) {
      console.error('Failed to fetch auth status', e);
      showNotice('error', 'Failed to contact the authentication endpoint');
    } finally {
      setAuthChecked(true);
    }
  };

  const fetchStatus = async () => {
    try {
      const res = await apiFetch('/api/status');
      const data = await res.json();
      setStatus(data);
    } catch (e) {
      console.error('Failed to fetch status', e);
      showNotice('error', 'Failed to load workflow status');
    }
  };

  const fetchConfig = async () => {
    try {
      const res = await apiFetch('/api/config');
      const data = await res.json();
      setConfig(data);
    } catch (e) {
      console.error('Failed to fetch config', e);
      showNotice('error', 'Failed to load configuration');
    }
  };

  const handleLogin = async () => {
    try {
      setLoginLoading(true);
      setLoginError(null);
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(loginForm),
      });

      if (!res.ok) {
        throw new Error('Invalid username or password');
      }

      const data: AuthStatus = await res.json();
      setAuthEnabled(data.auth_enabled);
      setAuthenticated(data.authenticated);
      setRequirePasswordChange(data.require_password_change);
      setCurrentUser(data.username || '');
      setLoginForm((prev) => ({ ...prev, password: '' }));
      setPasswordForm((prev) => ({ ...prev, currentPassword: loginForm.password }));
      if (data.require_password_change) {
        await fetchConfig();
      } else {
        await Promise.all([fetchStatus(), fetchConfig()]);
      }
    } catch (e) {
      setLoginError(e instanceof Error ? e.message : 'Login failed');
    } finally {
      setLoginLoading(false);
    }
  };

  const handleLogout = async () => {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
    setAuthenticated(false);
    setRequirePasswordChange(false);
    setCurrentUser('');
    setStatus(null);
    setConfig(null);
  };

  const handlePasswordChange = async () => {
    if (passwordForm.newPassword !== passwordForm.confirmPassword) {
      setPasswordError('New passwords do not match');
      return;
    }

    try {
      setPasswordLoading(true);
      setPasswordError(null);
      const res = await apiFetch('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_password: passwordForm.currentPassword,
          new_password: passwordForm.newPassword,
        }),
      });
      if (!res.ok) {
        throw new Error('Password change failed');
      }
      setRequirePasswordChange(false);
      setPasswordForm({ currentPassword: '', newPassword: '', confirmPassword: '' });
      showNotice('success', 'Password updated successfully');
      await fetchConfig();
    } catch (e) {
      setPasswordError(e instanceof Error ? e.message : 'Password change failed');
    } finally {
      setPasswordLoading(false);
    }
  };

  const handleRun = async () => {
    try {
      setLoading(true);
      await apiFetch('/api/run', { method: 'POST' });
      fetchStatus();
    } catch (e) {
      console.error('Failed to run workflow', e);
      showNotice('error', 'Failed to start the workflow');
    } finally {
      setLoading(false);
    }
  };

  const handleTriggerImports = async () => {
    try {
      setImportLoading(true);
      await apiFetch('/api/trigger-imports', { method: 'POST' });
      fetchStatus();
    } catch (e) {
      console.error('Failed to trigger imports', e);
      showNotice('error', 'Failed to trigger Arr imports');
    } finally {
      setImportLoading(false);
    }
  };

  const handleClearLogs = async () => {
    try {
      await apiFetch('/api/logs/clear', { method: 'POST' });
      setStatus((prev) => (prev ? { ...prev, logs: [] } : prev));
    } catch (e) {
      console.error('Failed to clear logs', e);
      showNotice('error', 'Failed to clear logs');
    }
  };

  const handleInputChange = (path: string, value: unknown) => {
    if (!config) {
      return;
    }
    const newConfig = structuredClone(config) as Record<string, any>;
    const parts = path.split('.');
    let current: Record<string, any> = newConfig;
    for (let i = 0; i < parts.length - 1; i++) {
      current = current[parts[i]];
    }
    current[parts[parts.length - 1]] = value;
    setConfig(newConfig as ExtractarrConfig);
  };

  const saveSettings = async () => {
    try {
      setLoading(true);
      const res = await apiFetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });

      if (!res.ok) {
        throw new Error('Save failed');
      }

      setSaveStatus('Settings saved successfully');
      showNotice('success', 'Settings saved successfully');
      setConfig((prev) =>
        prev
          ? {
              ...prev,
              web: { ...prev.web, password: '' },
            }
          : prev,
      );
      setTimeout(() => setSaveStatus(null), 3000);
      await fetchConfig();
    } catch (e) {
      setSaveStatus('Failed to save settings');
      showNotice('error', 'Failed to save settings');
    } finally {
      setLoading(false);
    }
  };

  const renderLogin = () => (
    <div className="login-shell">
      <div className="login-card card fade-in">
        <img src={logo} alt="Extractarr Logo" className="login-logo" />
        <h1>Extractarr</h1>
        <p>Sign in to manage workflow runs, credentials, and imports.</p>
        <div className="form-group">
          <label>Username</label>
          <input
            type="text"
            value={loginForm.username}
            onChange={(e) => setLoginForm((prev) => ({ ...prev, username: e.target.value }))}
          />
        </div>
        <div className="form-group">
          <label>Password</label>
          <input
            type="password"
            value={loginForm.password}
            onChange={(e) => setLoginForm((prev) => ({ ...prev, password: e.target.value }))}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                void handleLogin();
              }
            }}
          />
        </div>
        <p className="hint">
          Fresh installs bootstrap auth with <code>admin</code> / <code>admin</code>. Change it in Settings after login.
        </p>
        {loginError && <div className="login-error">{loginError}</div>}
        <button className="save-button login-button" onClick={handleLogin} disabled={loginLoading}>
          <Lock size={18} /> {loginLoading ? 'Signing in...' : 'Sign In'}
        </button>
      </div>
    </div>
  );

  const renderForcedPasswordChange = () => (
    <div className="login-shell">
      <div className="login-card card fade-in">
        <img src={logo} alt="Extractarr Logo" className="login-logo" />
        <h1>Change Password</h1>
        <p>Your initial password must be changed before the dashboard is unlocked.</p>
        <div className="form-group">
          <label>Current Password</label>
          <input
            type="password"
            value={passwordForm.currentPassword}
            onChange={(e) => setPasswordForm((prev) => ({ ...prev, currentPassword: e.target.value }))}
          />
        </div>
        <div className="form-group">
          <label>New Password</label>
          <input
            type="password"
            value={passwordForm.newPassword}
            onChange={(e) => setPasswordForm((prev) => ({ ...prev, newPassword: e.target.value }))}
          />
        </div>
        <div className="form-group">
          <label>Confirm New Password</label>
          <input
            type="password"
            value={passwordForm.confirmPassword}
            onChange={(e) => setPasswordForm((prev) => ({ ...prev, confirmPassword: e.target.value }))}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                void handlePasswordChange();
              }
            }}
          />
        </div>
        <p className="hint">Use at least 8 characters.</p>
        {passwordError && <div className="login-error">{passwordError}</div>}
        <button className="save-button login-button" onClick={handlePasswordChange} disabled={passwordLoading}>
          <Lock size={18} /> {passwordLoading ? 'Updating...' : 'Update Password'}
        </button>
      </div>
    </div>
  );

  const renderDashboard = () => (
    <div className="tab-content fade-in">
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-header">
            <Activity className="stat-icon" />
            <span>Workflow Status</span>
          </div>
          <div className={`stat-value ${status?.running ? 'active' : ''}`}>{status?.running ? 'Running' : 'Idle'}</div>
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
          <button
            className="run-button"
            disabled={status?.running || importLoading}
            onClick={handleTriggerImports}
            style={{ flex: 1, background: 'var(--accent-secondary, #6366f1)' }}
          >
            <Download size={16} style={{ display: 'inline', marginRight: '0.4rem', verticalAlign: 'middle' }} />
            {importLoading ? 'Triggering...' : 'Trigger Arr Imports'}
          </button>
        </div>
      </div>

      <div className="logs-section card">
        <div className="logs-header">
          <h3>Activity Logs</h3>
          <button className="clear-logs" onClick={handleClearLogs}>
            Clear Logs
          </button>
        </div>
        <div className="logs-content">
          {!status?.logs?.length ? (
            <div className="no-logs">No activity to show</div>
          ) : (
            [...status.logs].reverse().map((log, i) => (
              <div key={`${log.ts}-${i}`} className={`log-entry ${log.level}`}>
                <span className="log-ts">[{new Date(log.ts * 1000).toLocaleTimeString()}]</span>
                <span className="log-msg">{log.msg}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );

  const renderSettings = () => (
    <div className="tab-content fade-in">
      <div className="settings-grid">
        <div className="settings-card card">
          <h3><Server /> SFTP & Remote</h3>
          <div className="form-group">
            <label>Host</label>
            <input type="text" value={config?.sftp_host || ''} onChange={(e) => handleInputChange('sftp_host', e.target.value)} />
          </div>
          <div className="form-group">
            <label>Port</label>
            <input type="number" value={config?.sftp_port || 22} onChange={(e) => handleInputChange('sftp_port', parseInt(e.target.value, 10) || 22)} />
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
            <label>SFTP Host Key</label>
            <input type="text" value={config?.sftp_host_key || ''} onChange={(e) => handleInputChange('sftp_host_key', e.target.value)} />
          </div>
          <p className="hint">Use the server public host key, for example <code>ssh-ed25519 AAAA...</code>.</p>
        </div>

        <div className="settings-card card">
          <h3><Shield /> Web Access</h3>
          <div className="form-group">
            <label className="checkbox-label">
              <input type="checkbox" checked={config?.web?.auth_enabled ?? true} onChange={(e) => handleInputChange('web.auth_enabled', e.target.checked)} />
              <span>Require login for the dashboard API</span>
            </label>
          </div>
          <div className="form-group">
            <label>Username</label>
            <input type="text" value={config?.web?.username || ''} onChange={(e) => handleInputChange('web.username', e.target.value)} />
          </div>
          <div className="form-group">
            <label>New Password</label>
            <input type="password" value={config?.web?.password || ''} placeholder="Leave blank to keep existing password" onChange={(e) => handleInputChange('web.password', e.target.value)} />
          </div>
          <div className="form-group">
            <label>Bind Host</label>
            <input type="text" value={config?.web?.host || '127.0.0.1'} onChange={(e) => handleInputChange('web.host', e.target.value)} />
          </div>
          <div className="form-group">
            <label>Bind Port</label>
            <input type="number" value={config?.web?.port || 29441} onChange={(e) => handleInputChange('web.port', parseInt(e.target.value, 10) || 29441)} />
          </div>
          <p className="hint">Default bind is <code>127.0.0.1:29441</code>. Only use <code>0.0.0.0</code> if you intentionally want remote access.</p>
        </div>

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
          <p className="hint">Required if your local paths are network shares such as <code>\\\\192.168.1.x\\Share</code>.</p>
        </div>

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

        <div className="settings-card card">
          <h3><Shield /> App API Triggers</h3>
          <div className="app-trigger-group">
            <div className="trigger-header"><Tv size={16} /> Sonarr</div>
            <input type="text" placeholder="URL" value={config?.sonarr?.url || ''} onChange={(e) => handleInputChange('sonarr.url', e.target.value)} />
            <input type="password" placeholder="API Key" value={config?.sonarr?.api_key || ''} onChange={(e) => handleInputChange('sonarr.api_key', e.target.value)} />
            <label className="checkbox-label"><input type="checkbox" checked={!!config?.sonarr?.enabled} onChange={(e) => handleInputChange('sonarr.enabled', e.target.checked)} /> Enabled</label>
          </div>
          <div className="app-trigger-group mt-2">
            <div className="trigger-header"><Video size={16} /> Radarr</div>
            <input type="text" placeholder="URL" value={config?.radarr?.url || ''} onChange={(e) => handleInputChange('radarr.url', e.target.value)} />
            <input type="password" placeholder="API Key" value={config?.radarr?.api_key || ''} onChange={(e) => handleInputChange('radarr.api_key', e.target.value)} />
            <label className="checkbox-label"><input type="checkbox" checked={!!config?.radarr?.enabled} onChange={(e) => handleInputChange('radarr.enabled', e.target.checked)} /> Enabled</label>
          </div>
          <div className="app-trigger-group mt-2">
            <div className="trigger-header"><Music size={16} /> Lidarr</div>
            <input type="text" placeholder="URL" value={config?.lidarr?.url || ''} onChange={(e) => handleInputChange('lidarr.url', e.target.value)} />
            <input type="password" placeholder="API Key" value={config?.lidarr?.api_key || ''} onChange={(e) => handleInputChange('lidarr.api_key', e.target.value)} />
            <label className="checkbox-label"><input type="checkbox" checked={!!config?.lidarr?.enabled} onChange={(e) => handleInputChange('lidarr.enabled', e.target.checked)} /> Enabled</label>
          </div>
        </div>

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
                  <input type="number" value={config?.torrent_client?.max_seed_time || 14} onChange={(e) => handleInputChange('torrent_client.max_seed_time', parseInt(e.target.value, 10) || 14)} />
                </div>
                <div className="form-group">
                  <label>Max Seed Ratio</label>
                  <input type="number" step="0.1" value={config?.torrent_client?.max_seed_ratio || 2.0} onChange={(e) => handleInputChange('torrent_client.max_seed_ratio', parseFloat(e.target.value) || 2.0)} />
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
            <input type="checkbox" checked={!!config?.enable_scheduling} onChange={(e) => handleInputChange('enable_scheduling', e.target.checked)} />
            <span className="ml-2 font-medium">Enable Daily Automated Run</span>
          </label>
        </div>
        <div className="form-group">
          <label>Daily Execution Time (24h format)</label>
          <input type="time" value={config?.schedule_time || '01:00'} onChange={(e) => handleInputChange('schedule_time', e.target.value)} disabled={!config?.enable_scheduling} />
        </div>
        <div className="form-group">
          <label>Windows Task Name</label>
          <input type="text" value={config?.task_name || 'DailyExtractarr'} onChange={(e) => handleInputChange('task_name', e.target.value)} disabled={!config?.enable_scheduling} />
        </div>
        <p className="hint">The backend scheduler will run the workflow daily at the configured time.</p>
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
      case 'dashboard':
        return renderDashboard();
      case 'settings':
        return renderSettings();
      case 'schedule':
        return renderSchedule();
      default:
        return renderDashboard();
    }
  };

  if (!authChecked) {
    return <div className="login-shell"><div className="login-card card">Loading…</div></div>;
  }

  if (authEnabled && !authenticated) {
    return renderLogin();
  }

  if (requirePasswordChange) {
    return renderForcedPasswordChange();
  }

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
            <span>{currentUser || 'Admin'}</span>
            {authEnabled && (
              <button className="logout-button" onClick={handleLogout}>
                Sign Out
              </button>
            )}
          </div>
        </header>
        {notice && <div className={`notice-banner ${notice.type}`}>{notice.message}</div>}
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

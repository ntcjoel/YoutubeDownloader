// ---- Eagerly load categories on startup so the dropdown is populated from page load ----
async function initCategories() {
  try {
    const res = await fetch('/api/categories');
    if (res.ok) {
      _categories = await res.json();
      populateCategorySelect();
    }
  } catch (e) {
    console.error('Failed to load categories:', e);
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("urlInput").value = "";
  hidePlaylistBanner();
  // Load categories immediately so the task-form dropdown is populated from the start
  await initCategories();
});
// ---- WebSocket connection ----
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");

const socket = io({
  transports: ["polling", "websocket"],
  reconnectionDelay: 1000,
  reconnectionAttempts: 10,
});

socket && socket.on("connect", () => {
  statusDot.className = "dot active";
  statusText.textContent = "";
  socket.emit("request_tasks");
  hidePlaylistBanner();
  const savedPrefs = JSON.parse(localStorage.getItem('ydl_ui_prefs') || '{}');
  const defaultTab = savedPrefs.defaultTab || 'tasks';
  if (defaultTab !== 'tasks') switchTab(defaultTab);
});

socket && socket.on("disconnect", () => {
  statusDot.className = "dot error";
  statusText.textContent = "Connection lost";
});

socket && socket.on("connect_error", () => {
  statusDot.className = "dot error";
  statusText.textContent = "Connection failed";
});

// ---- Theme (auto + manual toggle) ----
function getAutoTheme() {
  const h = new Date().getHours();
  return h >= 6 && h < 18 ? 'light' : 'dark';
}
function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === 'light') root.classList.add('theme-light');
  else root.classList.remove('theme-light');
  updateThemeIcon(theme);
}
function updateThemeIcon(theme) {
  const icon = document.getElementById('themeIcon');
  if (!icon) return;
  if (theme === 'light') {
    icon.innerHTML = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';
  } else {
    icon.innerHTML = '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>';
  }
}
function toggleTheme() {
  const current = document.documentElement.classList.contains('theme-light') ? 'light' : 'dark';
  const next = current === 'light' ? 'dark' : 'light';
  localStorage.setItem('ydl_theme', next);
  applyTheme(next);
}
function initTheme() {
  const saved = localStorage.getItem('ydl_theme');
  if (saved) applyTheme(saved);
  else applyTheme(getAutoTheme());
}
initTheme();

// ---- Task state ----
let tasks = {};

// ---- Tab switching ----
let currentTab = "tasks";

function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
  document.querySelector(`.tab[data-tab="${tab}"]`).classList.add("active");
  document.getElementById(`pane-${tab}`).classList.add("active");
  if (tab === "logs") loadHistory(1);
  if (tab === "serverlog") loadServerLog();
  if (tab === "settings" && !_settingsLoaded) {
    _settingsLoaded = true;
    loadSettings();
  }
}

let _settingsLoaded = false;

let titleFetchTimer = null;
let logPage = 1;
let _historyPageSize = 20;

// ---- Title preview + playlist detection on URL input ----
let _pendingPlaylist = null;  // { url, items, title, count }

function hidePlaylistBanner() {
  const banner = document.getElementById("playlistBanner");
  if (banner) banner.classList.remove("show");
  _pendingPlaylist = null;
}

function showPlaylistBanner(items, title, count) {
  const banner = document.getElementById("playlistBanner");
  if (!banner) return;
  document.getElementById("plTitle").textContent = title || "Playlist";
  document.getElementById("plCount").textContent = count;
  document.getElementById("plSpinner").style.display = "none";
  document.getElementById("plMeta").style.display = "";
  document.getElementById("plDownloadBtn").style.display = "";
  document.getElementById("plCancelBtn").style.display = "";
  document.getElementById("plIcon").style.display = "";
  banner.classList.add("show");
  _pendingPlaylist = { items, title, count };
}

async function fetchTitle(url) {
  if (!url || !url.includes("youtube.com") && !url.includes("youtu.be") && !url.includes("bilibili.com") && !url.includes("tiktok.com")) {
    document.getElementById("titlePreview").textContent = "";
    hidePlaylistBanner();
    return;
  }
  // Hide playlist banner while fetching
  hidePlaylistBanner();
  const el = document.getElementById("titlePreview");
  el.innerHTML = '<span class="spinner"></span>Fetching...';
  el.className = "loading";
  try {
    // Use /api/parse which returns both title and is_playlist info
    const resp = await fetch("/api/parse?url=" + encodeURIComponent(url));
    const data = await resp.json();
    if (data.error && !data.title) {
      el.textContent = "Cannot fetch title...";
      el.className = "error";
      return;
    }
    if (data.title) {
      el.textContent = data.title;
      el.className = "";
      populateQualityDropdown(data.qualities || []);
    }
    // Show playlist banner if detected
    if (data.is_playlist && data.playlist_items && data.playlist_items.length >= 3) {
      showPlaylistBanner(data.playlist_items, data.playlist_title, data.playlist_count);
    }
  } catch (e) {
    el.textContent = "Failed to fetch title";
    el.className = "error";
  }
}

function populateQualityDropdown(qualities) {
  const select = document.getElementById("qualitySelect");
  const defaultQualities = ["2160p", "1440p", "1080p", "720p", "480p", "360p"];
  const allQualities = qualities.length > 0 ? qualities : defaultQualities;
  select.innerHTML = allQualities.map(q => `<option value="${q}">${q}</option>`).join("");
  // Auto-select the configured default quality, fall back to highest available
  const defaultQuality = document.getElementById("setDefaultQuality")?.value || "1080p";
  if (allQualities.includes(defaultQuality)) {
    select.value = defaultQuality;
  } else if (allQualities.length > 0) {
    select.value = allQualities[0];
  }
}

document.getElementById("urlInput").addEventListener("input", (e) => {
  clearTimeout(titleFetchTimer);
  const url = e.target.value.trim();
  if (!url) {
    document.getElementById("titlePreview").textContent = "";
    return;
  }
  titleFetchTimer = setTimeout(() => fetchTitle(url), 600);
});

// ---- Task rendering ----
let _collapsedPlaylists = {};  // task_id -> true if collapsed

function renderTasks() {
  const list = document.getElementById("taskList");
  const arr = Object.values(tasks);
  if (arr.length === 0) {
    list.innerHTML = '<div class="empty">No Tasks</div>';
    return;
  }

  // Read visibility prefs
  const prefs = JSON.parse(localStorage.getItem('ydl_ui_prefs') || '{}');
  const showUrl = prefs.showUrl !== false;
  const showFilename = prefs.showFilename !== false;
  const showQuality = prefs.showQuality !== false;

  arr.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

  // Separate playlist tasks from regular tasks
  const plTasks = arr.filter(t => t.task_type === 'playlist');
  const singleTasks = arr.filter(t => t.task_type !== 'playlist');

  list.innerHTML = plTasks.map(pl => renderPlaylistTask(pl, showUrl, showFilename, showQuality)).join('')
    + singleTasks.map(t => renderSingleTask(t, showUrl, showFilename, showQuality)).join('');

  // Close menus when clicking outside
  document.addEventListener('click', closeAllTaskMenus, { once: true });
}

function renderPlaylistTask(pl, showUrl, showFilename, showQuality) {
  const collapsed = _collapsedPlaylists[pl.id];
  const badge = {
    downloading: "Downloading",
    processing: "Processing",
    completed: "Completed",
    error: "Partially Failed",
    cancelled: "Cancelled",
    pending: "Pending",
  }[pl.status] || pl.status;

  const cls = {
    downloading: "badge-downloading",
    processing: "badge-processing",
    completed: "badge-completed",
    error: "badge-error",
    cancelled: "badge-pending",
    pending: "badge-pending",
  }[pl.status] || "badge-pending";

  const total = pl.total || 0;
  const done = (pl.completed || 0) + (pl.failed || 0);
  const failed = pl.failed || 0;

  const menuId = `task-menu-${pl.id}`;
  const plTitle = pl.title || "Playlist";
  const plBadge = pl.format === 'audio' ? 'MP3' : 'MP4';

  let childHtml = '';
  if (!collapsed) {
    const children = (pl.children || [])
      .map(cid => tasks[cid])
      .filter(c => c);

    childHtml = children.map(c => {
      const doneCls = c.status === 'completed' ? 'done'
        : c.status === 'error' ? 'err'
        : c.status === 'downloading' ? 'downloading'
        : 'pending';
      const statusText = c.status === 'completed' ? 'Done'
        : c.status === 'error' ? 'Failed'
        : c.status === 'downloading' ? `${c.progress || 0}%`
        : c.status === 'processing' ? 'Processing'
        : 'Pending';
      return `
        <div class="task-child">
          <span class="tc-status ${doneCls}">${statusText}</span>
          <span class="tc-title" title="${escapeHtml(c.title || c.url || '')}">${escapeHtml(c.title || c.url || 'Unknown')}</span>
          ${c.status === 'downloading' ? `<div class="progress-mini"><div class="progress-mini-fill" style="width:${c.progress || 0}%"></div></div>` : ''}
        </div>
      `;
    }).join('');
  }

  return `
    <div class="task" data-id="${pl.id}">
      <div class="task-header">
        <span class="collapse-btn" onclick="togglePlaylistCollapse(\'${pl.id}\')" title="${collapsed ? 'Expand' : 'Collapse'}">
          ${collapsed ? '&#9658;' : '&#9660;'}
        </span>
        <div class="task-title" style="flex:1;min-width:0;">
          ${escapeHtml(plTitle)}
          <span class="log-badge" style="font-size:0.65rem;padding:2px 6px;border-radius:10px;background:#1a2a3a;color:#f0a040;margin-left:6px;">${plBadge}</span>
          <span class="log-badge" style="font-size:0.65rem;padding:2px 6px;border-radius:10px;background:#1a2a3a;color:#aaa;margin-left:4px;">${total} videos</span>
        </div>
        <span class="task-badge ${cls}">${badge}${pl.status === 'downloading' && total > 0 ? ` ${done}/${total}` : ''}</span>
        <div class="context-menu">
          <button class="task-menu-btn" onclick="toggleTaskMenu(\'${menuId}\')" title="More actions">&#8942;</button>
          <div class="context-menu-dropdown" id="${menuId}">
            ${pl.status === 'downloading' ? `<button class="context-menu-item danger" onclick="cancelPlaylist(\'${pl.id}\')">Cancel</button>` : ''}
            <button class="context-menu-item danger" onclick="deleteTask(\'${pl.id}\')">Delete</button>
          </div>
        </div>
      </div>
      ${pl.status === 'downloading' ? `<div class="progress-wrap"><div class="progress-bar" style="width:${pl.progress || 0}%"></div></div>` : ''}
      ${pl.message ? `<div class="task-message">${pl.message}</div>` : ''}
      ${childHtml ? `<div class="task-children">${childHtml}</div>` : ''}
    </div>
  `;
}

function togglePlaylistCollapse(taskId) {
  if (_collapsedPlaylists[taskId]) {
    delete _collapsedPlaylists[taskId];
  } else {
    _collapsedPlaylists[taskId] = true;
  }
  renderTasks();
}

async function cancelPlaylist(taskId) {
  
  await fetch("/api/playlist/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: taskId }),
  });
  socket.emit("request_tasks");
  hidePlaylistBanner();
}

function renderSingleTask(t, showUrl, showFilename, showQuality) {
  const badge = {
    pending: "Pending",
    downloading: "Downloading",
    processing: "Processing",
    completed: "Completed",
    error: "Error",
  }[t.status] || t.status;

  const cls = {
    pending: "badge-pending",
    downloading: "badge-downloading",
    processing: "badge-processing",
    completed: "badge-completed",
    error: "badge-error",
  }[t.status] || "badge-pending";

  const msg = t.error
    ? `<span class="task-error">${t.error}</span>`
    : `<span>${t.message || ""}</span><span>${t.progress !== undefined ? t.progress + "%" : ""}</span>`;

  const filenameHtml2 = showFilename && t.filename
    ? `<div class="task-filename">&#128193; ${t.filename}</div>`
    : '';

  const qualityBadge = showQuality && t.quality
    ? `<span class="log-badge" style="font-size:0.65rem;padding:2px 6px;border-radius:10px;background:#1a2a3a;color:#4488ff;margin-left:6px;">${t.quality}</span>`
    : '';

  const categoryBadge = t.category
    ? `<span class="log-badge" style="font-size:0.65rem;padding:2px 6px;border-radius:10px;background:#2a1a3a;color:#aa66cc;margin-left:4px;">${t.category}</span>`
    : '';

  const hasFile = t.status === 'completed' && t.filename;

  const menuId = `task-menu-${t.id}`;
  const titleId = `task-title-${t.id}`;

  return `
    <div class="task" data-id="${t.id}">
      <div class="task-header">
        <div class="task-title" id="${titleId}" style="flex:1;min-width:0;">${t.title || t.url || "Unknown"}${qualityBadge}${categoryBadge}</div>
        ${(t.format === 'audio' && t.filename && t.status === 'completed')
          ? `<button class="btn-edit" onclick="openMetaModal(\'${t.filename.replace(/'/g, "\\'")}\')">Edit Metadata</button>`
          : ''}
        <span class="task-badge ${cls}">${badge}</span>
        <div class="context-menu">
          <button class="task-menu-btn" onclick="toggleTaskMenu(\'${menuId}\')" title="More actions">&#8942;</button>
          <div class="context-menu-dropdown" id="${menuId}">
            ${t.status === 'error' ? `<button class="context-menu-item" onclick="redownloadTask(\'${t.id}\')">Redownload</button>` : ''}
            ${t.status === 'error' && hasFile ? `<div class="context-menu-divider"></div>` : ''}
            ${hasFile ? `<button class="context-menu-item" onclick="openMoveModal('${t.id}', '${t.filename.replace(/'/g, "\\'")}')">Move</button>` : ''}
            ${hasFile ? `<button class="context-menu-item" onclick="openSingleRename(\'${t.id}\', \'${t.filename.replace(/'/g, "\\'")}\')">Rename</button>` : ''}
            ${hasFile ? `<div class="context-menu-divider"></div>` : ''}
            <button class="context-menu-item danger" onclick="deleteTask(\'${t.id}\')">Delete</button>
          </div>
        </div>
      </div>
      ${showUrl ? `<div class="task-url-row">
        <span class="task-url-label">URL</span>
        <a class="task-url" href="${t.url}" target="_blank" rel="noopener">${t.url}</a>
      </div>` : ''}
      ${filenameHtml2}
      ${t.status !== 'completed' && t.status !== 'error' && t.status !== 'pending' ? `<div class="progress-wrap"><div class="progress-bar" style="width:${t.progress || 0}%"></div></div>` : ''}
      <div class="task-message">${msg}</div>
    </div>
  `;
}



// ---- WebSocket event handlers ----
if (socket) {
  socket.on("task_list", (serverTasks) => {
    tasks = {};
    for (const t of serverTasks) {
      tasks[t.id] = t;
    }
    renderTasks();
  });

  socket.on("task_update", (task) => {
    tasks[task.id] = task;
    renderTasks();
  });

  socket.on("tasks_cleared", () => {
    socket.emit("request_tasks");
  hidePlaylistBanner();
  });

  socket.on("config_updated", (cfg) => {
    _serverConfig = cfg;
    populateServerConfig(cfg);
  });
}

// ---- Download form ----
document.getElementById("downloadForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = document.getElementById("urlInput").value.trim();
  const format = document.getElementById("formatSelect").value;
  const quality = document.getElementById("qualitySelect").value;
  const customName = document.getElementById("customNameInput").value.trim();
  const category = document.getElementById("categorySelect").value;
  if (!url) return;

  const titleEl = document.getElementById("titlePreview");
  const previewTitle = titleEl.textContent && !titleEl.className.includes("error")
    ? titleEl.textContent : null;

  document.getElementById("submitBtn").disabled = true;
  document.getElementById("submitBtn").textContent = "Submitting......";

  try {
    // If a playlist is pending, use playlist download API instead
    if (_pendingPlaylist) {
      const plData = {
        url,
        format,
        quality: format === "audio" ? "" : quality,
        category: category || null,
      };
      const res = await fetch("/api/playlist/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(plData),
      });
      const data = await res.json();
      if (!res.ok) {
        alert("Error: " + (data.error || "UnknownError"));
      } else if (data.task) {
        tasks[data.task.id] = data.task;
        // Add children as tasks too
        for (const child of (data.children || [])) {
          tasks[child.id] = child;
        }
        renderTasks();
        hidePlaylistBanner();
        document.getElementById("urlInput").value = "";
        document.getElementById("titlePreview").textContent = "";
      }
      document.getElementById("submitBtn").disabled = false;
      document.getElementById("submitBtn").textContent = "Download";
      return;
    }

    const res = await fetch("/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, format, quality, custom_name: customName, category }),
    });
    const data = await res.json();
    if (!res.ok) {
      alert("Error: " + (data.error || "UnknownError"));
    } else if (data.task && previewTitle) {
      data.task.title = previewTitle;
      tasks[data.task.id] = data.task;
      renderTasks();
    }
  } catch (err) {
    alert("Request failed: " + err.message);
  } finally {
    document.getElementById("submitBtn").disabled = false;
    document.getElementById("submitBtn").textContent = "Download";
  }
});

// ---- Paste from clipboard into URL input ----
document.getElementById("pasteBtn").addEventListener("click", async () => {
  try {
    const text = await navigator.clipboard.readText();
    if (text) {
      document.getElementById("urlInput").value = text.trim();
      document.getElementById("urlInput").dispatchEvent(new Event("input", { bubbles: true }));
    }
  } catch (e) {
    // Clipboard API not available (e.g. http context) — silently ignore
  }
});
// ---- Playlist banner buttons ----
document.getElementById("plDownloadBtn")?.addEventListener("click", async () => {
  const url = document.getElementById("urlInput").value.trim();
  const format = document.getElementById("formatSelect").value;
  const quality = document.getElementById("qualitySelect").value;
  if (!_pendingPlaylist || !url) return;
  document.getElementById("plDownloadBtn").disabled = true;
  document.getElementById("plDownloadBtn").textContent = "Starting...";
  try {
    const res = await fetch("/api/playlist/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, format, quality: format === "audio" ? "" : quality, category: "" }),
    });
    const data = await res.json();
    if (!res.ok) {
      alert("Error: " + (data.error || "UnknownError"));
      document.getElementById("plDownloadBtn").disabled = false;
      document.getElementById("plDownloadBtn").textContent = "Download All";
    } else if (data.task) {
      tasks[data.task.id] = data.task;
      for (const child of (data.children || [])) {
        tasks[child.id] = child;
      }
      renderTasks();
      hidePlaylistBanner();
      document.getElementById("urlInput").value = "";
      document.getElementById("titlePreview").textContent = "";
    }
  } catch (err) {
    alert("Request failed: " + err.message);
    document.getElementById("plDownloadBtn").disabled = false;
    document.getElementById("plDownloadBtn").textContent = "Download All";
  }
});

document.getElementById("plCancelBtn")?.addEventListener("click", () => {
  hidePlaylistBanner();
  document.getElementById("urlInput").value = "";
  document.getElementById("titlePreview").textContent = "";
});



// ---- Clear URL input ----
document.getElementById("urlClearBtn").addEventListener("click", () => {
  document.getElementById("urlInput").value = "";
  document.getElementById("urlInput").dispatchEvent(new Event("input", { bubbles: true }));
  document.getElementById("titlePreview").textContent = "";
  document.getElementById("titlePreview").className = "";
});

// ---- Clear completed tasks ----
document.getElementById("clearBtn").addEventListener("click", async () => {
  await fetch("/clear", { method: "POST" });
});

// ---- History tab ----
async function loadHistory(page) {
  logPage = page;
  const logList = document.getElementById("logList");
  const pagination = document.getElementById("logPagination");
  logList.innerHTML = '<div class="log-empty"><span class="spinner"></span>Loading......</div>';

  try {
    const res = await fetch(`/logs?page=${page}`);
    const data = await res.json();
    _historyPageSize = data.limit || 20;

    if (!data.items || data.items.length === 0) {
      logList.innerHTML = '<div class="log-empty">No download records</div>';
      pagination.innerHTML = '';
      return;
    }

    logList.innerHTML = data.items.map(item => {
      const badgeClass = item.format === 'audio' ? 'audio' : 'video';
      const badgeText = item.format === 'audio' ? 'MP3' : 'MP4';
      const sizeStr = item.size_mb ? `${item.size_mb} MB` : '';
      const statusIcon = item.status === 'success'
        ? '<span style="color:var(--green)">&#10004;</span>'
        : '<span style="color:var(--red)">&#10008;</span>';

      const hasFile = item.filename && item.status === 'success';
      const menuId = `hist-menu-${item.ts}`;

      return `
        <div class="log-item" data-ts="${item.ts || ''}">
          <div class="log-header">
            <div class="log-title">${item.title || item.url || 'Unknown title'}</div>
            <span class="log-badge ${badgeClass}">${badgeText} · ${item.quality || ''}</span>
            <div class="context-menu">
              <button class="log-menu-btn" onclick="toggleTaskMenu('${menuId}')" title="More actions">&#8942;</button>
              <div class="context-menu-dropdown" id="${menuId}">
                ${hasFile ? `<button class="context-menu-item" onclick="openMoveModal('${item.ts}', '${(item.filename || '').replace(/'/g, "\\'")}')">Move</button>` : ''}
                ${hasFile ? `<button class="context-menu-item" onclick="openHistoryRename('${item.ts}', '${(item.filename || '').replace(/'/g, "\\'")}')">Rename</button>` : ''}
                <div class="context-menu-divider"></div>
                <button class="context-menu-item danger" onclick="deleteHistoryRecord('${item.ts || ''}', false)">Delete record</button>
                ${hasFile ? `<button class="context-menu-item danger" onclick="deleteHistoryRecord('${item.ts || ''}', true)">Delete file</button>` : ''}
              </div>
            </div>
          </div>
          <div class="log-meta">
            <span>${statusIcon} ${item.status || ''}</span>
            <span>&#128196; ${item.ts ? item.ts.replace('T', ' ') : ''}</span>
            ${sizeStr ? `<span>&#128190; ${sizeStr}</span>` : ''}
          </div>
          <div class="log-url">${item.url}</div>
          ${item.filename ? `<div class="log-path">${item.filename}</div>` : ''}
          ${item.error ? `<div style="font-size:0.75rem;color:var(--red);margin-top:4px;">Error: ${item.error}</div>` : ''}
        </div>
      `;
    }).join('');

    // Pagination controls
    if (data.pages > 1) {
      pagination.innerHTML = `
        <button onclick="loadHistory(${data.page - 1})" ${data.page <= 1 ? 'disabled' : ''}>Prev</button>
        <span class="page-info">Page ${data.page} / ${data.pages} (Total: ${data.total})</span>
        <button onclick="loadHistory(${data.page + 1})" ${data.page >= data.pages ? 'disabled' : ''}>Next</button>
      `;
    } else {
      pagination.innerHTML = `<span class="page-info">Total: ${data.total} records</span>`;
    }
  } catch (e) {
    logList.innerHTML = '<div class="log-empty">Failed to load: ' + e.message + '</div>';
    pagination.innerHTML = '';
  }
}

// ---- Settings tab ----
let _serverConfig = null;
let _categories = {};

async function loadSettings() {
  // Load server config from API
  try {
    const res = await fetch('/api/config');
    if (res.ok) {
      _serverConfig = await res.json();
      populateServerConfig(_serverConfig);
      onCookieSiteChange();
    }
  } catch (e) {
    console.error('Failed to load server config:', e);
  }
  // Load categories
  try {
    const res = await fetch('/api/categories');
    if (res.ok) {
      _categories = await res.json();
      renderCategories();
      populateCategorySelect();
    }
  } catch (e) {
    console.error('Failed to load categories:', e);
  }
  // Load UI prefs from localStorage
  loadUIPrefsFromStorage();
}

function renderCategories() {
  const list = document.getElementById('categoriesList');
  if (!list) return;
  const cats = Object.entries(_categories);
  if (cats.length === 0) {
    list.innerHTML = '<div style="font-size:0.82rem;color:var(--text2);">No categories configured.</div>';
    return;
  }
  list.innerHTML = cats.map(([key, cat]) => `
    <div class="settings-row" style="margin-bottom:10px; background:var(--surface2); border:1px solid var(--border); border-radius:8px; padding:10px 12px;">
      <div style="flex:1; min-width:0;">
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
          <span style="font-size:0.88rem; font-weight:500; color:#fff;">${escapeHtml(cat.name || key)}</span>
          <span style="font-size:0.72rem; color:var(--text2);">(${escapeHtml(key)})</span>
        </div>
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
          <label style="font-size:0.72rem; color:var(--text2);">Dir:</label>
          <input type="text" class="settings-input" id="cat_dir_${escapeHtml(key)}" value="${escapeHtml(cat.dir || '')}" style="min-width:200px; font-size:0.8rem; padding:5px 8px;" />
          <label style="font-size:0.72rem; color:var(--text2); margin-left:8px;">Max GB:</label>
          <input type="number" class="settings-input" id="cat_max_${escapeHtml(key)}" value="${cat.max_size_gb ?? 0}" min="0" step="1" style="min-width:70px; font-size:0.8rem; padding:5px 8px;" />
        </div>
      </div>
      <button type="button" onclick="removeCategory('${escapeHtml(key)}')" style="background:transparent; border:1px solid var(--border); color:var(--text2); border-radius:6px; padding:4px 10px; font-size:0.75rem; cursor:pointer; flex-shrink:0;">Remove</button>
    </div>
  `).join('');
}

function populateCategorySelect() {
  const select = document.getElementById('categorySelect');
  if (!select) return;
  // Preserve current selection
  const current = select.value;
  select.innerHTML = '<option value="">Default (auto)</option>';
  for (const [key, cat] of Object.entries(_categories)) {
    if (cat.enabled !== false) {
      const opt = document.createElement('option');
      opt.value = key;
      opt.textContent = cat.name || key;
      select.appendChild(opt);
    }
  }
  if (current && _categories[current] && _categories[current].enabled !== false) {
    select.value = current;
  }
}

function addCategory() {
  const nameInput = document.getElementById('newCatName');
  const dirInput = document.getElementById('newCatDir');
  const name = nameInput.value.trim();
  const dir = dirInput.value.trim();
  if (!name) {
    alert('Category name is required');
    return;
  }
  // Generate key from name (slug-like)
  const key = name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'category_' + Date.now();
  if (_categories[key]) {
    alert('A category with this key already exists. Use a unique name or remove the existing one first.');
    return;
  }
  _categories[key] = { name, dir: dir || '', enabled: true };
  nameInput.value = '';
  dirInput.value = '';
  renderCategories();
  populateCategorySelect();
}

function removeCategory(key) {
  delete _categories[key];
  renderCategories();
  populateCategorySelect();
}

async function saveCategories() {
  // Collect current state from rendered inputs
  const updated = {};
  for (const [key, cat] of Object.entries(_categories)) {
    const enabled = document.getElementById('cat_enabled_' + key)?.checked ?? true;
    const dirEl = document.getElementById('cat_dir_' + key);
    const dir = dirEl ? dirEl.value : (cat.dir || '');
    const maxGb = parseFloat(document.getElementById('cat_max_' + key)?.value) || 0;
    updated[key] = { name: cat.name, dir, enabled, max_size_gb: maxGb };
  }
  _categories = updated;

  const btn = document.getElementById('saveCategoriesBtn');
  const errEl = document.getElementById('categoriesErrorMsg');
  const savedEl = document.getElementById('categoriesSavedMsg');
  errEl.classList.remove('show');
  savedEl.classList.remove('show');
  btn.disabled = true;
  btn.textContent = 'Saving...';
  try {
    const res = await fetch('/api/categories', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(_categories),
    });
    const data = await res.json();
    if (data.ok) {
      showSavedMsg('categoriesSavedMsg');
      populateCategorySelect();
    } else {
      errEl.textContent = 'Error: ' + (data.error || 'Unknown error');
      errEl.classList.add('show');
    }
  } catch (e) {
    errEl.textContent = 'Request failed: ' + e.message;
    errEl.classList.add('show');
  } finally {
    btn.textContent = 'Save Categories';
    btn.disabled = false;
  }
}

function onCookieSiteChange() {
  const site = document.getElementById('setCookieSite').value;
  const cookieRow = document.getElementById('cookieContentRow');
  const cookieContent = document.getElementById('setCookieContent');
  if (site && site !== '') {
    cookieRow.style.display = 'flex';
    // Fetch and display truncated cookie content
    fetch('/api/cookie?site=' + encodeURIComponent(site))
      .then(r => r.json())
      .then(d => { cookieContent.value = d.content || ''; });
  } else {
    cookieRow.style.display = 'none';
    cookieContent.value = '';
  }
}

function populateServerConfig(cfg) {
  if (!cfg) return;
  document.getElementById('setVideoDir').value = cfg.video_dir || '';
  document.getElementById('setMusicDir').value = cfg.music_dir || '';
  document.getElementById('setDiskLimitEnabled').checked = !!cfg.disk_limit_enabled;
  document.getElementById('setMaxVideoGb').value = cfg.max_video_size_gb ?? '';
  document.getElementById('setMaxMusicGb').value = cfg.max_music_size_gb ?? '';
  document.getElementById('setDefaultFormat').value = cfg.default_format || 'video';
  document.getElementById('setDefaultQuality').value = cfg.default_quality || '1080p';
  document.getElementById('setStripPlaylist').checked = !!cfg.strip_playlist;
  document.getElementById('setCleanupPolicy').value = cfg.cleanup_policy || 'oldest_first';
  document.getElementById('setRetentionDays').value = cfg.retention_days ?? '';
  document.getElementById('setCookieSite').value = cfg.cookie_site || '';
  // Show cookie content row and load content for selected site
  const site = cfg.cookie_site || '';
  const cookieRow = document.getElementById('cookieContentRow');
  const cookieContent = document.getElementById('setCookieContent');
  if (site) {
    cookieRow.style.display = 'flex';
    fetch('/api/cookie?site=' + encodeURIComponent(site))
      .then(r => r.json())
      .then(d => { cookieContent.value = d.content || ''; });
  } else {
    cookieRow.style.display = 'none';
    cookieContent.value = '';
  }
}

function loadUIPrefsFromStorage() {
  const prefs = JSON.parse(localStorage.getItem('ydl_ui_prefs') || '{}');
  document.getElementById('setDefaultTab').value = prefs.defaultTab || 'tasks';
  document.getElementById('setHistoryPageSize').value = prefs.historyPageSize || '20';
  document.getElementById('setShowUrl').checked = prefs.showUrl !== false;
  document.getElementById('setShowFilename').checked = prefs.showFilename !== false;
  document.getElementById('setShowQuality').checked = prefs.showQuality !== false;
  document.getElementById('setWebTitle').value = prefs.webTitle || '';
  if (prefs.webTitle) document.title = prefs.webTitle;
}

async function saveUIPrefs() {
  const prefs = {
    defaultTab: document.getElementById('setDefaultTab').value,
    historyPageSize: parseInt(document.getElementById('setHistoryPageSize').value),
    showUrl: document.getElementById('setShowUrl').checked,
    showFilename: document.getElementById('setShowFilename').checked,
    showQuality: document.getElementById('setShowQuality').checked,
    webTitle: document.getElementById('setWebTitle').value.trim(),
  };
  localStorage.setItem('ydl_ui_prefs', JSON.stringify(prefs));
  if (prefs.webTitle) document.title = prefs.webTitle;
  else document.title = 'YouTube Downloader';
  if (currentTab === 'logs') loadHistory(1);
  showSavedMsg('uiSavedMsg');
}

async function saveServerConfig() {
  const btn = document.getElementById('saveServerConfigBtn');
  const errEl = document.getElementById('serverErrorMsg');
  const savedEl = document.getElementById('serverSavedMsg');
  errEl.classList.remove('show');
  savedEl.classList.remove('show');
  btn.disabled = true;
  btn.textContent = 'Saving...';
  try {
    const body = {
      video_dir: document.getElementById('setVideoDir').value,
      music_dir: document.getElementById('setMusicDir').value,
      disk_limit_enabled: document.getElementById('setDiskLimitEnabled').checked,
      max_video_size_gb: parseFloat(document.getElementById('setMaxVideoGb').value) || 0,
      max_music_size_gb: parseFloat(document.getElementById('setMaxMusicGb').value) || 0,
      default_format: document.getElementById('setDefaultFormat').value,
      default_quality: document.getElementById('setDefaultQuality').value,
      strip_playlist: document.getElementById('setStripPlaylist').checked,
      cleanup_policy: document.getElementById('setCleanupPolicy').value,
      retention_days: parseInt(document.getElementById('setRetentionDays').value) || 0,
      cookie_site: document.getElementById('setCookieSite').value,
    };
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (data.ok) {
      _serverConfig = data.config;
      // Also save cookie content to file
      const cookieSite = document.getElementById('setCookieSite').value;
      const cookieVal = document.getElementById('setCookieContent').value;
      if (cookieSite) {
        await fetch('/api/cookie', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ site: cookieSite, content: cookieVal }),
        });
      }
      showSavedMsg('serverSavedMsg');
    } else {
      errEl.textContent = 'Error: ' + (data.error || 'Unknown error');
      errEl.classList.add('show');
    }
  } catch (e) {
    errEl.textContent = 'Request failed: ' + e.message;
    errEl.classList.add('show');
  } finally {
    btn.textContent = 'Save Server Config';
    btn.disabled = false;
  }
}

function showSavedMsg(id) {
  const el = document.getElementById(id);
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 3000);
}

// ---- Server Log tab ----
async function loadServerLog() {
  const output = document.getElementById("serverLogOutput");
  output.innerHTML = '<div class="server-log-empty"><span class="spinner"></span>Loading......</div>';
  try {
    const res = await fetch("/api/app-log?lines=200");
    const data = await res.json();
    if (!data.lines || data.lines.length === 0) {
      output.innerHTML = '<div class="server-log-empty">No server log entries yet</div>';
      return;
    }
    output.innerHTML = '<pre class="server-log">' + data.lines.map(line => {
      const cls = line.includes(' [ERROR]') ? 'log-error'
                 : line.includes(' [WARNING]') ? 'log-warn'
                 : 'log-info';
      return `<div class="log-line ${cls}">${escapeHtml(line)}</div>`;
    }).join('') + '</pre>';
  } catch (e) {
    output.innerHTML = '<div class="server-log-empty">Failed to load: ' + e.message + '</div>';
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ---- Metadata Editor Modal ----
let _metaCurrentFilepath = null;

function openMetaModal(filepath) {
  _metaCurrentFilepath = filepath;
  document.getElementById('metaFilepath').textContent = filepath;
  document.getElementById('metaArtist').value = '';
  document.getElementById('metaTitle').value = '';
  document.getElementById('metaAlbum').value = '';
  document.getElementById('metaYear').value = '';
  document.getElementById('metaGenre').value = '';
  document.getElementById('metaCover').value = '';
  document.getElementById('autofillBtn').innerHTML = 'Auto-fill';
  document.getElementById('autofillBtn').disabled = false;
  document.getElementById('metaModal').classList.add('open');
}

function closeMetaModal() {
  document.getElementById('metaModal').classList.remove('open');
  _metaCurrentFilepath = null;
}

async function doAutoFill() {
  if (!_metaCurrentFilepath) return;
  const btn = document.getElementById('autofillBtn');
  btn.innerHTML = '<span class="autofill-spinner"></span>Searching...';
  btn.disabled = true;
  try {
    const resp = await fetch('/api/metadata-form?filepath=' + encodeURIComponent(_metaCurrentFilepath));
    const data = await resp.json();
    if (data.error) {
      alert('Error: ' + data.error);
    } else {
      const s = data.suggestion;
      if (s.artist) document.getElementById('metaArtist').value = s.artist;
      if (s.title) document.getElementById('metaTitle').value = s.title;
      if (s.album) document.getElementById('metaAlbum').value = s.album;
      if (s.year) document.getElementById('metaYear').value = s.year;
      if (s.genre) document.getElementById('metaGenre').value = s.genre;
      if (s.cover_url) document.getElementById('metaCover').value = s.cover_url;
    }
  } catch (e) {
    alert('Auto-fill failed: ' + e.message);
  } finally {
    btn.innerHTML = 'Auto-fill';
    btn.disabled = false;
  }
}

async function doSaveMeta() {
  if (!_metaCurrentFilepath) return;
  const saveBtn = document.getElementById('metaSaveBtn');
  saveBtn.disabled = true;
  saveBtn.textContent = 'Saving...';
  try {
    const resp = await fetch('/api/save-metadata', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        filepath: _metaCurrentFilepath,
        artist: document.getElementById('metaArtist').value,
        title: document.getElementById('metaTitle').value,
        album: document.getElementById('metaAlbum').value,
        year: document.getElementById('metaYear').value,
        genre: document.getElementById('metaGenre').value,
        cover_url: document.getElementById('metaCover').value,
      }),
    });
    const data = await resp.json();
    if (data.ok) {
      closeMetaModal();
    } else {
      alert('Save failed: ' + (data.error || 'Unknown error'));
    }
  } catch (e) {
    alert('Save failed: ' + e.message);
  } finally {
    saveBtn.textContent = 'Save';
    saveBtn.disabled = false;
  }
}

// Close modal on overlay click
document.getElementById('metaModal').addEventListener('click', function(e) {
  if (e.target === this) closeMetaModal();
});

// ============================================================
// Per-item File Operations (menu actions)
// ============================================================

// Close all task/history menus when clicking outside
function closeAllTaskMenus(e) {
  if (!e.target.closest('.context-menu')) {
    document.querySelectorAll('.context-menu-dropdown.show').forEach(el => el.classList.remove('show'));
  }
}

// Toggle a specific task/history menu
function toggleTaskMenu(menuId) {
  const menu = document.getElementById(menuId);
  if (!menu) return;
  document.querySelectorAll('.context-menu-dropdown.show').forEach(el => {
    if (el.id !== menuId) el.classList.remove('show');
  });
  menu.classList.toggle('show');
}

// ---- Task actions ----
function deleteTask(taskId) {
  if (!confirm('Remove this task from the task list? (File on disk is not deleted)')) return;
  fetch('/api/tasks/remove', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids: [taskId] }),
  }).then(() => socket.emit("request_tasks"));
}

function redownloadTask(taskId) {
  if (!confirm('Remove this task and restart it?')) return;
  fetch('/api/tasks/redownload', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId }),
  }).then(r => r.json()).then(data => {
    if (data.error) {
      alert('Redownload failed: ' + data.error);
    }
    socket.emit("request_tasks");
  hidePlaylistBanner();
  });
}

function openSingleRename(taskId, filename) {
  const ext = filename ? filename.split('.').pop() : 'mp4';
  const base = filename ? filename.replace(/\.[^.]+$/, '') : '';
  const newBase = prompt('Enter new filename (without extension):', base);
  if (!newBase || newBase.trim() === base) return;
  const newFilename = newBase.trim() + '.' + ext;
  fetch('/api/batch/rename-history', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids: [], filenames: [filename], new_basenames: [newFilename] }),
  }).then(r => r.json()).then(data => {
    if (data.ok) {
      socket.emit("request_tasks");
  hidePlaylistBanner();
    } else {
      alert('Rename failed: ' + (data.error || 'Unknown error'));
    }
  });
}

// ---- History actions ----
let _histCheckedCount = 0;

function getSelectedHistoryIds() {
  return Array.from(document.querySelectorAll('.hist-cb:checked')).map(cb => cb.dataset.ts);
}

function onHistCheckChange() {
  _histCheckedCount = document.querySelectorAll('.hist-cb:checked').length;
  const toolbar = document.getElementById('logToolbar');
  const deleteBtn = document.getElementById('histDeleteBtn');
  const selectAll = document.getElementById('histSelectAll');
  if (_histCheckedCount > 0) {
    toolbar.style.display = 'flex';
    deleteBtn.style.display = 'inline-block';
    selectAll.checked = _histCheckedCount === document.querySelectorAll('.hist-cb').length;
  } else {
    toolbar.style.display = 'none';
    deleteBtn.style.display = 'none';
  }
  // Close delete menu if open
  document.getElementById('histDeleteMenu').style.display = 'none';
}

function toggleAllHistory() {
  const selectAll = document.getElementById('histSelectAll');
  document.querySelectorAll('.hist-cb').forEach(cb => cb.checked = selectAll.checked);
  onHistCheckChange();
}

function toggleHistDeleteMenu() {
  const menu = document.getElementById('histDeleteMenu');
  menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
}

function batchDeleteHistory(deleteFile) {
  const ids = getSelectedHistoryIds();
  if (!ids.length) return;
  if (!confirm(`Delete ${ids.length} record(s)?${deleteFile ? ' Files will also be deleted.' : ''}`)) return;
  fetch('/api/batch/delete-history', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids, delete_file: deleteFile }),
  }).then(r => r.json()).then(data => {
    if (data.ok) {
      document.getElementById('histDeleteMenu').style.display = 'none';
      onHistCheckChange();
      loadHistory(logPage);
    } else {
      alert('Error: ' + (data.error || 'Unknown error'));
    }
  });
}

function deleteHistoryRecord(ts, deleteFile) {
  const label = deleteFile ? 'Delete this record and its file?' : 'Remove this record from the download history?\n(File on disk is NOT deleted.)';
  if (!confirm(label)) return;
  fetch('/api/batch/delete-history', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids: [ts], delete_file: deleteFile }),
  }).then(r => r.json()).then(data => {
    if (data.ok) {
      loadHistory(logPage);
    } else {
      alert('Error: ' + (data.error || 'Unknown error'));
    }
  });
}

function openHistoryRename(ts, filename) {
  const ext = filename ? filename.split('.').pop() : 'mp4';
  const base = filename ? filename.replace(/\.[^.]+$/, '') : '';
  const newBase = prompt('Enter new filename (without extension):', base);
  if (!newBase || newBase.trim() === base) return;
  const newFilename = newBase.trim() + '.' + ext;
  fetch('/api/batch/rename-history', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids: [ts], filenames: [filename], new_basenames: [newFilename] }),
  }).then(r => r.json()).then(data => {
    if (data.ok) {
      loadHistory(logPage);
    } else {
      alert('Rename failed: ' + (data.error || 'Unknown error'));
    }
  });
}

// ---- Move modal ----
let _moveFilenames = null;
  _moveRecordTs = null;
let _moveRecordTs = null;

function openMoveModal(ts, filename) { _moveFilenames = [filename]; _moveRecordTs = ts;
  document.getElementById('moveDestDir').value = '';
  document.getElementById('moveError').textContent = '';
  document.getElementById('moveModal').classList.add('open');
  document.getElementById('moveDestDir').focus();
}

function closeMoveModal() {
  document.getElementById('moveModal').classList.remove('open');
  _moveFilenames = null;
  _moveRecordTs = null;
}

async function submitBatchMove() {
  if (!_moveFilenames || _moveFilenames.length === 0) return;
  const destDir = document.getElementById('moveDestDir').value.trim();
  if (!destDir) {
    document.getElementById('moveError').textContent = 'Please enter a destination directory.';
    return;
  }
  const btn = document.getElementById('moveSubmitBtn');
  btn.disabled = true; btn.textContent = 'Moving...';
  try {
    const res = await fetch('/api/batch/move-history', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: [_moveRecordTs], dest_dir: destDir }),
    });
    const data = await res.json();
    if (data.ok) {
      closeMoveModal();
      loadHistory(logPage);
      socket.emit("request_tasks");
  hidePlaylistBanner();
      if (data.errors && data.errors.length > 0) {
        alert('Moved with errors:\n' + data.errors.join('\n'));
      }
    } else {
      document.getElementById('moveError').textContent = data.error || 'Move failed.';
    }
  } catch (e) {
    document.getElementById('moveError').textContent = 'Request failed: ' + e.message;
  } finally {
    btn.disabled = false; btn.textContent = 'Move';
  }
}

// ---- Rename modal ----
let _renameFilenames = null;

function openRenameModal(filenames) {
  _renameFilenames = filenames;
  document.getElementById('renameNewBasename').value = filenames.length === 1
    ? filenames[0].replace(/\.[^.]+$/, '')
    : '';
  document.getElementById('renameError').textContent = '';
  document.getElementById('renameModal').classList.add('open');
  document.getElementById('renameNewBasename').focus();
}

function closeRenameModal() {
  document.getElementById('renameModal').classList.remove('open');
  _renameFilenames = null;
}

async function submitBatchRename() {
  if (!_renameFilenames || _renameFilenames.length === 0) return;
  const newBasename = document.getElementById('renameNewBasename').value.trim();
  if (!newBasename) {
    document.getElementById('renameError').textContent = 'Please enter a filename base.';
    return;
  }
  const btn = document.getElementById('renameSubmitBtn');
  btn.disabled = true; btn.textContent = 'Renaming...';
  try {
    const res = await fetch('/api/batch/rename-history', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filenames: _renameFilenames, new_basenames: _renameFilenames.map(() => newBasename) }),
    });
    const data = await res.json();
    if (data.ok) {
      closeRenameModal();
      loadHistory(logPage);
      socket.emit("request_tasks");
  hidePlaylistBanner();
      if (data.errors && data.errors.length > 0) {
        alert('Renamed with errors:\n' + data.errors.join('\n'));
      }
    } else {
      document.getElementById('renameError').textContent = data.error || 'Rename failed.';
    }
  } catch (e) {
    document.getElementById('renameError').textContent = 'Request failed: ' + e.message;
  } finally {
    btn.disabled = false; btn.textContent = 'Rename';
  }
}

// Close modals on overlay click
document.getElementById('moveModal').addEventListener('click', function(e) {
  if (e.target === this) closeMoveModal();
});
document.getElementById('renameModal').addEventListener('click', function(e) {
  if (e.target === this) closeRenameModal();
});

// ============================================================
// App ready signal
// ============================================================
// Signal that app.js fully loaded
window._appJsReady = true;
console.log('[app.js] Fully loaded, socket instance:', typeof socket !== 'undefined' ? 'EXISTS' : 'MISSING');

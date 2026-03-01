// ===================== STATE =====================
let authToken = sessionStorage.getItem('jarvis_token');
let tempToken = null;
let currentUser = null;
let currentChatId = localStorage.getItem('jarvis_chat_id') || null;
let socket = null;
let pendingApprovals = [];
let sessionCwd = localStorage.getItem('jarvis_cwd') || '/root/projects';
let allTools = [];
let terminal = null;
let terminalFit = null;
let resourceChart = null;
let fileEditor = null;
let treeCache = {};

// ===================== AUTH =====================
function api(url, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
    return fetch(url, { ...options, headers });
}

async function handleLogin() {
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value.trim();
    const errorEl = document.getElementById('login-error');
    errorEl.classList.add('hidden');
    if (!username || !password) { errorEl.textContent = 'Enter username and password'; errorEl.classList.remove('hidden'); return; }
    try {
        const res = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) });
        const data = await res.json();
        if (!res.ok) { errorEl.textContent = data.error || 'Login failed'; errorEl.classList.remove('hidden'); return; }
        if (data.access_token) {
            authToken = data.access_token;
            sessionStorage.setItem('jarvis_token', authToken);
            currentUser = data.username;
            enterApp();
        }
    } catch (e) { errorEl.textContent = 'Connection error'; errorEl.classList.remove('hidden'); }
}

function handleLogout() {
    authToken = null; sessionStorage.removeItem('jarvis_token'); if (socket) socket.disconnect();
    document.getElementById('app-container').classList.add('hidden'); document.getElementById('login-screen').classList.remove('hidden');
    document.getElementById('login-password').value = '';
}

function enterApp() {
    document.getElementById('login-screen').classList.add('hidden'); document.getElementById('app-container').classList.remove('hidden');
    if (currentUser) document.getElementById('user-display').textContent = currentUser;
    initWebSocket(); pollApprovals(); loadChatList();
}

if (authToken) {
    api('/api/auth/me').then(res => { if (res.ok) return res.json(); throw new Error(); }).then(data => { currentUser = data.username; enterApp(); }).catch(() => { authToken = null; sessionStorage.removeItem('jarvis_token'); });
}

// ===================== WebSocket =====================
function initWebSocket() {
    if (!authToken) return;
    if (typeof io === 'undefined') {
        console.error('Socket.io not loaded. WebSocket features disabled.');
        return;
    }
    try {
        socket = io({ auth: { token: authToken }, reconnection: true, reconnectionAttempts: 5 });
        socket.on('connect', () => console.log('WS connected'));
        socket.on('connect_error', (err) => console.warn('WS Connect Error:', err.message));
        socket.on('approval_required', (data) => { showApprovalModal(data); pollApprovals(); });
        socket.on('tool_log', (data) => console.log('Tool log:', data));
        socket.on('system_heartbeat', (data) => {
            const dot = document.getElementById('ws-status-dot');
            if (dot) { dot.style.backgroundColor = '#10b981'; setTimeout(() => dot.style.backgroundColor = '#374151', 1000); }
        });
    } catch (e) { console.error('WebSocket init error:', e); }
}

// ===================== TABS =====================
function switchTab(tab) {
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
    document.querySelectorAll('.sidebar-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(`tab-${tab}`).classList.remove('hidden');
    document.querySelector(`[data-tab="${tab}"]`)?.classList.add('active');
    if (tab === 'home') refreshHome();
    if (tab === 'chat') loadChatList();
    if (tab === 'terminal') initTerminal();
    if (tab === 'monitor') refreshSystemStatus();
    if (tab === 'docker') refreshDocker();
    if (tab === 'network') refreshNetwork();
    if (tab === 'security') refreshSecurity();
    if (tab === 'packages') refreshPackages();
    if (tab === 'database') refreshDatabase();
    if (tab === 'tools') refreshToolsRegistry();
    if (tab === 'services') refreshServices();
    if (tab === 'audit') refreshAuditLogs();
    if (tab === 'scheduler') refreshScheduler();
    if (tab === 'approvals') pollApprovals();
    if (tab === 'settings') refreshSettings();
}

// ===================== MULTI-CHAT SYSTEM =====================
const chatMessages = document.getElementById('chat-messages');
const chatContainer = document.getElementById('chat-container');
const userInput = document.getElementById('user-input');
const sendButton = document.getElementById('send-button');

userInput.addEventListener('input', function () { this.style.height = 'auto'; this.style.height = this.scrollHeight + 'px'; });
userInput.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
sendButton.addEventListener('click', sendMessage);

async function loadChatList() {
    try {
        const res = await api('/api/chats');
        const data = await res.json();
        const chats = data.chats || [];
        const chatList = document.getElementById('chat-list');

        if (!chats.length) {
            chatList.innerHTML = '<p class="text-gray-600 text-[10px] text-center py-4">No chats yet</p>';
            // Auto-switch to welcome view
            currentChatId = null;
            localStorage.removeItem('jarvis_chat_id');
            showWelcomeView();
            return;
        }

        chatList.innerHTML = chats.map(c => `
            <button onclick="switchChat('${c.id}')"
                class="chat-item w-full text-left px-3 py-2.5 rounded-lg text-xs transition-all hover:bg-dark-700 group ${c.id === currentChatId ? 'bg-dark-700 text-white' : 'text-gray-400'}"
                data-chat-id="${c.id}">
                <div class="flex items-center gap-2">
                    <i class="fa-solid fa-message text-[10px] ${c.id === currentChatId ? 'text-accent-400' : 'text-gray-600'}"></i>
                    <span class="truncate flex-1">${esc(c.title || 'New Chat')}</span>
                </div>
                <div class="text-[9px] text-gray-600 mt-0.5 pl-5">${formatChatDate(c.updated_at)}</div>
            </button>
        `).join('');

        // If we have a current chat, make sure it still exists
        if (currentChatId && !chats.find(c => c.id === currentChatId)) {
            currentChatId = chats[0].id;
            localStorage.setItem('jarvis_chat_id', currentChatId);
        }

        // If no current chat selected but chats exist, pick the newest
        if (!currentChatId && chats.length) {
            switchChat(chats[0].id);
        }
    } catch (e) { console.error('Load chats error:', e); }
}

function formatChatDate(dateStr) {
    if (!dateStr) return '';
    try {
        const d = new Date(dateStr + 'Z');
        const now = new Date();
        const diff = now - d;
        if (diff < 60000) return 'just now';
        if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
        if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    } catch { return ''; }
}

async function createNewChat() {
    try {
        const res = await api('/api/chats', { method: 'POST', body: JSON.stringify({}) });
        const data = await res.json();
        if (data.chat) {
            currentChatId = data.chat.id;
            localStorage.setItem('jarvis_chat_id', currentChatId);
            sessionCwd = data.chat.cwd || '/root/projects';
            document.getElementById('cwd-input').value = sessionCwd;
            loadChatList();
            showWelcomeView();
            document.getElementById('chat-title-header').textContent = 'New Chat';
            document.getElementById('delete-chat-btn').classList.remove('hidden');
        }
    } catch (e) { console.error('Create chat error:', e); }
}

async function switchChat(chatId) {
    currentChatId = chatId;
    localStorage.setItem('jarvis_chat_id', chatId);

    // Highlight active chat in sidebar
    document.querySelectorAll('.chat-item').forEach(el => {
        const isActive = el.dataset.chatId === chatId;
        el.classList.toggle('bg-dark-700', isActive);
        el.classList.toggle('text-white', isActive);
        el.classList.toggle('text-gray-400', !isActive);
        el.querySelector('i').classList.toggle('text-accent-400', isActive);
        el.querySelector('i').classList.toggle('text-gray-600', !isActive);
    });

    // Load chat messages
    try {
        const res = await api(`/api/chats/${chatId}`);
        const data = await res.json();
        if (data.chat) {
            document.getElementById('chat-title-header').textContent = data.chat.title || 'New Chat';
            document.getElementById('delete-chat-btn').classList.remove('hidden');
            sessionCwd = data.chat.cwd || '/root/projects';
            document.getElementById('cwd-input').value = sessionCwd;
        }

        // Render messages
        chatMessages.innerHTML = '';
        const messages = data.messages || [];
        if (!messages.length) {
            showWelcomeView();
        } else {
            messages.forEach(m => {
                if (m.role === 'user') appendUserMessage(m.content);
                else if (m.role === 'assistant') appendAIMessage(m.content);
            });
            scrollChat();
        }
    } catch (e) { console.error('Switch chat error:', e); }
}

async function deleteCurrentChat() {
    if (!currentChatId) return;
    if (!confirm('Delete this chat and all messages?')) return;
    try {
        await api(`/api/chats/${currentChatId}`, { method: 'DELETE' });
        currentChatId = null;
        localStorage.removeItem('jarvis_chat_id');
        loadChatList();
        showWelcomeView();
        document.getElementById('chat-title-header').textContent = 'AI Chat';
        document.getElementById('delete-chat-btn').classList.add('hidden');
    } catch (e) { console.error('Delete chat error:', e); }
}

function showWelcomeView() {
    chatMessages.innerHTML = `
        <div id="chat-welcome" class="text-center py-8 fade-up">
            <div class="w-14 h-14 rounded-2xl bg-dark-800 border border-dark-700 flex items-center justify-center mx-auto mb-4 shadow-2xl shadow-black">
                <i class="fa-solid fa-wand-magic-sparkles text-xl text-accent-400"></i>
            </div>
            <h2 class="text-xl font-light text-white mb-1">How can I help you?</h2>
            <p class="text-gray-500 font-light text-xs">59 tools · System · Files · Deploy · Automation · Security · Communication · WordPress · Email</p>
        </div>
    `;
}

async function sendMessage() {
    const message = userInput.value.trim(); if (!message) return;

    // Auto-create chat if none exists
    if (!currentChatId) {
        try {
            const res = await api('/api/chats', { method: 'POST', body: JSON.stringify({}) });
            const data = await res.json();
            if (data.chat) {
                currentChatId = data.chat.id;
                localStorage.setItem('jarvis_chat_id', currentChatId);
                document.getElementById('delete-chat-btn').classList.remove('hidden');
            }
        } catch (e) { console.error('Auto-create chat error:', e); return; }
    }

    userInput.value = ''; userInput.style.height = 'auto';

    // Remove welcome if visible
    const welcome = document.getElementById('chat-welcome');
    if (welcome) welcome.remove();

    appendUserMessage(message); scrollChat();
    const loadingId = appendLoading(); scrollChat();

    try {
        const res = await api(`/api/chats/${currentChatId}/message`, {
            method: 'POST',
            body: JSON.stringify({ message, cwd: sessionCwd })
        });
        const data = await res.json(); removeEl(loadingId);
        if (data.cwd) { sessionCwd = data.cwd; localStorage.setItem('jarvis_cwd', sessionCwd); const cwdInput = document.getElementById('cwd-input'); if (cwdInput) cwdInput.value = sessionCwd; }
        if (data.status === 'approval_required') { appendAIMessage('This action requires your approval. Check the approval panel.'); showApprovalModal(data); }
        else { appendAIMessage(data.response, data.image_data, data.download_url, data.filename); }

        // Refresh chat list to update title & order
        loadChatList();
    } catch (e) { removeEl(loadingId); appendAIMessage('Connection error: ' + e.message); }
    scrollChat();
}

async function updateCwd(newCwd) {
    try {
        const res = await api('/api/session/cwd', { method: 'POST', body: JSON.stringify({ thread_id: currentChatId || 'default_thread', cwd: newCwd }) });
        const data = await res.json();
        if (data.cwd) { sessionCwd = data.cwd; localStorage.setItem('jarvis_cwd', sessionCwd); document.getElementById('cwd-input').value = sessionCwd; }
        else if (data.error) { alert(data.error); document.getElementById('cwd-input').value = sessionCwd; }
    } catch (e) { console.error('CWD update error:', e); }
}

function scrollChat() { chatContainer.scrollTop = chatContainer.scrollHeight; requestAnimationFrame(() => chatContainer.scrollTop = chatContainer.scrollHeight); }

function appendUserMessage(text) {
    const div = document.createElement('div'); div.className = 'flex gap-3 fade-up justify-end';
    div.innerHTML = `<div class="max-w-[80%]"><div class="bg-dark-800 border border-dark-700 rounded-2xl p-4 text-white text-sm">${esc(text)}</div></div>
        <div class="w-7 h-7 rounded-full bg-dark-700 flex-shrink-0 flex items-center justify-center text-gray-400 mt-1"><i class="fa-solid fa-user text-[10px]"></i></div>`;
    chatMessages.appendChild(div);
}

let _mdLoaderPromise = null;

function _loadScriptOnce(src) {
    return new Promise((resolve, reject) => {
        const existing = document.querySelector(`script[src="${src}"]`);
        if (existing) return resolve();
        const s = document.createElement('script');
        s.src = src;
        s.onload = () => resolve();
        s.onerror = () => reject(new Error('Failed to load ' + src));
        document.head.appendChild(s);
    });
}

function ensureMarkdownLibs() {
    if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') return Promise.resolve();
    if (_mdLoaderPromise) return _mdLoaderPromise;

    _mdLoaderPromise = (async () => {
        if (typeof marked === 'undefined') {
            try { await _loadScriptOnce('https://cdn.jsdelivr.net/npm/marked/marked.min.js'); }
            catch (e) { await _loadScriptOnce('https://unpkg.com/marked/marked.min.js'); }
        }
        if (typeof DOMPurify === 'undefined') {
            try { await _loadScriptOnce('https://cdn.jsdelivr.net/npm/dompurify@3.0.11/dist/purify.min.js'); }
            catch (e) { await _loadScriptOnce('https://unpkg.com/dompurify@3.0.11/dist/purify.min.js'); }
        }
    })().catch(() => { /* ignore loader errors; we still have fallback */ });

    return _mdLoaderPromise;
}

function basicMarkdownToHtml(mdText) {
    const escaped = esc(String(mdText || ''));
    const withCodeBlocks = escaped.replace(/```(\w+)?\n([\s\S]*?)```/g, (m, lang, code) => {
        const cls = lang ? ` class="language-${lang}"` : '';
        return `<pre><code${cls}>${code}</code></pre>`;
    });
    const withInlineCode = withCodeBlocks.replace(/`([^`]+)`/g, '<code>$1</code>');
    const withBold = withInlineCode.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    const withItalic = withBold.replace(/(^|[^*])\*([^*]+)\*(?!\*)/g, '$1<em>$2</em>');
    const withHeadings = withItalic
        .replace(/^######\s+(.+)$/gm, '<h6>$1</h6>')
        .replace(/^#####\s+(.+)$/gm, '<h5>$1</h5>')
        .replace(/^####\s+(.+)$/gm, '<h4>$1</h4>')
        .replace(/^###\s+(.+)$/gm, '<h3>$1</h3>')
        .replace(/^##\s+(.+)$/gm, '<h2>$1</h2>')
        .replace(/^#\s+(.+)$/gm, '<h1>$1</h1>');
    return withHeadings.replace(/\n/g, '<br>');
}

function renderMarkdownSafe(text) {
    try {
        if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            const rawHtml = marked.parse(String(text || ''), { breaks: true, gfm: true });
            return DOMPurify.sanitize(rawHtml);
        }
    } catch (e) { /* fall through */ }
    return basicMarkdownToHtml(text);
}

function appendAIMessage(text, imgData = null, dlUrl = null, filename = null) {
    const div = document.createElement('div'); div.className = 'flex gap-3 fade-up'; let extra = '';
    if (imgData) extra += `<div class="mt-3 rounded-lg overflow-hidden border border-dark-600"><img src="data:image/png;base64,${imgData}" class="max-w-full h-auto" /></div>`;
    if (dlUrl) extra += `<div class="mt-3"><a href="${dlUrl}" class="inline-flex items-center gap-2 px-4 py-2 bg-accent-500 hover:bg-accent-400 text-white text-xs rounded-lg transition-all"><i class="fa-solid fa-download text-[10px]"></i> Download ${esc(filename || 'file')}</a></div>`;
    const msgId = 'ai-msg-' + Date.now() + '-' + Math.floor(Math.random() * 1000000);
    const html = renderMarkdownSafe(text);
    div.innerHTML = `<div class="w-7 h-7 rounded bg-dark-800 border border-dark-700 flex-shrink-0 flex items-center justify-center text-accent-400 mt-1"><i class="fa-solid fa-robot text-[10px]"></i></div>
        <div class="max-w-[80%]"><div id="${msgId}" class="prose prose-invert prose-sm text-gray-300">${html}${extra}</div></div>`;
    chatMessages.appendChild(div);

    ensureMarkdownLibs().then(() => {
        const el = document.getElementById(msgId);
        if (!el) return;
        el.innerHTML = `${renderMarkdownSafe(text)}${extra}`;
    });
}

function appendLoading() {
    const id = 'load-' + Date.now(); const div = document.createElement('div'); div.id = id; div.className = 'flex gap-3 fade-up';
    div.innerHTML = `<div class="w-7 h-7 rounded bg-dark-800 border border-dark-700 flex-shrink-0 flex items-center justify-center text-accent-400 mt-1"><i class="fa-solid fa-robot text-[10px]"></i></div>
        <div class="bg-dark-800/50 border border-dark-700/50 rounded-2xl p-3 flex gap-1 items-center"><div class="w-2 h-2 bg-accent-500/50 rounded-full animate-bounce"></div><div class="w-2 h-2 bg-accent-500/50 rounded-full animate-bounce" style="animation-delay:100ms"></div><div class="w-2 h-2 bg-accent-500/50 rounded-full animate-bounce" style="animation-delay:200ms"></div></div>`;
    chatMessages.appendChild(div); return id;
}

function removeEl(id) { const el = document.getElementById(id); if (el) el.remove(); }
function esc(t) { if (!t) return ''; const m = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }; return String(t).replace(/[&<>"']/g, c => m[c]); }

// ===================== APPROVALS =====================
function showApprovalModal(data) {
    document.getElementById('modal-tool-name').textContent = data.tool || 'Unknown';
    document.getElementById('modal-args-preview').textContent = data.args_preview || JSON.stringify(data.args || {});
    document.getElementById('approval-modal').classList.remove('hidden');
    const approvalId = data.approval_id;
    document.getElementById('modal-approve-btn').onclick = () => resolveApproval(approvalId, 'approve');
    document.getElementById('modal-deny-btn').onclick = () => resolveApproval(approvalId, 'deny');
}

async function resolveApproval(id, action) {
    try { await api(`/api/approvals/${id}/${action}`, { method: 'POST' }); document.getElementById('approval-modal').classList.add('hidden'); pollApprovals(); } catch (e) { console.error('Approval error:', e); }
}

async function pollApprovals() {
    try {
        const res = await api('/api/approvals/pending'); const data = await res.json();
        pendingApprovals = data.approvals || [];
        const badge = document.getElementById('approval-badge-container'); const count = document.getElementById('approval-count');
        if (pendingApprovals.length > 0) { badge.classList.remove('hidden'); count.textContent = pendingApprovals.length; } else { badge.classList.add('hidden'); }
        renderApprovals();
    } catch (e) { /* ignore */ }
}

function renderApprovals() {
    const container = document.getElementById('approvals-content');
    if (!pendingApprovals.length) { container.innerHTML = '<p class="text-gray-500 text-sm">No pending approvals.</p>'; return; }
    container.innerHTML = pendingApprovals.map(a => `
        <div class="bg-dark-800 border border-dark-700 rounded-xl p-4 mb-3 fade-up">
            <div class="flex items-center justify-between mb-2">
                <span class="text-white text-sm"><i class="fa-solid fa-triangle-exclamation text-danger-400 mr-2"></i>${esc(a.tool_name)}</span>
                <span class="text-[10px] text-gray-500">${a.created_at}</span>
            </div>
            <pre class="text-xs text-accent-400 bg-dark-900 rounded p-2 mb-3">${esc(a.args_preview || '')}</pre>
            <div class="flex gap-2">
                <button onclick="resolveApproval('${a.id}','deny')" class="flex-1 py-1.5 rounded bg-dark-700 hover:bg-dark-600 text-gray-300 text-xs transition-all">Deny</button>
                <button onclick="resolveApproval('${a.id}','approve')" class="flex-1 py-1.5 rounded bg-accent-500 hover:bg-accent-400 text-white text-xs transition-all">Approve</button>
            </div>
        </div>`).join('');
}

setInterval(pollApprovals, 10000);

// ===================== TERMINAL =====================
function initTerminal() {
    if (terminal) return;
    if (typeof Terminal === 'undefined') {
        alert('Terminal library (xterm.js) not loaded. Please check your internet connection and refresh.');
        return;
    }
    const container = document.getElementById('terminal-container');
    terminal = new Terminal({
        cursorBlink: true,
        fontFamily: 'JetBrains Mono, Fira Code, monospace',
        fontSize: 14,
        theme: { background: '#0c0c0c', foreground: '#d1d5db', accent: '#10b981' }
    });
    terminal.open(container);

    // Fit terminal
    const cols = Math.floor(container.clientWidth / 9) || 80;
    const rows = Math.floor(container.clientHeight / 20) || 24;
    terminal.resize(cols, rows);

    if (socket && socket.connected) {
        socket.emit('terminal_start', { token: authToken });
    } else {
        terminal.write('\x1b[31m[Waiting for WebSocket...]\x1b[0m\r\n');
        const checkConn = setInterval(() => {
            if (socket && socket.connected) {
                socket.emit('terminal_start', { token: authToken });
                clearInterval(checkConn);
            }
        }, 1000);
    }

    terminal.onData(data => {
        socket.emit('terminal_input', { data });
    });

    socket.on('terminal_output', data => {
        terminal.write(data.data);
    });

    socket.on('terminal_ready', () => {
        terminal.write('\r\n\x1b[32m[Jarvis PTY Connected]\x1b[0m\r\n');
    });

    window.addEventListener('resize', () => {
        const cols = Math.floor(container.clientWidth / 9);
        const rows = Math.floor(container.clientHeight / 20);
        terminal.resize(cols, rows);
        socket.emit('terminal_resize', { cols, rows });
    });
}

function reconnectTerminal() {
    if (terminal) {
        terminal.dispose();
        terminal = null;
        document.getElementById('terminal-container').innerHTML = '';
    }
    initTerminal();
}

// ===================== HOME DASHBOARD = [NEW] =====================
async function refreshHome() {
    const statsGrid = document.getElementById('home-stats-grid');
    const activityList = document.getElementById('home-activity-list');
    statsGrid.innerHTML = '<div class="col-span-4 text-gray-500 text-center animate-pulse py-4">Loading dashboard...</div>';

    try {
        const res = await api('/api/system/overview');
        const data = await res.json();

        // Stats Grid
        statsGrid.innerHTML = `
            ${infoCard('CPU Usage', (data.cpu_percent || 0).toFixed(1) + '%', 'microchip')}
            ${infoCard('Memory', (data.ram_percent || 0).toFixed(1) + '%', 'memory')}
            ${infoCard('Disk', (data.disk_percent || 0).toFixed(1) + '%', 'hard-drive')}
            ${infoCard('Uptime', data.uptime || '0m', 'clock')}
        `;

        // Resource Chart
        initResourceChart(data.history || []);

        // Recent Activity (Audit logs mock-integration for home)
        const auditRes = await api('/api/audit/logs?limit=5');
        const auditData = await auditRes.json();
        const logs = auditData.logs || [];
        activityList.innerHTML = logs.map(l => `
            <div class="flex items-center justify-between text-xs border-b border-dark-700 pb-2 last:border-0 last:pb-0">
                <span class="text-white font-mono">${esc(l.tool_name)}</span>
                <span class="${l.status === 'executed' ? 'text-accent-400' : 'text-danger-400'} uppercase">${l.status}</span>
            </div>
        `).join('') || '<p class="text-gray-600">No recent activity</p>';

    } catch (e) { statsGrid.innerHTML = `<p class="text-danger-400 text-sm">Error: ${e.message}</p>`; }
}

function initResourceChart(history = []) {
    const ctx = document.getElementById('resource-chart');
    if (!ctx) return;
    if (typeof Chart === 'undefined') { console.warn('Chart.js not loaded'); return; }
    if (resourceChart) resourceChart.destroy();

    const labels = history.map(h => h.time || '');
    const cpuData = history.map(h => h.cpu);
    const memData = history.map(h => h.mem);

    resourceChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                { label: 'CPU', data: cpuData, borderColor: '#818cf8', backgroundColor: 'rgba(129, 140, 248, 0.1)', fill: true, tension: 0.4, borderWidth: 1.5, pointRadius: 0 },
                { label: 'RAM', data: memData, borderColor: '#10b981', backgroundColor: 'rgba(16, 185, 129, 0.1)', fill: true, tension: 0.4, borderWidth: 1.5, pointRadius: 0 }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { display: false },
                y: { grid: { color: '#151e32' }, ticks: { color: '#6b7280', font: { size: 10 } }, min: 0, max: 100 }
            }
        }
    });
}

// ===================== DOCKER = [NEW] =====================
async function refreshDocker() {
    const grid = document.getElementById('docker-containers');
    grid.innerHTML = '<div class="col-span-3 text-gray-500 animate-pulse">Scanning containers...</div>';
    try {
        const res = await api('/api/docker/containers');
        const data = await res.json();
        const containers = data.containers || [];
        if (!containers.length) { grid.innerHTML = '<p class="text-gray-600 col-span-3">No containers found</p>'; return; }
        grid.innerHTML = containers.map(c => `
            <div class="bg-dark-800 border border-dark-700 rounded-xl p-4 fade-up">
                <div class="flex items-center justify-between mb-2">
                    <span class="text-white text-xs font-semibold truncate">${esc(c.name)}</span>
                    <span class="px-2 py-0.5 rounded text-[10px] uppercase ${c.state === 'running' ? 'bg-accent-500/10 text-accent-400' : 'bg-gray-700 text-gray-400'}">${c.state}</span>
                </div>
                <div class="text-[10px] text-gray-500 font-mono mb-3 truncate">${esc(c.image)}</div>
                <div class="grid grid-cols-2 gap-2 mb-4">
                    <div class="bg-dark-900 rounded p-2 text-center"><p class="text-[9px] text-gray-500 uppercase">CPU</p><p class="text-accent-400">${c.cpu_usage || '0.0%'}</p></div>
                    <div class="bg-dark-900 rounded p-2 text-center"><p class="text-[9px] text-gray-500 uppercase">MEM</p><p class="text-accent-400">${c.mem_usage || '0.0%'}</p></div>
                </div>
                <div class="flex gap-2">
                    ${c.state === 'running'
                ? `<button onclick="dockerAction('${c.id}', 'stop')" class="flex-1 py-1.5 rounded bg-dark-700 hover:bg-dark-600 text-[10px]">Stop</button>`
                : `<button onclick="dockerAction('${c.id}', 'start')" class="flex-1 py-1.5 rounded bg-accent-500 text-white text-[10px]">Start</button>`
            }
                    <button onclick="dockerAction('${c.id}', 'restart')" class="flex-1 py-1.5 rounded bg-dark-700 hover:bg-dark-600 text-[10px]">Restart</button>
                </div>
            </div>
        `).join('');
    } catch (e) { grid.innerHTML = `<p class="text-danger-400">Error: ${e.message}</p>`; }
}

async function dockerAction(id, action) {
    try {
        await api(`/api/docker/containers/${id}/${action}`, { method: 'POST' });
        setTimeout(refreshDocker, 1500);
    } catch (e) { alert('Docker error: ' + e.message); }
}

// ===================== NETWORK = [NEW] =====================
async function refreshNetwork() {
    const ufwGrid = document.getElementById('ufw-rules');
    const netGrid = document.getElementById('net-connections');
    ufwGrid.innerHTML = 'Loading Rules...';
    netGrid.innerHTML = 'Loading Connections...';
    try {
        const [uRes, nRes] = await Promise.all([api('/api/firewall/rules'), api('/api/network/connections')]);
        const uData = await uRes.json();
        const nData = await nRes.json();

        ufwGrid.innerHTML = `<h3 class="text-white text-xs mb-3">Firewall Rules</h3><div class="space-y-1">${(uData.rules || []).map(r => `
            <div class="flex justify-between text-[11px] font-mono border-b border-dark-700/50 py-1">
                <span class="text-gray-400">${esc(r.to)}</span>
                <span class="text-accent-400">${esc(r.action)}</span>
            </div>
        `).join('') || '<p class="text-gray-600">No rules found</p>'}</div>`;

        netGrid.innerHTML = `<h3 class="text-white text-xs mb-3">Active Connections</h3><div class="max-h-64 overflow-y-auto space-y-1">${(nData.connections || []).map(c => `
            <div class="flex justify-between text-[10px] font-mono border-b border-dark-700/50 py-1">
                <span class="text-gray-500 truncate w-32">${esc(c.laddr)}</span>
                <span class="text-gray-600">→</span>
                <span class="text-gray-400 truncate w-32">${esc(c.raddr || '*')}</span>
                <span class="text-accent-400">${esc(c.status)}</span>
            </div>
        `).join('')}</div>`;
    } catch (e) { ufwGrid.innerHTML = 'Error loading network data'; }
}

// ===================== SECURITY = [NEW] =====================
async function refreshSecurity() {
    const container = document.getElementById('security-content');
    container.innerHTML = '<div class="flex items-center gap-2 text-gray-500 text-sm animate-pulse"><i class="fa-solid fa-shield-halved"></i> Running security audit...</div>';
    try {
        const [aRes, sRes] = await Promise.all([api('/api/security/audit', { method: 'POST' }), api('/api/ssh/keys')]);
        const audit = await aRes.json();
        const keys = await sRes.json();

        container.innerHTML = `
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                <div class="bg-dark-800 border border-dark-700 rounded-xl p-4">
                    <h3 class="text-white text-xs mb-3">Audit Score</h3>
                    <div class="flex items-center gap-4">
                        <div class="text-3xl font-bold ${audit.score > 80 ? 'text-accent-400' : 'text-danger-400'}">${audit.score || 0}%</div>
                        <div class="text-[10px] text-gray-500 uppercase tracking-tighter">System Hardening Status</div>
                    </div>
                </div>
                ${(audit.checks || []).map(c => `
                    <div class="bg-dark-800 border border-dark-700 rounded-xl p-4 flex justify-between items-center">
                        <span class="text-xs text-gray-300">${esc(c.name)}</span>
                        <i class="fa-solid fa-${c.status === 'PASS' ? 'check-circle text-accent-400' : 'warning text-danger-400'} text-sm"></i>
                    </div>
                `).join('')}
            </div>
            <div class="bg-dark-800 border border-dark-700 rounded-xl p-4">
                <h3 class="text-white text-xs mb-3">SSH Authorized Keys</h3>
                <div class="space-y-2">${(keys.keys || []).map(k => `
                    <div class="flex justify-between items-center bg-dark-900 rounded p-2 text-[10px] font-mono">
                        <span class="truncate w-64 text-gray-400">${esc(k.comment)}</span>
                        <button class="text-danger-400 hover:text-danger-300">Remove</button>
                    </div>
                `).join('') || '<p class="text-gray-600 text-xs text-center">No keys found</p>'}</div>
            </div>
        `;
    } catch (e) { container.innerHTML = 'Error auditing system'; }
}

// ===================== PACKAGES = [NEW] =====================
async function refreshPackages() {
    const container = document.getElementById('packages-content');
    container.innerHTML = '<div class="text-gray-500 animate-pulse">Scanning packages...</div>';
    try {
        const [pRes, cRes] = await Promise.all([api('/api/packages'), api('/api/crontab')]);
        const pData = await pRes.json();
        const cData = await cRes.json();

        container.innerHTML = `
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div class="bg-dark-800 border border-dark-700 rounded-xl p-4 flex flex-col h-[400px]">
                    <h3 class="text-white text-xs mb-3 flex justify-between">
                        <span>System Packages</span>
                        <span class="text-accent-400">${(pData.packages || []).length} items</span>
                    </h3>
                    <div class="flex-1 overflow-y-auto space-y-1 pr-2 custom-scrollbar">
                        ${(pData.packages || []).map(p => `<div class="flex justify-between text-[10px] font-mono border-b border-dark-700/50 py-1"><span class="text-gray-400">${esc(p.name)}</span><span class="text-gray-600">${esc(p.version)}</span></div>`).join('')}
                    </div>
                </div>
                <div class="bg-dark-800 border border-dark-700 rounded-xl p-4 flex flex-col h-[400px]">
                    <h3 class="text-white text-xs mb-3">Crontab (Scheduled Tasks)</h3>
                    <div class="flex-1 overflow-y-auto space-y-3">
                        ${(cData.entries || []).map(c => `
                            <div class="bg-dark-900 rounded p-3 border border-dark-700/50">
                                <div class="text-white text-[10px] font-mono mb-1 truncate">${esc(c.command)}</div>
                                <div class="flex justify-between text-[9px]">
                                    <span class="text-accent-400">${esc(c.schedule)}</span>
                                    <span class="text-gray-500">${esc(c.human)}</span>
                                </div>
                            </div>
                        `).join('') || '<p class="text-gray-600 text-[10px]">No cron entries</p>'}
                    </div>
                </div>
            </div>
        `;
    } catch (e) { container.innerHTML = 'Error loading packages'; }
}

// ===================== SYSTEM MONITOR =====================
function gaugeHTML(label, value, icon, color) {
    const pct = Math.min(100, Math.max(0, value));
    const circ = 2 * Math.PI * 36;
    const offset = circ - (pct / 100) * circ;
    const barColor = pct > 85 ? '#ef4444' : pct > 60 ? '#fbbf24' : color;
    return `<div class="bg-dark-800 border border-dark-700 rounded-xl p-5 flex flex-col items-center gap-2 fade-up">
        <svg width="90" height="90" viewBox="0 0 80 80"><circle cx="40" cy="40" r="36" fill="none" stroke="#151e32" stroke-width="6"/>
        <circle cx="40" cy="40" r="36" fill="none" stroke="${barColor}" stroke-width="6" stroke-linecap="round" stroke-dasharray="${circ}" stroke-dashoffset="${offset}" class="gauge-ring" transform="rotate(-90 40 40)"/></svg>
        <div class="text-center -mt-[62px] mb-4"><p class="text-xl font-normal text-white">${pct.toFixed(0)}%</p></div>
        <div class="flex items-center gap-2 mt-2"><i class="fa-solid fa-${icon} text-xs" style="color:${color}"></i><span class="text-xs text-gray-400">${label}</span></div>
    </div>`;
}

function infoCard(label, value, icon) {
    return `<div class="bg-dark-800 border border-dark-700 rounded-xl p-4 fade-up">
        <div class="flex items-center gap-2 mb-1"><i class="fa-solid fa-${icon} text-accent-400 text-xs"></i><span class="text-[10px] text-gray-500 uppercase tracking-wider">${label}</span></div>
        <p class="text-sm text-white font-mono">${esc(value)}</p>
    </div>`;
}

async function refreshSystemStatus() {
    const container = document.getElementById('monitor-content');
    container.innerHTML = '<div class="flex items-center gap-2 text-gray-500 text-sm"><i class="fa-solid fa-spinner animate-spin"></i> Loading...</div>';
    try {
        const [hRes, oRes] = await Promise.all([fetch('/health'), api('/api/system/overview')]);
        const health = await hRes.json();
        const data = await oRes.json();

        const badge = document.getElementById('health-badge');
        badge.textContent = health.status === 'healthy' ? 'HEALTHY' : 'UNHEALTHY';
        badge.className = health.status === 'healthy' ? 'text-[10px] px-2 py-0.5 rounded-full bg-accent-500/10 text-accent-400' : 'text-[10px] px-2 py-0.5 rounded-full bg-danger-500/10 text-danger-400';

        const cpu = data.cpu_percent || health.cpu_percent || 0;
        const ram = data.ram_percent || health.ram_percent || 0;
        const disk = data.disk_percent || health.disk_percent || 0;

        container.innerHTML = `
            <div class="grid grid-cols-3 gap-4 mb-6">${gaugeHTML('CPU', cpu, 'microchip', '#818cf8')}${gaugeHTML('RAM', ram, 'memory', '#10b981')}${gaugeHTML('Disk', disk, 'hard-drive', '#fb923c')}</div>
            <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
                ${infoCard('OS', data.os, 'display')}
                ${infoCard('Hostname', data.hostname, 'server')}
                ${infoCard('Uptime', data.uptime, 'clock')}
                ${infoCard('User', data.user, 'user')}
            </div>
            <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
                ${infoCard('Local IP', data.local_ip, 'network-wired')}
                ${infoCard('Public IP', data.public_ip, 'globe')}
                ${infoCard('Tools', health.tools_registered + ' registered', 'wrench')}
                ${infoCard('Database', health.db || 'unknown', 'database')}
            </div>
            <div class="bg-dark-800 border border-dark-700 rounded-xl p-4 fade-up">
                <p class="text-[10px] text-gray-500 uppercase tracking-wider mb-2">System Metadata</p>
                <div class="grid grid-cols-2 gap-4 text-xs font-mono">
                    <div class="space-y-1">
                        <p class="text-gray-500">RAM: <span class="text-accent-400">${data.ram_used_gb}/${data.ram_total_gb} GB</span></p>
                        <p class="text-gray-500">Disk: <span class="text-accent-400">${data.disk_used_gb}/${data.disk_total_gb} GB</span></p>
                    </div>
                    <div class="space-y-1">
                        <p class="text-gray-500">Load: <span class="text-accent-400">${data.load_avg.map(v => v.toFixed(2)).join(', ')}</span></p>
                        <p class="text-gray-500">Cores: <span class="text-accent-400">${data.cpu_count}</span></p>
                    </div>
                </div>
            </div>`;
    } catch (e) { container.innerHTML = `<p class="text-danger-400 text-sm">Error: ${e.message}</p>`; }
}

// ===================== TOOLS REGISTRY =====================
async function refreshToolsRegistry() {
    const container = document.getElementById('tools-content');
    container.innerHTML = '<div class="flex items-center gap-2 text-gray-500 text-sm"><i class="fa-solid fa-spinner animate-spin"></i> Loading...</div>';
    try {
        const res = await api('/api/tools/registry');
        const data = await res.json();
        allTools = data.tools || [];
        renderTools(allTools);
    } catch (e) { container.innerHTML = `<p class="text-danger-400 text-sm">Error: ${e.message}</p>`; }
}

function filterTools() {
    const search = document.getElementById('tool-search').value.toLowerCase();
    const cat = document.getElementById('tool-cat-filter').value;
    const risk = document.getElementById('tool-risk-filter').value;
    let filtered = allTools;
    if (search) filtered = filtered.filter(t => t.name.toLowerCase().includes(search) || (t.description || '').toLowerCase().includes(search));
    if (cat !== 'all') filtered = filtered.filter(t => t.category === cat);
    if (risk !== 'all') filtered = filtered.filter(t => t.risk_level === risk);
    renderTools(filtered);
}

function renderTools(tools) {
    const container = document.getElementById('tools-content');
    if (!tools.length) { container.innerHTML = '<p class="text-gray-500 text-sm">No tools match your filters.</p>'; return; }
    // Summary bar
    const cats = {}; const risks = { LOW: 0, MEDIUM: 0, HIGH: 0 };
    allTools.forEach(t => { cats[t.category] = (cats[t.category] || 0) + 1; risks[t.risk_level] = (risks[t.risk_level] || 0) + 1; });

    let html = `<div class="flex flex-wrap items-center gap-3 mb-5 fade-up">
        <span class="text-white text-sm font-normal">${allTools.length} Tools</span>
        <span class="text-gray-500 text-xs">|</span>
        ${Object.entries(cats).map(([c, n]) => `<span class="cat-pill cat-${c}">${c} ${n}</span>`).join('')}
        <span class="text-gray-500 text-xs">|</span>
        <span class="text-xs risk-low">● ${risks.LOW} Low</span>
        <span class="text-xs risk-medium">● ${risks.MEDIUM} Med</span>
        <span class="text-xs risk-high">● ${risks.HIGH} High</span>
        <span class="text-gray-500 text-xs ml-auto">Showing ${tools.length}</span>
    </div>`;

    html += '<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">';
    tools.forEach(t => {
        const riskClass = t.risk_level === 'HIGH' ? 'risk-high' : t.risk_level === 'MEDIUM' ? 'risk-medium' : 'risk-low';
        const riskIcon = t.risk_level === 'HIGH' ? '🔴' : t.risk_level === 'MEDIUM' ? '🟡' : '🟢';
        html += `<div class="tool-card bg-dark-800 border border-dark-700 rounded-xl p-4 transition-all cursor-default fade-up">
            <div class="flex items-start justify-between mb-2">
                <span class="text-white text-sm font-mono">${esc(t.name)}</span>
                <span class="text-xs ${riskClass}">${riskIcon} ${t.risk_level}</span>
            </div>
            <p class="text-xs text-gray-500 mb-3 line-clamp-2">${esc(t.description || 'No description')}</p>
            <span class="cat-pill cat-${t.category}">${t.category}</span>
        </div>`;
    });
    html += '</div>';
    container.innerHTML = html;
}

async function runSelfTest() {
    const container = document.getElementById('tools-content');
    const btn = document.querySelector('[onclick="runSelfTest()"]');
    btn.innerHTML = '<i class="fa-solid fa-spinner animate-spin mr-1"></i>Testing...';
    try {
        const res = await api('/api/tools/selftest', { method: 'POST' });
        const data = await res.json();
        let html = '<div class="mb-4"><h3 class="text-white text-sm mb-3">Self-Test Results</h3><div class="space-y-2">';
        Object.entries(data.selftest || {}).forEach(([name, result]) => {
            const ok = result.status === 'OK';
            html += `<div class="bg-dark-800 border border-dark-700 rounded-lg p-3 flex items-center justify-between fade-up">
                <span class="text-sm font-mono ${ok ? 'text-accent-400' : 'text-danger-400'}">${esc(name)}</span>
                <div class="flex items-center gap-2">
                    ${result.output_length ? `<span class="text-[10px] text-gray-500">${result.output_length} chars</span>` : ''}
                    <span class="text-xs ${ok ? 'text-accent-400' : 'text-danger-400'}"><i class="fa-solid fa-${ok ? 'check' : 'xmark'} mr-1"></i>${result.status}</span>
                </div>
            </div>`;
        });
        html += '</div><button onclick="refreshToolsRegistry()" class="mt-3 text-xs text-accent-400 hover:text-accent-300 transition-colors">← Back to Tools</button></div>';
        container.innerHTML = html;
    } catch (e) { container.innerHTML = `<p class="text-danger-400 text-sm">Self-test error: ${e.message}</p>`; }
    btn.innerHTML = '<i class="fa-solid fa-vial mr-1"></i>Self-Test';
}

// ===================== SERVICES =====================
async function refreshServices() {
    const container = document.getElementById('services-content');
    container.innerHTML = '<div class="flex items-center gap-2 text-gray-500 text-sm"><i class="fa-solid fa-spinner animate-spin"></i> Loading...</div>';
    try {
        const res = await api('/api/services');
        const data = await res.json();
        const services = data.services || [];
        if (!services.length) {
            container.innerHTML = `<div class="text-center py-16 fade-up">
                <div class="w-14 h-14 rounded-2xl bg-dark-800 border border-dark-700 flex items-center justify-center mx-auto mb-4">
                    <i class="fa-solid fa-server text-xl text-gray-600"></i>
                </div>
                <p class="text-gray-500 text-sm mb-1">No active services</p>
                <p class="text-gray-600 text-xs">Deploy a site via chat to see it here</p>
            </div>`;
            return;
        }
        container.innerHTML = `<div class="grid grid-cols-1 md:grid-cols-2 gap-4">${services.map(s => `
            <div class="svc-card bg-dark-800 border border-dark-700 rounded-xl p-5 fade-up">
                <div class="flex items-center justify-between mb-3">
                    <div class="flex items-center gap-2">
                        <div class="w-2 h-2 rounded-full bg-accent-400 animate-pulse"></div>
                        <span class="text-white text-sm font-normal">${esc(s.name)}</span>
                    </div>
                    <span class="text-[10px] text-gray-500">PID: ${s.pid}</span>
                </div>
                <div class="space-y-2 text-xs">
                    <div class="flex justify-between"><span class="text-gray-500">URL</span><a href="${esc(s.url)}" target="_blank" class="text-accent-400 hover:underline">${esc(s.url)}</a></div>
                    <div class="flex justify-between"><span class="text-gray-500">Directory</span><span class="text-gray-300 font-mono">${esc(s.directory)}</span></div>
                </div>
                <button onclick="stopService('${esc(s.name)}')" class="mt-3 w-full py-2 rounded-lg bg-danger-500/10 hover:bg-danger-500/20 text-danger-400 text-xs transition-all border border-danger-500/20">
                    <i class="fa-solid fa-stop mr-1"></i> Stop Service
                </button>
            </div>`).join('')}</div>`;
    } catch (e) { container.innerHTML = `<p class="text-danger-400 text-sm">Error: ${e.message}</p>`; }
}

async function stopService(name) {
    try {
        await api('/api/chat', { method: 'POST', body: JSON.stringify({ message: `stop deployed service ${name}`, thread_id: threadId }) });
        setTimeout(refreshServices, 1000);
    } catch (e) { console.error(e); }
}

// ===================== FILES =====================
// ===================== FILES (Enhanced) =====================
async function loadFiles(path = sessionCwd) {
    const container = document.getElementById('files-content');
    const tree = document.getElementById('file-tree');
    const breadcrumbs = document.getElementById('file-breadcrumbs');
    container.innerHTML = '<div class="col-span-8 text-gray-500 text-center py-8 animate-pulse">Loading files...</div>';

    // Update Breadcrumbs
    const parts = path.split('/').filter(p => p);
    breadcrumbs.innerHTML = `<span onclick="loadFiles('/')" class="cursor-pointer hover:text-accent-400">root</span>` +
        parts.map((p, i) => `<span>/</span><span onclick="loadFiles('/${parts.slice(0, i + 1).join('/')}')" class="cursor-pointer hover:text-accent-400">${esc(p)}</span>`).join('');

    try {
        const res = await api(`/api/files/tree?path=${encodeURIComponent(path)}&depth=1`);
        const data = await res.json();
        const items = data.tree || [];

        if (tree.innerHTML === '') renderFileTree(items, tree);

        container.innerHTML = items.map(f => {
            const icon = f.type === 'directory' ? 'folder text-yellow-500' : 'file-lines text-gray-400';
            return `
                <div class="bg-dark-800/50 border border-dark-700/50 rounded-xl p-4 flex flex-col items-center gap-2 hover:bg-dark-700/50 transition-all cursor-pointer group" onclick="${f.type === 'directory' ? `loadFiles('${esc(f.path)}')` : `openFileInEditor('${esc(f.path)}')`}">
                    <i class="fa-solid fa-${icon} text-2xl mb-1 group-hover:scale-110 transition-transform"></i>
                    <span class="text-[10px] text-gray-300 text-center truncate w-full font-mono">${esc(f.name)}</span>
                </div>
            `;
        }).join('') || '<p class="col-span-8 text-gray-600 text-center py-8">Empty directory</p>';

    } catch (e) { container.innerHTML = `<p class="col-span-8 text-danger-400 text-center">Error: ${e.message}</p>`; }
}

function renderFileTree(items, container) {
    container.innerHTML = items.map(f => `
        <div class="tree-node py-1 px-2 rounded flex items-center gap-2" onclick="${f.type === 'directory' ? `loadFiles('${esc(f.path)}')` : `openFileInEditor('${esc(f.path)}')`}">
            <i class="fa-solid fa-${f.type === 'directory' ? 'folder text-yellow-500' : 'file text-gray-400'} text-[10px]"></i>
            <span class="truncate">${esc(f.name)}</span>
        </div>
    `).join('');
}

async function openFileInEditor(path) {
    const editorContainer = document.getElementById('file-editor-container');
    const editorWrapper = document.getElementById('editor-wrapper');
    const filenameEl = document.getElementById('editor-filename');

    filenameEl.textContent = path.split('/').pop();
    filenameEl.dataset.path = path;
    editorContainer.classList.remove('hidden');

    try {
        const res = await api(`/api/files/read?path=${encodeURIComponent(path)}`);
        const data = await res.json();

        if (fileEditor) {
            fileEditor.setValue(data.content || '');
        } else {
            if (typeof CodeMirror === 'undefined') {
                editorWrapper.innerHTML = `<textarea class="w-full h-full bg-dark-900 text-gray-300 p-4 font-mono text-sm outline-none" id="fallback-textarea">${esc(data.content || '')}</textarea>`;
                fileEditor = { getValue: () => document.getElementById('fallback-textarea').value, setValue: (v) => document.getElementById('fallback-textarea').value = v };
            } else {
                fileEditor = CodeMirror(editorWrapper, {
                    value: data.content || '',
                    mode: 'python',
                    theme: 'dracula',
                    lineNumbers: true,
                    autoCloseBrackets: true,
                    matchBrackets: true,
                    indentUnit: 4,
                    tabSize: 4,
                    lineWrapping: true
                });
            }
        }
    } catch (e) { alert('Error reading file'); }
}

function closeEditor() {
    document.getElementById('file-editor-container').classList.add('hidden');
}

async function saveFile() {
    const path = document.getElementById('editor-filename').dataset.path;
    const content = fileEditor.getValue();
    try {
        const res = await api('/api/files/write', { method: 'POST', body: JSON.stringify({ path, content }) });
        if (res.ok) { closeEditor(); loadFiles(sessionCwd); }
        else { alert('Error saving file'); }
    } catch (e) { alert('Save error'); }
}

function createNewFile() {
    const name = prompt('Enter filename:');
    if (name) openFileInEditor(sessionCwd + '/' + name);
}

// ===================== SCHEDULER =====================
async function refreshScheduler() {
    const container = document.getElementById('scheduler-content');
    container.innerHTML = '<div class="flex items-center gap-2 text-gray-500 text-sm"><i class="fa-solid fa-spinner animate-spin"></i> Loading...</div>';
    try {
        const res = await api('/api/scheduler/tasks'); const data = await res.json();
        const tasks = data.tasks || [];
        if (!tasks.length) {
            container.innerHTML = `<div class="text-center py-16 fade-up">
                <div class="w-14 h-14 rounded-2xl bg-dark-800 border border-dark-700 flex items-center justify-center mx-auto mb-4">
                    <i class="fa-solid fa-clock text-xl text-gray-600"></i>
                </div>
                <p class="text-gray-500 text-sm mb-1">No scheduled tasks</p>
                <p class="text-gray-600 text-xs">Ask Jarvis to schedule a task via chat</p>
            </div>`;
            return;
        }
        container.innerHTML = tasks.map(t => `
            <div class="bg-dark-800 border border-dark-700 rounded-xl p-4 mb-3 fade-up">
                <div class="flex justify-between items-start">
                    <div>
                        <p class="text-white text-sm font-mono">${esc(t.command)}</p>
                        <p class="text-gray-500 text-xs mt-1"><i class="fa-solid fa-clock text-[10px] mr-1"></i>Cron: <span class="text-accent-400">${esc(t.cron_expression)}</span> | Last: ${t.last_run || 'Never'}</p>
                    </div>
                    <button onclick="cancelTask('${t.id}')" class="text-xs text-danger-400 hover:text-danger-300 transition-colors px-2 py-1 rounded hover:bg-danger-500/10"><i class="fa-solid fa-trash mr-1"></i>Cancel</button>
                </div>
            </div>`).join('');
    } catch (e) { container.innerHTML = `<p class="text-danger-400 text-sm">Error: ${e.message}</p>`; }
}

async function cancelTask(id) {
    try { await api(`/api/scheduler/tasks/${id}`, { method: 'DELETE' }); refreshScheduler(); } catch (e) { console.error(e); }
}

// ===================== AUDIT LOGS =====================
async function refreshAuditLogs() {
    const container = document.getElementById('audit-content');
    container.innerHTML = '<div class="flex items-center gap-2 text-gray-500 text-sm"><i class="fa-solid fa-spinner animate-spin"></i> Loading...</div>';
    try {
        const res = await api('/api/audit/logs?limit=50'); const data = await res.json();
        const logs = data.logs || [];
        if (!logs.length) {
            container.innerHTML = `<div class="text-center py-16 fade-up">
                <div class="w-14 h-14 rounded-2xl bg-dark-800 border border-dark-700 flex items-center justify-center mx-auto mb-4">
                    <i class="fa-solid fa-scroll text-xl text-gray-600"></i>
                </div>
                <p class="text-gray-500 text-sm">No audit logs yet</p>
            </div>`;
            return;
        }
        let html = `<div class="bg-dark-800 border border-dark-700 rounded-xl overflow-hidden"><table class="w-full text-xs">
            <thead><tr class="border-b border-dark-700 text-gray-500"><th class="px-4 py-3 text-left">Tool</th><th class="px-4 py-3 text-left">Risk</th><th class="px-4 py-3 text-left">Status</th><th class="px-4 py-3 text-left">Timestamp</th></tr></thead><tbody>`;
        logs.forEach(l => {
            const riskClass = l.risk_level === 'HIGH' ? 'risk-high' : l.risk_level === 'MEDIUM' ? 'risk-medium' : 'risk-low';
            const statusClass = l.status === 'executed' ? 'text-accent-400' : l.status === 'denied' ? 'text-danger-400' : 'text-yellow-400';
            html += `<tr class="border-b border-dark-700/50 hover:bg-dark-700/30">
                <td class="px-4 py-2.5 text-white font-mono">${esc(l.tool_name)}</td>
                <td class="px-4 py-2.5 ${riskClass}">${l.risk_level}</td>
                <td class="px-4 py-2.5 ${statusClass}">${l.status}</td>
                <td class="px-4 py-2.5 text-gray-500">${l.timestamp || '-'}</td>
            </tr>`;
        });
        html += '</tbody></table></div>';
        container.innerHTML = html;
    } catch (e) { container.innerHTML = `<p class="text-danger-400 text-sm">Error: ${e.message}</p>`; }
}

// ===================== DATABASE = [NEW] =====================
async function refreshDatabase() {
    const container = document.getElementById('database-content');
    container.innerHTML = 'Loading database...';
    try {
        const res = await api('/api/database/stats');
        const data = await res.json();

        container.innerHTML = `
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
                <div class="bg-dark-800 border border-dark-700 rounded-xl p-4">
                    <h3 class="text-white text-xs mb-1">DB Size</h3>
                    <p class="text-accent-400 text-lg">${data.size_kb} KB</p>
                </div>
                <div class="bg-dark-800 border border-dark-700 rounded-xl p-4">
                    <h3 class="text-white text-xs mb-1">Total Tables</h3>
                    <p class="text-accent-400 text-lg">${(data.tables || []).length}</p>
                </div>
            </div>
            <div class="bg-dark-800 border border-dark-700 rounded-xl p-4">
                <h3 class="text-white text-xs mb-3">Tables Overview</h3>
                <div class="space-y-2">${Object.entries(data.counts || {}).map(([t, c]) => `
                    <div class="flex justify-between items-center bg-dark-900 rounded p-2 text-xs">
                        <span class="text-gray-300 font-mono">${esc(t)}</span>
                        <span class="text-gray-500">${c} rows</span>
                    </div>
                `).join('')}</div>
            </div>
        `;
    } catch (e) { container.innerHTML = 'Error loading database stats'; }
}

// ===================== INIT =====================
document.getElementById('login-password').addEventListener('keydown', e => { if (e.key === 'Enter') handleLogin(); });
document.getElementById('twofa-code').addEventListener('keydown', e => { if (e.key === 'Enter') handleVerify2FA(); });

// ===================== SETTINGS =====================
async function refreshSettings() {
    try {
        const res = await api('/api/settings');
        const data = await res.json();
        const s = data.settings || {};

        document.getElementById('setting-smtp-host').value = s['smtp_host'] || '';
        document.getElementById('setting-smtp-port').value = s['smtp_port'] || '';
        document.getElementById('setting-smtp-user').value = s['smtp_user'] || '';
        document.getElementById('setting-smtp-pass').value = s['smtp_pass'] || '';
        document.getElementById('setting-gmail-credentials').value = s['gmail_credentials_json'] || '';
        document.getElementById('setting-gmail-reset-token').checked = false;
        document.getElementById('setting-wp-url').value = s['wp_url'] || '';
        document.getElementById('setting-wp-path').value = s['wp_path'] || '';
        document.getElementById('setting-groq-key').value = s['groq_key'] || '';
        document.getElementById('setting-webhook-url').value = s['webhook_url'] || '';
        document.getElementById('setting-proactive').checked = s['proactive'] !== false;
    } catch (e) {
        console.error('Failed to load settings:', e);
    }
}

async function saveAllSettings() {
    const settings = {
        'smtp_host': document.getElementById('setting-smtp-host').value.trim(),
        'smtp_port': document.getElementById('setting-smtp-port').value.trim(),
        'smtp_user': document.getElementById('setting-smtp-user').value.trim(),
        'smtp_pass': document.getElementById('setting-smtp-pass').value.trim(),
        'gmail_credentials_json': document.getElementById('setting-gmail-credentials').value.trim(),
        'gmail_reset_token': document.getElementById('setting-gmail-reset-token').checked,
        'wp_url': document.getElementById('setting-wp-url').value.trim(),
        'wp_path': document.getElementById('setting-wp-path').value.trim(),
        'groq_key': document.getElementById('setting-groq-key').value.trim(),
        'webhook_url': document.getElementById('setting-webhook-url').value.trim(),
        'proactive': document.getElementById('setting-proactive').checked
    };

    try {
        const btn = document.querySelector('button[onclick="saveAllSettings()"]');
        const originalText = btn.textContent;
        btn.textContent = 'Saving...';
        btn.disabled = true;

        const res = await api('/api/settings', {
            method: 'POST',
            body: JSON.stringify(settings)
        });

        if (res.ok) {
            btn.textContent = 'Saved!';
            btn.classList.replace('bg-accent-500', 'bg-success-500');
            setTimeout(() => {
                btn.textContent = originalText;
                btn.classList.replace('bg-success-500', 'bg-accent-500');
                btn.disabled = false;
            }, 2000);
        } else {
            alert('Failed to save settings');
            btn.textContent = originalText;
            btn.disabled = false;
        }
    } catch (e) {
        alert('Connection error');
        console.error(e);
    }
}

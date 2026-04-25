#!/usr/bin/env python3
"""Build a fully self-contained static HTML demo.

Reads the seeded demo SQLite DB through the real Flask routes (so the data
shape stays in sync with the live server), embeds the responses as JSON in
the page, and shims `window.fetch` so the dashboard runs entirely client-side.

Output: demo/static/index.html — drop into GitHub Pages, Cloudflare Pages,
Netlify, or any static host. Zero cold start, zero server, zero cost.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = Path(__file__).resolve().parent
OUT_DIR = DEMO_DIR / "static"
OUT_HTML = OUT_DIR / "index.html"
DB_PATH = DEMO_DIR / "demo-sessions.db"


def detect_repo_url():
    """Return https://github.com/owner/repo if a github remote is configured."""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(ROOT), "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:
        return None
    # git@github.com:owner/repo.git  or  https://github.com/owner/repo(.git)
    m = re.match(r"(?:git@github\.com:|https?://github\.com/)([^/]+/[^/]+?)(?:\.git)?$", out)
    if not m:
        return None
    return f"https://github.com/{m.group(1)}"


def main():
    # Seed if needed
    if not DB_PATH.exists():
        print(f"DB not found at {DB_PATH}; seeding…")
        sys.path.insert(0, str(DEMO_DIR))
        from seed_demo import seed
        seed(str(DB_PATH))

    # Point the server at the demo DB
    os.environ["CLAUDE_DASHBOARD_DB_PATH"] = str(DB_PATH)
    os.environ["CLAUDE_DASHBOARD_CONFIG"] = str(DEMO_DIR / "server-config.yaml")
    sys.path.insert(0, str(ROOT / "server"))

    import app as app_module
    app_module.init_db()
    client = app_module.app.test_client()

    clients_json = client.get("/api/clients").get_json()
    sessions_json = client.get("/api/sessions?limit=10000").get_json()

    messages = {}
    for s in sessions_json["sessions"]:
        sid = s["id"]
        detail = client.get(f"/api/sessions/{sid}").get_json()
        messages[sid] = detail["messages"]

    embedded = {
        "clients": clients_json["clients"],
        "sessions": sessions_json["sessions"],
        "messages": messages,
    }

    html = app_module.DASHBOARD_HTML
    repo_url = detect_repo_url()
    banner_html = (
        f'Read-only static demo — '
        f'<a href="{repo_url}" target="_blank" rel="noopener">view on GitHub</a>'
        if repo_url else 'Read-only static demo'
    )
    shim = (STATIC_SHIM_TEMPLATE
            .replace("__DATA__", json.dumps(embedded, ensure_ascii=False))
            .replace("__BANNER_HTML__", json.dumps(banner_html)))

    # Inject before the main inline <script>. The marker is the first line of
    # the dashboard's main script block; if the file changes shape the marker
    # may need updating.
    marker = "<script>\nlet allSessions = [];"
    if marker not in html:
        raise SystemExit(
            "Could not find injection marker in DASHBOARD_HTML. "
            "Update build_static.py with the new marker."
        )
    html = html.replace(marker, shim + "\n" + marker, 1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    size_kb = OUT_HTML.stat().st_size / 1024
    print(f"Wrote {OUT_HTML} ({size_kb:.1f} KB, {len(sessions_json['sessions'])} sessions, "
          f"{sum(len(m) for m in messages.values())} messages)")


# Static-mode shim. Overrides window.fetch BEFORE the main dashboard script
# runs, so loadSessions()/loadClients()/showDetail() resolve from the embedded
# data instead of hitting the network. Admin POSTs return a 403 with a
# friendly message — and the corresponding UI buttons are hidden via CSS.
STATIC_SHIM_TEMPLATE = r"""<style id="static-mode-style">
  /* Hide write-action UI in the static demo */
  .static-mode .client-actions,
  .static-mode .session-row .move-btn { display: none !important; }
  .static-mode .demo-banner {
    background: var(--surface); border-bottom: 1px solid var(--border);
    color: var(--text-muted); font-size: 13px; padding: 6px 24px; text-align: center;
  }
  .static-mode .demo-banner a { color: var(--accent); }
</style>
<script id="static-data">
window.STATIC_DATA = __DATA__;
</script>
<script id="static-shim">
(function() {
  document.documentElement.classList.add('static-mode');
  document.addEventListener('DOMContentLoaded', () => {
    const banner = document.createElement('div');
    banner.className = 'demo-banner';
    banner.innerHTML = __BANNER_HTML__;
    document.body.insertBefore(banner, document.body.firstChild);
  });

  const realFetch = window.fetch.bind(window);
  function mkResp(body, status) {
    status = status || 200;
    return Promise.resolve({
      ok: status < 400,
      status: status,
      json: () => Promise.resolve(body),
    });
  }

  function buildSessionsResponse(params) {
    const q = (params.get('q') || '').toLowerCase();
    const vm = params.get('vm');
    const project = params.get('project');

    let results = STATIC_DATA.sessions.filter(s => {
      if (vm && s.vm_name !== vm) return false;
      if (project && !((s.project || '').includes(project))) return false;
      if (q) {
        const meta = ((s.summary || '') + ' ' + (s.project || '') + ' ' +
                      (s.custom_title || '')).toLowerCase();
        if (meta.includes(q)) return true;
        const msgs = STATIC_DATA.messages[s.id] || [];
        return msgs.some(m => (m.content || '').toLowerCase().includes(q));
      }
      return true;
    });

    results = results.slice().sort((a, b) =>
      (b.last_timestamp || '').localeCompare(a.last_timestamp || ''));

    if (q) {
      results = results.map(s => {
        const msgs = STATIC_DATA.messages[s.id] || [];
        for (const m of msgs) {
          const c = m.content || '';
          const idx = c.toLowerCase().indexOf(q);
          if (idx >= 0) {
            const start = Math.max(0, idx - 40);
            const end = Math.min(c.length, idx + q.length + 80);
            let snippet = c.slice(start, end).replace(/\n/g, ' ');
            if (start > 0) snippet = '…' + snippet;
            if (end < c.length) snippet = snippet + '…';
            return Object.assign({}, s, {match_snippet: snippet});
          }
        }
        return s;
      });
    }

    const vmSet = new Set(STATIC_DATA.sessions.map(s => s.vm_name).filter(Boolean));
    const projSet = new Set(STATIC_DATA.sessions.map(s => s.project).filter(Boolean));
    return {
      sessions: results,
      filters: {
        vms: [...vmSet].sort(),
        projects: [...projSet].sort(),
      },
    };
  }

  window.fetch = function(url, opts) {
    if (typeof url !== 'string') return realFetch(url, opts);
    if (url === '/api/clients') {
      return mkResp({
        clients: STATIC_DATA.clients,
        total_sessions: STATIC_DATA.sessions.length,
      });
    }
    if (url === '/api/sessions' || url.startsWith('/api/sessions?')) {
      const qs = url.includes('?') ? url.split('?')[1] : '';
      return mkResp(buildSessionsResponse(new URLSearchParams(qs)));
    }
    const m = url.match(/^\/api\/sessions\/([^?]+)$/);
    if (m) {
      const id = decodeURIComponent(m[1]);
      const session = STATIC_DATA.sessions.find(s => s.id === id);
      if (!session) return mkResp({error: 'not found'}, 404);
      return mkResp({session: session, messages: STATIC_DATA.messages[id] || []});
    }
    if (url.startsWith('/api/admin/')) {
      return mkResp({error: 'This is a static demo — admin actions are disabled.'}, 403);
    }
    return realFetch(url, opts);
  };
})();
</script>"""


if __name__ == "__main__":
    main()

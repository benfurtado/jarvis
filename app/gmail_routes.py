"""
Jarvis Gmail OAuth2 Routes — handles authorization flow for Gmail API.
Works with Desktop App (installed) credentials on a headless server.
Uses manual auth-code flow: user visits Google, copies code, pastes it back.
"""
import os
import json
import logging

from flask import Blueprint, redirect, request, url_for, jsonify

logger = logging.getLogger("Jarvis")

gmail_bp = Blueprint("gmail", __name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gmail_data")


@gmail_bp.route("/api/gmail/authorize")
def gmail_authorize():
    """
    Show a page with a Google OAuth link.
    User clicks it, signs in, gets redirected to localhost with a code,
    then pastes the code back into the form on this page.
    """
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        return jsonify({"error": "google-auth-oauthlib not installed"}), 500

    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    creds_path = os.path.join(_DATA_DIR, "credentials.json")
    if not os.path.exists(creds_path):
        return jsonify({"error": f"credentials.json not found in {_DATA_DIR}/"}), 404

    # Build OAuth URL using the installed app flow with OOB-like redirect
    flow = InstalledAppFlow.from_client_secrets_file(creds_path, scopes=SCOPES)
    flow.redirect_uri = "http://localhost"

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    # Store state
    state_path = os.path.join(_DATA_DIR, "oauth_state.json")
    with open(state_path, "w") as f:
        json.dump({"state": state}, f)

    server_url = request.host_url.rstrip("/")

    return f"""
    <html>
    <head>
        <title>Jarvis — Gmail Authorization</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
                background: #0a0a0f; color: #e5e7eb;
                display: flex; align-items: center; justify-content: center;
                min-height: 100vh; padding: 2rem;
            }}
            .card {{
                background: #111827; border: 1px solid #1f2937;
                border-radius: 1rem; padding: 2.5rem; max-width: 520px; width: 100%;
            }}
            h1 {{ color: #22d3ee; font-size: 1.5rem; margin-bottom: 0.5rem; }}
            h2 {{ color: #9ca3af; font-size: 0.95rem; font-weight: 400; margin-bottom: 2rem; }}
            .step {{
                background: #0d1117; border: 1px solid #1f2937; border-radius: 0.5rem;
                padding: 1rem; margin-bottom: 1rem;
            }}
            .step-num {{
                display: inline-block; background: #22d3ee20; color: #22d3ee;
                width: 24px; height: 24px; border-radius: 50%; text-align: center;
                line-height: 24px; font-size: 0.75rem; font-weight: 600; margin-right: 0.5rem;
            }}
            .step-title {{ color: #f3f4f6; font-weight: 500; }}
            .step p {{ color: #9ca3af; font-size: 0.85rem; margin-top: 0.5rem; padding-left: 2rem; }}
            a.btn {{
                display: inline-block; margin-top: 0.5rem; padding: 0.6rem 1.2rem;
                background: #22d3ee; color: #0a0a0f; border-radius: 0.5rem;
                text-decoration: none; font-weight: 600; font-size: 0.85rem;
            }}
            a.btn:hover {{ background: #06b6d4; }}
            input[type="text"] {{
                width: 100%; padding: 0.6rem 0.8rem; margin-top: 0.5rem;
                background: #0a0a0f; border: 1px solid #374151; border-radius: 0.4rem;
                color: #f3f4f6; font-size: 0.85rem; font-family: monospace;
            }}
            button.submit {{
                margin-top: 0.75rem; padding: 0.6rem 1.5rem;
                background: #10b981; color: white; border: none; border-radius: 0.5rem;
                font-weight: 600; cursor: pointer; font-size: 0.85rem;
            }}
            button.submit:hover {{ background: #059669; }}
            .note {{
                color: #6b7280; font-size: 0.75rem; margin-top: 1.5rem;
                border-top: 1px solid #1f2937; padding-top: 1rem;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🔐 Gmail Authorization</h1>
            <h2>Connect your Gmail account to Jarvis</h2>

            <div class="step">
                <span class="step-num">1</span>
                <span class="step-title">Sign in with Google</span>
                <p>Click the button below. Sign in and click <b>Allow</b>.</p>
                <p><a href="{authorization_url}" target="_blank" class="btn">Sign in with Google →</a></p>
            </div>

            <div class="step">
                <span class="step-num">2</span>
                <span class="step-title">Copy the URL</span>
                <p>After allowing access, you'll see a page that can't load (that's normal!).<br>
                Copy the <b>entire URL</b> from your browser's address bar.<br>
                It will look like: <code>http://localhost/?code=4/0A...&scope=...</code></p>
            </div>

            <div class="step">
                <span class="step-num">3</span>
                <span class="step-title">Paste it here</span>
                <form action="{server_url}/api/gmail/callback" method="GET"
                      onsubmit="return extractCode(this)">
                    <input type="text" name="redirect_url" id="redirect_url"
                           placeholder="Paste the full URL here..." />
                    <input type="hidden" name="code" id="code_field" />
                    <br>
                    <button type="submit" class="submit">✅ Connect Gmail</button>
                </form>
            </div>

            <p class="note">
                Your credentials are stored locally on this server only.
                Jarvis uses OAuth2 — your password is never shared.
            </p>
        </div>
        <script>
            function extractCode(form) {{
                const url = document.getElementById('redirect_url').value.trim();
                let code = '';
                try {{
                    const parsed = new URL(url);
                    code = parsed.searchParams.get('code') || '';
                }} catch(e) {{
                    // Maybe they pasted just the code
                    code = url;
                }}
                if (!code) {{
                    alert('Could not extract authorization code. Make sure you pasted the full URL.');
                    return false;
                }}
                document.getElementById('code_field').value = code;
                // Redirect with just the code
                window.location.href = '{server_url}/api/gmail/callback?code=' + encodeURIComponent(code);
                return false;
            }}
        </script>
    </body>
    </html>
    """


@gmail_bp.route("/api/gmail/callback")
def gmail_callback():
    """Handle the OAuth2 callback — exchange code for token."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        return jsonify({"error": "google-auth-oauthlib not installed"}), 500

    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    code = request.args.get("code")
    if not code:
        return jsonify({"error": "No authorization code provided. Go to /api/gmail/authorize"}), 400

    creds_path = os.path.join(_DATA_DIR, "credentials.json")
    token_path = os.path.join(_DATA_DIR, "token.json")

    if not os.path.exists(creds_path):
        return jsonify({"error": "credentials.json not found"}), 404

    try:
        flow = InstalledAppFlow.from_client_secrets_file(creds_path, scopes=SCOPES)
        flow.redirect_uri = "http://localhost"

        # Exchange the authorization code for credentials
        flow.fetch_token(code=code)
        creds = flow.credentials

        # Save the token
        with open(token_path, "w") as f:
            f.write(creds.to_json())

        # Clean up state file
        state_path = os.path.join(_DATA_DIR, "oauth_state.json")
        try:
            os.remove(state_path)
        except OSError:
            pass

        logger.info("Gmail OAuth2: authorization complete, token saved!")

        return """
        <html>
        <head><title>Jarvis — Gmail Connected</title></head>
        <body style="font-family: system-ui; background: #0a0a0f; color: #fff; display: flex;
                     align-items: center; justify-content: center; height: 100vh; margin: 0;">
            <div style="text-align: center; max-width: 400px;">
                <h1 style="color: #22d3ee; font-size: 2.5rem;">✅ Gmail Connected!</h1>
                <p style="color: #9ca3af; margin-top: 1rem; font-size: 1.1rem;">
                    Jarvis can now send and read emails on your behalf.
                </p>
                <p style="color: #6b7280; font-size: 0.85rem; margin-top: 2rem;">
                    Try it: <code style="color: #22d3ee;">"Email someone@example.com that the project is done"</code>
                </p>
                <a href="/" style="display: inline-block; margin-top: 1.5rem; padding: 0.6rem 1.5rem;
                    background: #22d3ee20; border: 1px solid #22d3ee40; border-radius: 0.5rem;
                    color: #22d3ee; text-decoration: none; font-weight: 600;">
                    ← Back to Jarvis
                </a>
            </div>
        </body>
        </html>
        """

    except Exception as e:
        logger.error(f"Gmail OAuth2 callback error: {e}")
        return jsonify({
            "error": f"Failed to exchange authorization code: {str(e)}",
            "hint": "Make sure you pasted the complete URL from the redirect."
        }), 400


@gmail_bp.route("/api/gmail/status")
def gmail_status():
    """Check Gmail OAuth2 configuration status."""
    from app.email_tools import check_gmail_configured
    ok, error = check_gmail_configured()
    if ok:
        return jsonify({"status": "connected", "message": "Gmail API is ready"})
    return jsonify({"status": "not_configured", "message": error})

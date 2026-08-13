"""
Slack OAuth v2 client — the "Add to Slack" install flow.

Registering an app: https://api.slack.com/apps -> create app -> OAuth & Permissions
- Add the bot scopes in BOT_SCOPES below
- Set the redirect URL to match SLACK_OAUTH_REDIRECT_URI in .env

Bot tokens (xoxb-...) from this flow don't expire on their own (token
rotation is a separate, opt-in app setting we're not using), so unlike Jira
there's no refresh step here — just store it.

Important scope limit: this only covers *storing* a bot token per org. The
running slack_bot.py process still authenticates as a single hardcoded
SLACK_BOT_TOKEN via Socket Mode, which is inherently one workspace per
process — it does NOT yet read from slack_integrations to serve multiple
workspaces from one process. Making the bot itself multi-tenant needs an
installation store (bolt's OAuthSettings) and likely a switch from Socket
Mode to the HTTP Events API, since Socket Mode's app-level token model
doesn't map cleanly onto "one bot token per installed workspace."
"""

import os
from urllib.parse import urlencode

import requests

AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
TOKEN_URL = "https://slack.com/api/oauth.v2.access"
BOT_SCOPES = "channels:history,channels:read,chat:write,commands"


def build_authorize_url(state: str) -> str:
    params = {
        "client_id": os.environ["SLACK_OAUTH_CLIENT_ID"],
        "scope": BOT_SCOPES,
        "redirect_uri": os.environ["SLACK_OAUTH_REDIRECT_URI"],
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_tokens(code: str) -> dict:
    """Returns Slack's oauth.v2.access response: {access_token, team: {id, name}, bot_user_id, ...}.
    Slack's token endpoint expects form-encoded params, not JSON, and always
    replies 200 even on failure — the real signal is the "ok" field.
    """
    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": os.environ["SLACK_OAUTH_CLIENT_ID"],
            "client_secret": os.environ["SLACK_OAUTH_CLIENT_SECRET"],
            "code": code,
            "redirect_uri": os.environ["SLACK_OAUTH_REDIRECT_URI"],
        },
    )
    body = response.json()
    if response.status_code != 200 or not body.get("ok"):
        raise ValueError(f"Slack OAuth token exchange failed: {body.get('error', response.text)}")
    return body

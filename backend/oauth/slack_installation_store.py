"""
Backs Bolt's per-event bot-token resolution with our own slack_integrations
table, so a single Socket Mode connection (one process, one app-level token)
can serve every workspace that's installed the app — not just one hardcoded
SLACK_BOT_TOKEN.

Socket Mode does support this: the WebSocket is opened once with the app-level
token (an app-level token belongs to the Slack App itself, not to any one
workspace installation), and events from every installed workspace multiplex
over that single connection, each carrying a team_id. Bolt resolves the right
bot token per event via InstallationStore.find_bot(team_id=...) before
dispatching to a handler — this file is that lookup, backed by Postgres.

Our own OAuth flow (backend/oauth/slack.py + the /integrations/slack/callback
route in main.py) is the real write path when a workspace installs the app.
save() exists to satisfy the InstallationStore interface and handle it
correctly if Bolt ever calls it directly (e.g. a future token-rotation flow),
but isn't how installations normally get created here.
"""

from slack_sdk.oauth.installation_store import InstallationStore
from slack_sdk.oauth.installation_store.models.bot import Bot
from slack_sdk.oauth.installation_store.models.installation import Installation

from ..db import crud
from ..db.crypto import decrypt
from ..db.session import get_session


class PostgresInstallationStore(InstallationStore):
    def save(self, installation: Installation) -> None:
        with get_session() as db:
            integration = crud.get_slack_integration_by_team_id(db, installation.team_id)
            if integration is None:
                # No org has connected this workspace through our own OAuth flow —
                # nothing to attach a bare Bolt-initiated save() to.
                return
            crud.update_slack_bot_token(db, integration.id, installation.bot_token)

    def find_bot(self, *, enterprise_id, team_id, is_enterprise_install=False, **kwargs):
        with get_session() as db:
            integration = crud.get_slack_integration_by_team_id(db, team_id)
            if integration is None:
                return None
            return Bot(
                enterprise_id=enterprise_id,
                team_id=team_id,
                bot_token=decrypt(integration.encrypted_bot_token),
                # Slack's real bot_id (B0XXX) isn't captured in our schema, only
                # bot_user_id (U0XXX) — fine here since nothing in this app uses
                # Bolt's bot_id-keyed features (app uninstall handling, etc.).
                bot_id=integration.bot_user_id or "",
                bot_user_id=integration.bot_user_id or "",
                installed_at=integration.installed_at.timestamp(),
            )

    def find_installation(self, *, enterprise_id, team_id, user_id=None, is_enterprise_install=False, **kwargs):
        bot = self.find_bot(enterprise_id=enterprise_id, team_id=team_id, is_enterprise_install=is_enterprise_install)
        if bot is None:
            return None
        return Installation(
            enterprise_id=bot.enterprise_id,
            team_id=bot.team_id,
            bot_token=bot.bot_token,
            bot_id=bot.bot_id,
            bot_user_id=bot.bot_user_id,
            user_id=user_id or "",
            installed_at=bot.installed_at,
        )

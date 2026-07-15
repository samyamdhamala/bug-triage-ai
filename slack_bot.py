import os
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from backend.triage import triage_bug
from backend.jira_client import create_jira_ticket, find_similar_in_jira
from backend.vector_store import find_similar, store_embedding
from backend.feedback_store import save_feedback

load_dotenv()

app = App(token=os.environ["SLACK_BOT_TOKEN"])


def format_slack_message(result: dict) -> str:
    severity = result.get("severity", "?")
    confidence = result.get("confidence", "?")
    title = result.get("title", "Untitled")
    component = result.get("component", "Unknown")
    team = result.get("suggested_assignee_team", "Unassigned")
    reasoning = result.get("priority_reasoning", "")
    labels = result.get("suggested_labels", [])
    repro = result.get("reproduction_steps", [])
    needs_review = "needs-human-review" in labels

    severity_emoji = {"P1": ":red_circle:", "P2": ":orange_circle:", "P3": ":yellow_circle:", "P4": ":white_circle:"}.get(severity, ":white_circle:")
    confidence_emoji = {"High": ":large_green_circle:", "Medium": ":large_yellow_circle:", "Low": ":large_red_circle:"}.get(confidence, "")
    review_banner = "\n:warning: *Flagged for human review* — low confidence or high severity." if needs_review else ""

    repro_text = ""
    if repro:
        repro_text = "\n*Reproduction Steps:*\n" + "\n".join(f"{i+1}. {step}" for i, step in enumerate(repro))

    labels_text = f"\n*Labels:* {' '.join(f'`{l}`' for l in labels)}" if labels else ""

    return f"""{review_banner}
{severity_emoji} *[{severity}] {title}*

*Component:* {component}
*Assigned To:* {team}
*Confidence:* {confidence_emoji} {confidence}
*Reasoning:* {reasoning}{repro_text}{labels_text}
""".strip()


BOT_USER_ID = None  # populated on startup to avoid self-triaging bot messages


def _build_jira_suffix(result: dict) -> str:
    """Run the two-layer dedup pipeline and return a Slack message suffix."""
    confidence = result.get("confidence", "Medium")

    if confidence == "Low":
        return "\n\n:pause_button: *No Jira ticket created* — confidence too low. Please review and create manually if valid."

    # Layer 1: local vector store (semantic, fast)
    similar = find_similar(result)
    if similar:
        return (
            f"\n\n:brain: *Semantic duplicate detected* ({similar['similarity']}% match): "
            f"<{similar['jira_url']}|{similar['jira_key']}> — _{similar['title']}_\nNo new ticket created."
        )

    # Layer 2: Jira semantic search (catches manually-created tickets not yet in vector store)
    jira_dup = find_similar_in_jira(result)
    if jira_dup:
        return (
            f"\n\n:brain: *Semantic duplicate found in Jira* ({jira_dup['similarity']}% match): "
            f"<{jira_dup['url']}|{jira_dup['key']}> — _{jira_dup['title']}_\nNo new ticket created."
        )

    # Layer 3: no duplicate — create ticket and store embedding
    jira = create_jira_ticket(result)
    store_embedding(result, jira["key"], jira["url"])
    return f"\n\n:jira: *Jira ticket created:* <{jira['url']}|{jira['key']}>"


@app.event("message")
def handle_message(event, say, client):
    # Ignore bot messages, edits, deletions, and thread replies
    if event.get("bot_id"):
        return
    if event.get("subtype"):
        return
    if event.get("thread_ts"):
        return

    # Only listen to the #bugs channel
    bugs_channel = os.environ.get("SLACK_BUGS_CHANNEL", "bugs")
    try:
        channel_info = client.conversations_info(channel=event["channel"])
        channel_name = channel_info["channel"]["name"]
    except Exception:
        return
    if channel_name != bugs_channel.lstrip("#"):
        return

    text = event.get("text", "").strip()
    if not text or len(text) < 20:
        return

    say(":hourglass_flowing_sand: Auto-triaging this bug report...", thread_ts=event["ts"])

    try:
        result = triage_bug(text, save_output=True)
        message = format_slack_message(result)
        try:
            message += _build_jira_suffix(result)
        except Exception as jira_err:
            message += f"\n\n:warning: Jira ticket creation failed: {str(jira_err)}"
        say(message, thread_ts=event["ts"])
    except Exception as e:
        say(f":x: Triage failed: {str(e)}", thread_ts=event["ts"])


@app.command("/triage")
def handle_triage(ack, respond, command):
    ack()

    bug_text = command.get("text", "").strip()
    if not bug_text:
        respond("Please provide a bug description. Usage: `/triage <bug description>`")
        return

    respond(":hourglass_flowing_sand: Triaging your bug report...")

    try:
        result = triage_bug(bug_text, save_output=True)
        message = format_slack_message(result)
        try:
            message += _build_jira_suffix(result)
        except Exception as jira_err:
            message += f"\n\n:warning: Jira ticket creation failed: {str(jira_err)}"
        respond(message)
    except Exception as e:
        respond(f":x: Triage failed: {str(e)}")


@app.command("/feedback")
def handle_feedback(ack, respond, command):
    """Record a QA correction for a previously triaged bug.

    Usage: /feedback BT-123 Severity should be P1, affected all users
    The correction is stored and injected into future triage prompts.
    """
    ack()

    text = command.get("text", "").strip()
    if not text:
        respond(
            "Usage: `/feedback <JIRA-KEY> <correction>`\n"
            "Example: `/feedback BT-42 Severity should be P1, this was affecting all paying users`"
        )
        return

    parts = text.split(None, 1)
    if len(parts) < 2:
        respond(":x: Please include both a Jira key and a correction comment.\nExample: `/feedback BT-42 Team should be QA not Backend`")
        return

    jira_key, comment = parts[0], parts[1]
    corrected_by = command.get("user_id", "unknown")

    save_feedback(jira_key=jira_key, comment=comment, corrected_by=corrected_by)
    respond(
        f":white_check_mark: Correction saved for *{jira_key.upper()}*.\n"
        f"> {comment}\n"
        "This will be applied to future triage prompts automatically."
    )


if __name__ == "__main__":
    app_token = os.environ.get("SLACK_APP_TOKEN")
    if not app_token:
        raise ValueError("SLACK_APP_TOKEN not set in .env")
    print("Bug Triage Bot is running...")
    SocketModeHandler(app, app_token).start()

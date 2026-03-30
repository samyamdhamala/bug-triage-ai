import os
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from backend.triage import triage_bug
from backend.jira_client import create_jira_ticket, find_duplicate

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

        confidence = result.get("confidence", "Medium")

        try:
            if confidence == "Low":
                message += "\n\n:pause_button: *No Jira ticket created* — confidence too low. Please review and create manually if valid."
            else:
                duplicate = find_duplicate(result)
                if duplicate:
                    message += f"\n\n:eyes: *Possible duplicate:* <{duplicate['url']}|{duplicate['key']}> — _{duplicate['title']}_\nNo new ticket created."
                else:
                    jira = create_jira_ticket(result)
                    message += f"\n\n:jira: *Jira ticket created:* <{jira['url']}|{jira['key']}>"
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

        confidence = result.get("confidence", "Medium")

        try:
            if confidence == "Low":
                message += "\n\n:pause_button: *No Jira ticket created* — confidence too low. Please review and create manually if valid."
            else:
                duplicate = find_duplicate(result)
                if duplicate:
                    message += f"\n\n:eyes: *Possible duplicate detected:* <{duplicate['url']}|{duplicate['key']}> — _{duplicate['title']}_\nNo new ticket created."
                else:
                    jira = create_jira_ticket(result)
                    message += f"\n\n:jira: *Jira ticket created:* <{jira['url']}|{jira['key']}>"
        except Exception as jira_err:
            message += f"\n\n:warning: Jira ticket creation failed: {str(jira_err)}"

        respond(message)
    except Exception as e:
        respond(f":x: Triage failed: {str(e)}")


if __name__ == "__main__":
    app_token = os.environ.get("SLACK_APP_TOKEN")
    if not app_token:
        raise ValueError("SLACK_APP_TOKEN not set in .env")
    print("Bug Triage Bot is running...")
    SocketModeHandler(app, app_token).start()

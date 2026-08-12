"""
One-time helper: creates (or updates) a default org in Postgres and migrates the
current .env Jira credentials into it, encrypted.

This exists only for the single-org transition period before real signup/OAuth
flows land — every request resolves to this one org via DEFAULT_ORG_SLUG until
then.

Usage:
    python -m scripts.seed_default_org
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from backend.db import crud
from backend.db.session import get_engine, get_session

load_dotenv()


def main() -> None:
    slug = os.environ.get("DEFAULT_ORG_SLUG", "default")
    base_url = os.environ["JIRA_BASE_URL"]
    email = os.environ["JIRA_EMAIL"]
    api_token = os.environ["JIRA_API_TOKEN"]
    project_key = os.environ["JIRA_PROJECT_KEY"]

    with get_session() as db:
        org = crud.get_or_create_org(db, slug=slug, name=slug.replace("-", " ").title())
        crud.upsert_jira_integration(
            db,
            org_id=org.id,
            base_url=base_url,
            email=email,
            api_token=api_token,
            project_key=project_key,
        )
        print(f"Seeded org '{org.slug}' ({org.id}) with Jira credentials for {base_url}")


if __name__ == "__main__":
    main()

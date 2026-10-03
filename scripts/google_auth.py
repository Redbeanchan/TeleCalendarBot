#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from app.calendar_service import SCOPES


def main() -> None:
    parser = argparse.ArgumentParser(description="Authorize this private assistant for Google Calendar")
    parser.add_argument("--credentials", default=os.getenv("GOOGLE_CREDENTIALS_PATH", "/secrets/google_credentials.json"))
    parser.add_argument("--token", default=os.getenv("GOOGLE_TOKEN_PATH", "/secrets/google_token.json"))
    args = parser.parse_args()
    credentials_path, token_path = Path(args.credentials), Path(args.token)
    if not credentials_path.is_file():
        raise SystemExit(f"OAuth desktop client file not found: {credentials_path}")
    token_path.parent.mkdir(parents=True, exist_ok=True)
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    credentials = flow.run_local_server(host="0.0.0.0", port=8080, open_browser=False, authorization_prompt_message="Open this URL in your browser:\n{url}")
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    token_path.chmod(0o600)
    print(f"Authorization saved to {token_path}")


if __name__ == "__main__":
    main()

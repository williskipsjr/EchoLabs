"""Deploy the web demo in space/ to a Hugging Face Space.

Usage (after `uv run hf auth login`):
    uv run python scripts/deploy_space.py                  # -> <your-hf-user>/EchoLabs
    uv run python scripts/deploy_space.py --repo me/MySpace

The Space installs the echolabs package from GitHub main (space/requirements.txt),
so merge library changes before deploying.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from huggingface_hub import HfApi

SPACE_DIR = Path(__file__).resolve().parent.parent / "space"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", help="Space id, e.g. user/EchoLabs (default: <logged-in user>/EchoLabs)")
    args = p.parse_args()

    api = HfApi()
    repo = args.repo or f"{api.whoami()['name']}/EchoLabs"
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()

    api.create_repo(repo, repo_type="space", space_sdk="gradio", exist_ok=True)
    commit = api.upload_folder(
        folder_path=SPACE_DIR,
        repo_id=repo,
        repo_type="space",
        commit_message=f"Deploy EchoLabs demo from github.com/williskipsjr/EchoLabs@{sha}",
    )
    print(f"Deployed: https://huggingface.co/spaces/{repo}\n{commit.commit_url}")


if __name__ == "__main__":
    main()

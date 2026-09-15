"""Build the static GitHub Pages documentation from the app's canonical page."""

from __future__ import annotations

import argparse
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY_ROOT / "src/changeproof/templates/documentation_architecture.html"
LIVE_DEMO = "https://changeproof-production.up.railway.app"

LINK_REPLACEMENTS = {
    'href="/documentation/architecture"': 'href="./"',
    'href="/triage"': f'href="{LIVE_DEMO}/triage"',
    'href="/impact"': f'href="{LIVE_DEMO}/impact"',
    'href="/datahub"': f'href="{LIVE_DEMO}/datahub"',
}


def build(output_directory: Path) -> Path:
    """Render a Pages-safe copy while keeping the app template authoritative."""

    html = SOURCE.read_text(encoding="utf-8")
    for local_link, public_link in LINK_REPLACEMENTS.items():
        html = html.replace(local_link, public_link)

    if 'href="/' in html:
        raise ValueError("The static documentation contains an unresolved app route")

    output_directory.mkdir(parents=True, exist_ok=True)
    output_file = output_directory / "index.html"
    output_file.write_text(html, encoding="utf-8")
    (output_directory / ".nojekyll").write_text("", encoding="utf-8")
    return output_file


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=REPOSITORY_ROOT / "_site")
    arguments = parser.parse_args()
    print(build(arguments.output))


if __name__ == "__main__":
    main()

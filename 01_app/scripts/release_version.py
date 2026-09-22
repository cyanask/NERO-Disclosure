"""One released version number, shared by the manifest, the page and the builders.

The iteration records are the source of truth. Packaging and the published
manifest read it here instead of keeping a second literal that drifts behind the
delivered version.
"""
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
NOTES = APP / 'config/release-notes.json'


def current(notes=NOTES):
    """Return the version recorded as current in the iteration records."""
    try:
        value = json.loads(Path(notes).read_text('utf-8')).get('current', '')
    except (OSError, ValueError, AttributeError):
        value = ''
    version = str(value).strip()
    if not version:
        raise SystemExit('缺少 config/release-notes.json 的 current 版本号，拒绝继续；版本号只有一个来源。')
    return version

import time
from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader, PrefixLoader

from abicus.version import get_version

# Cache-buster: changes on every server restart so edited CSS/JS reloads
# without a hard refresh. Stable within a single process so static URLs
# stay cacheable while the server is up.
ASSET_V = str(int(time.time()))

ROOT = Path(__file__).parent

_loader = ChoiceLoader(
    [
        FileSystemLoader(str(ROOT / "shell" / "templates")),
        PrefixLoader(
            {
                "outflows": FileSystemLoader(str(ROOT / "apps" / "outflows" / "templates")),
                "assets":   FileSystemLoader(str(ROOT / "apps" / "assets" / "templates")),
                "claims":   FileSystemLoader(str(ROOT / "apps" / "claims" / "templates")),
                "loan":     FileSystemLoader(str(ROOT / "apps" / "loan" / "templates")),
            }
        ),
    ]
)

templates = Jinja2Templates(directory=str(ROOT / "shell" / "templates"))
templates.env.loader = _loader
templates.env.globals["version"] = get_version()
templates.env.globals["asset_v"] = ASSET_V

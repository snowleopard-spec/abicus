from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader, PrefixLoader

from abicus.version import get_version

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

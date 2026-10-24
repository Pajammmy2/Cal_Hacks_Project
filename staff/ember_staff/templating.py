from fastapi.templating import Jinja2Templates

from . import config

templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))

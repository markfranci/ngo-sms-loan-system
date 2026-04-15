# This file makes the 'routes' folder a Python package.
# We import all blueprints here so the rest of the app
# can register them easily from one place.

from app.routes.auth import auth
from app.routes.main import main

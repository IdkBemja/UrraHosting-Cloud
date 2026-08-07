from flask_bcrypt import Bcrypt
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

db = SQLAlchemy()
csrf = CSRFProtect()
bcrypt = Bcrypt()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.session_protection = "strong"

# Backed by Redis (not memory://): unlike WebPanel's single dashboard
# process, this instance runs `app` and `webdav` as two separate
# containers that must share the same rate-limit state, so an in-memory
# store would silently under-count attempts made against the other
# service.
limiter = Limiter(key_func=get_remote_address)

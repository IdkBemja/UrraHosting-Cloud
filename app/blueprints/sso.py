"""SSO from UrraHosting-Dashboard (Fase 4, plan.md section 9/11): lets
the Dashboard offer an "Abrir UrraHosting Cloud" button that logs a user
into this instance without them re-entering credentials, by minting a
short-lived JWT signed with this instance's own `ORCHESTRATOR_TOKEN` -
the same shared secret the Dashboard already generated for this
instance at deploy time (see scripts/seed_platform_stack_templates.py::
seed_cloudstorage, `ORCHESTRATOR_TOKEN` value_source=generated_secret),
so no new secret-distribution channel is needed between the two
services.

This is a real, working implementation of the JWT verification side
(this app). The Dashboard side (an endpoint there that mints the JWT
using its own record of this instance's ORCHESTRATOR_TOKEN and redirects
the browser here) is NOT implemented as part of this repo - it lives in
UrraHosting-Dashboard and is out of scope for this codebase, same as any
other consumer of this endpoint would be.
"""

from __future__ import annotations

import jwt as pyjwt
from flask import Blueprint, current_app, flash, redirect, request, url_for
from flask_login import login_user

from ..extensions import limiter
from ..models.user import User
from ..services import activity

bp = Blueprint("sso", __name__, url_prefix="/sso")

_ALGORITHM = "HS256"


@bp.route("/consume")
@limiter.limit("20 per minute")
def consume():
    # The JWT travels as a query param, which - same concern as the
    # public-share password fixed in blueprints/public/__init__.py - can
    # leak into browser history/access logs/Referer headers. Accepted
    # here (matching common "magic link" SSO patterns) ONLY because the
    # Dashboard side is expected to mint these with a short expiry
    # (recommend <=60s) and treat each one as effectively single-use;
    # this endpoint itself can't enforce single-use without shared state
    # with the Dashboard, so that's a contract the Dashboard side must
    # honor, not something this code can verify.
    token = request.args.get("token", "")
    secret = current_app.config["INSTANCE"].orchestrator_token

    try:
        claims = pyjwt.decode(token, secret, algorithms=[_ALGORITHM])
    except pyjwt.PyJWTError:
        flash("El enlace de acceso es invalido o expiro", "error")
        return redirect(url_for("auth.login"))

    email = claims.get("sub", "")
    user = User.query.filter(User.email.ilike(email)).first()
    if user is None or not user.active:
        flash("No existe una cuenta activa para ese usuario en esta instancia", "error")
        return redirect(url_for("auth.login"))

    # Same session Flask-Login would create for a password login - still
    # subject to the 2FA-enforcement policy on the next request if the
    # instance requires it and this account hasn't set it up yet (see
    # main.py::enforce_2fa_policy). SSO doesn't get a free pass around it.
    login_user(user, remember=True)
    activity.record("login_sso", user_id=user.id)
    return redirect(url_for("drive.my_drive"))

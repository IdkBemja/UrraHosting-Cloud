"""Sharing (plan.md section 5.2): link publico (con/sin contrasena, con/sin
expiracion) y compartir con un usuario especifico. Una compartición en un
nodo carpeta se hereda a todos sus descendientes (igual que Drive/Nextcloud)
- `find_governing_share` camina hacia arriba por `parent_id` hasta encontrar
la primera Share aplicable, en vez de requerir una fila de Share por cada
archivo dentro de una carpeta compartida.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from ..extensions import bcrypt, db
from ..models.node import Node
from ..models.share import Share


def generate_token() -> str:
    return secrets.token_urlsafe(24)


def create_link_share(
    node: Node,
    created_by_id: uuid.UUID,
    *,
    permission: str = "viewer",
    password: str | None = None,
    expires_at: datetime | None = None,
) -> Share:
    share = Share(
        node_id=node.id,
        created_by=created_by_id,
        target_type="public_link",
        token=generate_token(),
        permission=permission,
        password_hash=bcrypt.generate_password_hash(password).decode("utf-8") if password else None,
        expires_at=expires_at,
    )
    db.session.add(share)
    return share


def create_user_share(node: Node, created_by_id: uuid.UUID, target_user_id: uuid.UUID, *, permission: str = "viewer") -> Share:
    existing = Share.query.filter_by(node_id=node.id, target_type="user", target_user_id=target_user_id).first()
    if existing:
        existing.permission = permission
        return existing
    share = Share(
        node_id=node.id,
        created_by=created_by_id,
        target_type="user",
        target_user_id=target_user_id,
        permission=permission,
    )
    db.session.add(share)
    return share


def revoke_share(share: Share) -> None:
    db.session.delete(share)


def get_link_share_by_token(token: str) -> Share | None:
    share = Share.query.filter_by(token=token, target_type="public_link").first()
    if share is None or share.is_expired:
        return None
    return share


def check_link_password(share: Share, password: str) -> bool:
    if share.password_hash is None:
        return True
    if not password:
        return False
    return bcrypt.check_password_hash(share.password_hash, password)


def _ancestor_chain(node: Node) -> list[Node]:
    """[node, parent, grandparent, ..., root] - stops at the drive root
    (parent_id is None)."""
    chain = [node]
    current = node
    while current.parent_id is not None:
        current = Node.query.get(current.parent_id)
        if current is None:
            break
        chain.append(current)
    return chain


def find_governing_share(node: Node, *, token: str | None = None, user_id: uuid.UUID | None = None) -> tuple[Share, Node] | None:
    """Walks from `node` up to the drive root looking for the first Share
    that matches either `token` (public link) or `user_id` (direct user
    share). Returns (share, share_root_node) so callers can compute the
    relative path of `node` inside the shared subtree, or None if nothing
    in the chain is shared.
    """
    for ancestor in _ancestor_chain(node):
        if token:
            share = Share.query.filter_by(node_id=ancestor.id, token=token, target_type="public_link").first()
            if share and not share.is_expired:
                return share, ancestor
        if user_id:
            share = Share.query.filter_by(node_id=ancestor.id, target_type="user", target_user_id=user_id).first()
            if share:
                return share, ancestor
    return None


def list_shared_with_me(user_id: uuid.UUID) -> list[Share]:
    return Share.query.filter_by(target_type="user", target_user_id=user_id).order_by(Share.created_at.desc()).all()


def list_shared_by_me(user_id: uuid.UUID) -> list[Share]:
    return Share.query.filter_by(created_by=user_id).order_by(Share.created_at.desc()).all()

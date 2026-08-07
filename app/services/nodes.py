from __future__ import annotations

from datetime import datetime, timezone

from ..extensions import db
from ..models.node import Node
from ..models.user import User
from .storage.base import StorageBackend


def create_user_root(user: User) -> Node:
    """Every user gets exactly one `parent_id IS NULL` folder node at
    creation time - this is their drive root (see Node's docstring for
    why the uniqueness index is deliberately a no-op for these rows).
    """
    root = Node(owner_id=user.id, parent_id=None, type="folder", name="")
    db.session.add(root)
    return root


def get_user_root(user: User) -> Node:
    root = Node.query.filter_by(owner_id=user.id, parent_id=None).first()
    if root is None:
        root = create_user_root(user)
        db.session.commit()
    return root


def resolve_path(user: User, parts: list[str]) -> Node | None:
    """Walk `parts` (already split, no empty segments) from the user's
    drive root, matching one active (non-trashed) child name per level.
    Used by both the WebDAV provider (translating DAV path segments) and
    anything else that needs "give me the node at this virtual path".
    Returns the root itself for an empty `parts` list.
    """
    current = get_user_root(user)
    for part in parts:
        current = Node.query.filter_by(parent_id=current.id, name=part, is_trashed=False).first()
        if current is None:
            return None
    return current


def delete_node_tree(storage: StorageBackend, node: Node) -> None:
    """Deletes `node` and, for folders, every descendant - freeing each
    file's blob and crediting the owner's `storage_used_bytes` back.
    Shared by the Drive App's trash-purge and the WebDAV provider's
    DELETE/recursive-move-overwrite handling so this isn't reimplemented
    (and potentially drift) in two places. Caller must db.session.commit().
    """
    owner = node.owner
    for child in list(node.children):
        delete_node_tree(storage, child)
    if node.type == "file":
        storage.delete(node.id)
        owner.storage_used_bytes = max(owner.storage_used_bytes - node.size_bytes, 0)
    db.session.delete(node)


def trash_node_tree(node: Node) -> None:
    """Marks `node` and every descendant as trashed (Fase 2 fix for the
    Fase 1 limitation noted in Node/trash_node: previously only the node
    itself was marked, so a trashed folder's children silently became
    unreachable instead of showing up in "Papelera" as part of the same
    subtree). Restoring only the top node later (see drive routes) is
    enough to bring the whole subtree back, since descendants keep their
    original `parent_id`.
    """
    now = datetime.now(timezone.utc)
    node.is_trashed = True
    node.trashed_at = now
    for child in node.children:
        if not child.is_trashed:
            trash_node_tree(child)


def restore_node_tree(node: Node) -> None:
    """Inverse of trash_node_tree: restoring only the top node while
    leaving descendants with is_trashed=True would make them vanish (not
    reappear as trashed nor as active) since browse() filters on
    is_trashed=False and Papelera only lists nodes the user explicitly
    trashed at the top level - so the whole subtree must flip back
    together.
    """
    node.is_trashed = False
    node.trashed_at = None
    for child in node.children:
        if child.is_trashed:
            restore_node_tree(child)

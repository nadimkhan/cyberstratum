"""Issue an API key for one workspace.

A machine client acts in exactly one tenant. The key records which
workspace it belongs to, so a client cannot drift into another
tenant's data by being used from somewhere else, and a key whose owner
is a member of several workspaces can say which one it meant.

The plaintext key is printed once, here, and only its SHA-256 digest is
stored: a database leak must not yield usable credentials.

Run with::

    python -m app.cli.issue_key --workspace acme --name "ci pipeline"
    python -m app.cli.issue_key --workspace acme --user owner@example.com
    python -m app.cli.issue_key --workspace acme --expires-days 90
"""

from __future__ import annotations

import argparse
import secrets
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.security import hash_api_key
from app.db.models.identity import ApiKey, User, Workspace, WorkspaceMember
from app.db.session import session_scope

logger = get_logger(__name__)

#: The prefix every issued key starts with, so a key that turns up in a
#: log or a screenshot is recognisable.
KEY_PREFIX = "cs_live_"


class KeyIssuanceError(Exception):
    """Raised when a key cannot be issued as asked."""


def issue_key(
    session: Session,
    *,
    workspace_slug: str,
    name: str,
    user_email: str | None = None,
    expires_days: int | None = None,
) -> tuple[str, ApiKey]:
    """Issue a key for one workspace.

    Args:
        session: The database session.
        workspace_slug: The workspace the key acts in.
        name: A label for the key, so an operator can recognise it.
        user_email: The member the key belongs to. A key without one is
            a service key: it has no human owner, and only the
            workspace bounds it.
        expires_days: Days until the key stops working.

    Returns:
        The plaintext key and the stored row.

    Raises:
        KeyIssuanceError: The workspace, the user or the membership does
            not exist. A key is never issued into a workspace the named
            user is not a member of: that would hand out access the
            person does not have.
    """
    workspace = session.scalars(
        select(Workspace).where(Workspace.slug == workspace_slug)
    ).one_or_none()
    if workspace is None:
        raise KeyIssuanceError(f"no workspace with the slug {workspace_slug!r}")

    user: User | None = None
    if user_email:
        user = session.scalars(
            select(User).where(User.email == user_email)
        ).one_or_none()
        if user is None:
            raise KeyIssuanceError(f"no user with the email {user_email!r}")
        membership = session.scalars(
            select(WorkspaceMember).where(
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.workspace_id == workspace.id,
            )
        ).one_or_none()
        if membership is None:
            raise KeyIssuanceError(
                f"{user_email!r} is not a member of {workspace_slug!r}, so a key "
                "cannot be issued to them for it"
            )

    raw_key = KEY_PREFIX + secrets.token_urlsafe(24)
    row = ApiKey(
        user_id=user.id if user is not None else None,
        workspace_id=workspace.id,
        name=name,
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:12],
        expires_at=(
            datetime.now(UTC) + timedelta(days=expires_days)
            if expires_days is not None
            else None
        ),
    )
    session.add(row)
    session.flush()
    return raw_key, row


def main(argv: Sequence[str] | None = None) -> int:
    """Issue a key and print it once."""
    parser = argparse.ArgumentParser(
        description="Issue an API key for one workspace."
    )
    parser.add_argument(
        "--workspace", required=True, help="The workspace slug the key acts in."
    )
    parser.add_argument("--name", default="api key", help="A label for the key.")
    parser.add_argument(
        "--user",
        default=None,
        help="The member the key belongs to. Omit it for a service key.",
    )
    parser.add_argument(
        "--expires-days",
        type=int,
        default=None,
        help="Days until the key stops working.",
    )
    args = parser.parse_args(argv)

    try:
        with session_scope() as session:
            raw_key, row = issue_key(
                session,
                workspace_slug=args.workspace,
                name=args.name,
                user_email=args.user,
                expires_days=args.expires_days,
            )
    except KeyIssuanceError as exc:
        print(f"cannot issue the key: {exc}", file=sys.stderr)
        return 2

    print(f"key        : {raw_key}")
    print(f"prefix     : {row.key_prefix}")
    print(f"workspace  : {args.workspace}")
    print(
        "expires at : "
        + (row.expires_at.isoformat() if row.expires_at else "never")
    )
    print("The key is shown once. Only its digest is stored.")
    logger.info("api_key_issued", workspace=args.workspace, prefix=row.key_prefix)
    return 0


if __name__ == "__main__":  # pragma: no cover - the entry point
    raise SystemExit(main())

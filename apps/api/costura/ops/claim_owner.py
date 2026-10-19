"""First owner of an organization with no members:
`python -m costura.ops.claim_owner <slug> <email> [--create]`.

`--create` creates the organization when it is missing. The web app refuses the slug named
by `COSTURA_ORG` (the one the environment provider keys bind to), so the operator opens that
organization here. Refuses once the organization has any member; from then on, owners manage
members in Settings.
"""

import argparse
import sys
from collections.abc import Sequence

from costura.ops import OperationError, run


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="costura.ops.claim_owner", description=__doc__)
    parser.add_argument("slug")
    parser.add_argument("email")
    parser.add_argument("--create", action="store_true")
    args = parser.parse_args(argv)

    def operation() -> int:
        from costura.auth import get_or_create_user
        from costura.db import SessionLocal
        from costura.orgs import (
            DuplicateSlug,
            OrganizationClaimed,
            ReservedSlug,
            UnknownOrganization,
            claim_first_owner,
        )

        with SessionLocal() as session:
            try:
                user = get_or_create_user(session, args.email)
                claim_first_owner(session, args.slug, user, create=args.create)
                session.commit()
            except (
                UnknownOrganization,
                OrganizationClaimed,
                ReservedSlug,
                DuplicateSlug,
                ValueError,
            ) as exc:
                session.rollback()
                raise OperationError(str(exc)) from exc
            print(f"{user.email} is owner of {args.slug}")
        return 0

    return run(operation)


if __name__ == "__main__":
    sys.exit(main())

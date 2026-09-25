"""Initial platform schema."""

from collections.abc import Sequence

from alembic import op

from mc_shared.db import Base
from mc_shared import models  # noqa: F401

revision: str = "20260925_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind)

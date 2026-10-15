"""Versioned admin gateway settings and publication state."""
from alembic import op

from aiflux.models import GatewaySettings, GatewaySettingsRevision

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 used live metadata; checkfirst also supports databases bootstrapped by it.
    GatewaySettings.__table__.create(op.get_bind(), checkfirst=True)
    GatewaySettingsRevision.__table__.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    GatewaySettingsRevision.__table__.drop(op.get_bind())
    GatewaySettings.__table__.drop(op.get_bind())

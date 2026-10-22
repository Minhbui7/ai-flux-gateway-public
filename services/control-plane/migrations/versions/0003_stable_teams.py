"""Stable, tenant-scoped team identities for managed gateway controls."""
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from aiflux.models import Team
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    Team.__table__.create(connection, checkfirst=True)
    columns = {column["name"] for column in sa.inspect(connection).get_columns("team_subscriptions")}
    if "team_id" not in columns:
        with op.batch_alter_table("team_subscriptions") as batch:
            batch.add_column(sa.Column("team_id", sa.String(36), nullable=True))
            batch.create_foreign_key("fk_subscription_team", "teams", ["team_id"], ["id"])
            batch.create_index("ix_team_subscriptions_team_id", ["team_id"])
    subscriptions = sa.table(
        "team_subscriptions", sa.column("id"), sa.column("organization_id"),
        sa.column("team"), sa.column("team_id"),
    )
    rows = connection.execute(sa.select(subscriptions)).mappings().all()
    for row in rows:
        if row["team_id"] is not None:
            continue
        identity = str(uuid5(NAMESPACE_URL, f"aiflux:team:{row['organization_id']}:{row['team']}"))
        if connection.execute(sa.select(Team.id).where(Team.id == identity)).first() is None:
            connection.execute(Team.__table__.insert().values(
                id=identity, organization_id=row["organization_id"], name=row["team"],
            ))
        connection.execute(
            subscriptions.update().where(subscriptions.c.id == row["id"]).values(team_id=identity),
        )


def downgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    convention = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    foreign_keys = inspector.get_foreign_keys("team_subscriptions")
    with op.batch_alter_table("team_subscriptions", naming_convention=convention) as batch:
        for index in inspector.get_indexes("team_subscriptions"):
            if "team_id" in index["column_names"]:
                batch.drop_index(index["name"])
        for foreign_key in foreign_keys:
            if "team_id" in foreign_key["constrained_columns"]:
                batch.drop_constraint(
                    foreign_key["name"] or "fk_team_subscriptions_team_id_teams", type_="foreignkey",
                )
        batch.drop_column("team_id")
    Team.__table__.drop(connection, checkfirst=True)

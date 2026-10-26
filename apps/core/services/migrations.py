from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor


def unapplied_migrations(alias: str = DEFAULT_DB_ALIAS) -> list[tuple[str, str]]:
    """Return the (app, migration) pairs ``migrate`` would still apply to this database."""
    executor = MigrationExecutor(connections[alias])
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    return [(migration.app_label, migration.name) for migration, _backwards in plan]

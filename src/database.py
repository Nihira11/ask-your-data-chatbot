"""PostgreSQL integration placeholder. No connection is opened on import."""


def get_schema() -> str:
    """Return allowed tables, column types, and relationships from database metadata."""
    raise NotImplementedError("Connect PostgreSQL and configure the permitted schema first.")


def create_readonly_engine(database_url: str):
    """Configure SQLAlchemy, a restricted DB role, and server-side query limits.

    The function name alone does not enforce read-only access: implement and
    verify database permissions and transaction settings before returning an engine.
    """
    raise NotImplementedError("Read-only database configuration is not implemented.")

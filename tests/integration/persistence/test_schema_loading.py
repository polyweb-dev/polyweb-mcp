"""Every row module is registered in production processes (rework_1 M2).

``Base.metadata`` only knows the tables whose row modules were imported. A
process that imports just the transports and opens the repository must still
resolve every foreign key, or the first flush that touches a cross-module key
fails with ``NoReferencedTableError``. The check runs in a fresh interpreter so
no test-suite import can mask a missing registration.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

_PROBE = textwrap.dedent(
    """
    import asyncio
    import sqlite3
    import sys
    from pathlib import Path

    import freesearch.routers.api  # noqa: F401  (the REST transport)
    import freesearch.mcp.server  # noqa: F401  (the MCP transport)
    from freesearch.persistence.storage import Base, SQLiteRepository

    database = Path(sys.argv[1])


    async def main() -> None:
        repository = await SQLiteRepository.open(database)
        try:
            unresolved = []
            for table in Base.metadata.tables.values():
                for foreign_key in table.foreign_keys:
                    try:
                        foreign_key.column
                    except Exception as error:  # noqa: BLE001
                        unresolved.append(f"{table.name}.{foreign_key.parent.name}: {error}")
            if unresolved:
                print("UNRESOLVED", *unresolved, sep="\\n")
                raise SystemExit(3)
            for required in ("upstream_quota_pools", "execution_dispatches", "project_api_keys"):
                if required not in Base.metadata.tables:
                    print("NOT REGISTERED", required)
                    raise SystemExit(4)

            connection = sqlite3.connect(database)
            connection.execute(
                "INSERT INTO provider_native_pools (pool_id, provider, auth_mode, native_unit, "
                "source, confidence, version, credential_generation, stale, manual_anchor, "
                "tier_split_known) VALUES ('native-1', 'tavily', 'api_key', 'credit', "
                "'observed', 'high', 1, 1, 0, 0, 0)"
            )
            connection.commit()
            connection.close()

            from freesearch.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID
            from freesearch.models.schema_enums import UpstreamScope
            from freesearch.persistence.pools import UpstreamPoolRepository

            async with repository.session() as session:
                pool = await UpstreamPoolRepository(session).create_pool(
                    account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                    provider_type="tavily",
                    upstream_scope=UpstreamScope.ACCOUNT,
                    pool_key="probe",
                    label="probe",
                    constraints=[],
                    native_pool_id="native-1",
                )
                await session.commit()
            print("POOL", pool.native_pool_id)
        finally:
            await repository.close()


    asyncio.run(main())
    """
)


def test_transport_process_registers_every_row_module(tmp_path: Path) -> None:
    database = tmp_path / "transport process.db"

    completed = subprocess.run(
        [sys.executable, "-c", _PROBE, str(database)],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, (completed.stdout, completed.stderr[-3000:])
    assert "POOL native-1" in completed.stdout

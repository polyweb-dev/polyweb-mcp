"""The dev seed uses real auth, RBAC, migrations and encrypted SQLite storage."""

from pathlib import Path

import httpx
import pytest
import scripts.seed_dev as seed_dev
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import SecretStr
from scripts.seed_dev import (
    DEV_DATABASE,
    DEV_PASSWORD,
    MOCK_DEV_DATABASE,
    PROJECTS,
    USER_EMAILS,
    main,
    read_mock_keys,
    read_provider_keys,
    reserve_database,
    seed_database,
)
from sqlalchemy import select, text

from polyweb.configuration.config import Settings
from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore, load_secret_codec
from polyweb.infrastructure.secrets import PROVIDER_ENV_VARS, ProviderName
from polyweb.models.projects import BuiltinRole
from polyweb.persistence.storage import SQLiteRepository
from polyweb.persistence.users import UserRow
from polyweb.services.credentials import credential_secret_slot
from polyweb.services.projects import ProjectNotFound, ProjectService
from polyweb.services.provider_bindings import ProviderBindingService, provider_capability
from polyweb.services.users import AuthService
from polyweb.services.vault_keys import VaultKeyService


async def test_fresh_seed_accounts_memberships_and_encrypted_bindings(tmp_path: Path) -> None:
    """Users can log in; live permissions and provider bindings match the fixture."""

    settings = Settings(
        _env_file=None,
        environment="development",
        encryption_key_file=tmp_path / ".secret_key",
        auth_jwt_secret=SecretStr("fake-test-jwt-secret-at-least-32-characters"),
    )
    database = tmp_path / DEV_DATABASE
    normal_database = tmp_path / "polyweb.db"
    normal_database.write_bytes(b"leave the normal database untouched")
    keys = {
        ProviderName.EXA: SecretStr("fake-dev-exa-key"),
        ProviderName.BRAVE: SecretStr("fake-dev-brave-key"),
    }
    projects = await seed_database(database, settings, keys, SecretStr(DEV_PASSWORD))
    assert [project.slug for project in projects] == ["alpha", "beta", "gamma"]
    assert normal_database.read_bytes() == b"leave the normal database untouched"

    async with await SQLiteRepository.open(database) as repository:
        auth = AuthService(settings, repository=repository)
        users = []
        for email in USER_EMAILS:
            tokens = await auth.login(
                OAuth2PasswordRequestForm(username=email, password=DEV_PASSWORD),
                peer_address="127.0.0.1",
            )
            assert tokens is not None
            user = await auth.verify_token(tokens.access_token.get_secret_value())
            assert user is not None
            users.append(user)
        service = ProjectService(repository)
        for index, user in enumerate(users):
            system_access = await service.system_access(user)
            if index < 2:
                assert "project.create" in system_access.permissions
                assert any(
                    permission.startswith("system.") for permission in system_access.permissions
                )
            else:
                assert system_access.permissions == ["project.create"]
        for project, (_, _, admins, members) in zip(projects, PROJECTS, strict=True):
            administrator = users[admins[0]]
            listed = await service.list_members(administrator, project.id)
            assert {member.email for member in listed} == {
                USER_EMAILS[index] for index in (*admins, *members)
            }
            for member in listed:
                if member.email == USER_EMAILS[2]:
                    assert member.role == "developer" and member.permissions == 15
            for index in (*admins, *members):
                access = await service.project_access(users[index], project.id)
                role = BuiltinRole.PROJECT_ADMIN if index in admins else BuiltinRole.PROJECT_MEMBER
                assert access.roles == [role.value]
                assert "search.execute" in access.permissions
                assert ("members.manage" in access.permissions) == (index in admins)
            bindings = ProviderBindingService(repository)
            view = await bindings.project_providers(administrator, project.id)
            if project.slug == "alpha":
                for provider in keys:
                    item = next(p for p in view.providers if p.provider_type == provider)
                    assert item.available and item.enabled
                    assert set(item.effective_operations) == provider_capability(provider)
            assert len(await bindings.list_bindings(administrator, project.id)) == (
                len(keys) if project.slug == "alpha" else 0
            )
        # A system admin has no implicit membership in Beta; user3 has none in Alpha/Gamma.
        for user, project in (
            (users[0], projects[1]),
            (users[4], projects[0]),
            (users[4], projects[2]),
        ):
            with pytest.raises(ProjectNotFound):
                await service.project_access(user, project.id)

        store = EncryptedDbSecretStore(repository, load_secret_codec(settings))
        credentials = await VaultKeyService(repository, store).list_keys(users[0])
        assert len(credentials) == len(keys)
        for credential in credentials:
            slot = credential_secret_slot(credential.id, credential.generation)
            assert (
                await store.get(slot)
                == keys[ProviderName(credential.provider_type)].get_secret_value()
            )
        async with repository.session() as session:
            rows = list((await session.scalars(select(UserRow))).all())
            assert len(rows) == 5
            assert all(row.hashed_password != DEV_PASSWORD for row in rows)
            owners = (
                await session.execute(
                    text(
                        "SELECT provider_type,owner_user_id FROM provider_credentials "
                        "WHERE auth_mode != 'keyless'"
                    )
                )
            ).all()
            assert set(owners) == {(provider.value, str(users[0].id)) for provider in keys}
            labels = (
                await session.execute(text("SELECT provider_type,label FROM key_pools"))
            ).all()
            assert set(labels) == {(provider.value, projects[0].name) for provider in keys}
            pools = (
                await session.execute(
                    text("SELECT provider_type,project_id,rate_limit,budget_limit FROM key_pools")
                )
            ).all()
            assert set(pools) == {
                (provider.value, str(projects[0].id), 60, 20_000_000) for provider in keys
            }
            allocations = (
                await session.execute(
                    text(
                        "SELECT k.provider_type,a.project_id,a.operation_scope,a.base_rate "
                        "FROM project_pool_allocations a JOIN key_pools k ON k.id=a.key_pool_id"
                    )
                )
            ).all()
            assert set(allocations) == {
                (provider.value, str(projects[0].id), operation.value, 60)
                for provider in keys
                for operation in provider_capability(provider.value)
            }
            assert not (await session.execute(text("PRAGMA foreign_key_check"))).all()
    contents = database.read_bytes()
    assert DEV_PASSWORD.encode() not in contents
    assert all(key.get_secret_value().encode() not in contents for key in keys.values())
    before = database.read_bytes()
    with pytest.raises(FileExistsError):
        await seed_database(database, settings, keys, SecretStr(DEV_PASSWORD))
    assert database.read_bytes() == before


def test_env_key_import_is_explicit_and_never_prints_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for variable in (*PROVIDER_ENV_VARS.values(), "TINYFISH_API_KEY"):
        monkeypatch.delenv(variable, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        'POLYWEB_EXA_API_KEY="fake-exa-from-file" # comment\n'
        "POLYWEB_BRAVE_SEARCH_API_KEY='fake-brave'\n"
        "POLYWEB_BRAVE_ANSWERS_API_KEY=unused-answers\n"
        "POLYWEB_TINYFISH_API_KEY=fake-tinyfish\n"
        "POLYWEB_TAVILY_API_KEY=\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("POLYWEB_EXA_API_KEY", "fake-process-exa")
    keys = read_provider_keys(env_file)
    assert set(keys) == {ProviderName.EXA, ProviderName.BRAVE, ProviderName.TINYFISH}
    assert keys[ProviderName.EXA].get_secret_value() == "fake-process-exa"
    assert keys[ProviderName.BRAVE].get_secret_value() == "fake-brave"
    assert "fake-process-exa" not in repr(keys)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("name", ["polyweb.db", "production.db", "other.dev.db"])
def test_seed_rejects_normal_database_paths(tmp_path: Path, name: str) -> None:
    database = tmp_path / name
    database.write_bytes(b"do not touch")
    with pytest.raises(ValueError, match="normal databases are protected"):
        reserve_database(database)
    assert database.read_bytes() == b"do not touch"


async def test_production_and_leftover_sidecars_are_rejected(tmp_path: Path) -> None:
    database = tmp_path / DEV_DATABASE
    with pytest.raises(ValueError, match="requires POLYWEB_ENVIRONMENT=development"):
        await seed_database(
            database,
            Settings(_env_file=None, environment="production"),
            {},
            SecretStr(DEV_PASSWORD),
        )
    assert not database.exists()
    sidecar = Path(f"{database}-wal")
    sidecar.write_bytes(b"backend may be running")
    with pytest.raises(FileExistsError, match="sidecars exist"):
        reserve_database(database)
    assert sidecar.read_bytes() == b"backend may be running"
    assert not database.exists()


def test_cli_failure_does_not_leak_a_configured_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("POLYWEB_HTTP_TIMEOUT_SECONDS", "fake-sensitive-bad-value")
    env_file = tmp_path / ".env"
    env_file.write_text("POLYWEB_ENVIRONMENT=development\n", encoding="utf-8")
    assert main(["--database", str(tmp_path / DEV_DATABASE), "--env-file", str(env_file)]) == 1
    output = capsys.readouterr()
    assert "failed validation" in output.err
    assert "fake-sensitive-bad-value" not in output.err
    assert not (tmp_path / DEV_DATABASE).exists()


_MOCK_EXPORT = (
    "POLYWEB_BRAVE_ANSWERS_API_KEY=BSAmock-answers\n"
    "POLYWEB_BRAVE_SEARCH_API_KEY=BSAmock-search\n"
    "POLYWEB_EXA_API_KEY=6d6f636b-exa\n"
    "POLYWEB_FIRECRAWL_API_KEY=fc-mock\n"
    "POLYWEB_KEENABLE_API_KEY=keen_mock\n"
    "POLYWEB_PARALLEL_API_KEY=mock-parallel\n"
    "POLYWEB_TAVILY_API_KEY=tvly-dev-mock\n"
    "POLYWEB_TINYFISH_API_KEY=mock-tinyfish\n"
    "POLYWEB_YOU_API_KEY=ydc-sk-mock\n"
)


def test_mock_keys_come_from_the_seeded_mock_admin_api() -> None:
    """Mock mode seeds the mock first, then maps every exported provider variable."""

    seen: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.url.path == "/_mock/seed":
            return httpx.Response(200, json={"tavily": 1})
        return httpx.Response(200, text=_MOCK_EXPORT)

    keys = read_mock_keys(
        "http://127.0.0.1:8212", admin_token="fake-admin", transport=httpx.MockTransport(handler)
    )

    assert [(method, path) for method, path, _ in seen] == [
        ("POST", "/_mock/seed"),
        ("GET", "/_mock/export-keys"),
    ]
    assert {auth for _, _, auth in seen} == {"Bearer fake-admin"}
    assert set(keys) == set(ProviderName)
    assert keys[ProviderName.BRAVE].get_secret_value() == "BSAmock-search"
    assert keys[ProviderName.TAVILY].get_secret_value() == "tvly-dev-mock"


@pytest.mark.parametrize("origin", ["127.0.0.1:8212", "ftp://127.0.0.1:8212"])
def test_mock_keys_need_an_http_origin(origin: str) -> None:
    with pytest.raises(ValueError, match="needs the mock origin"):
        read_mock_keys(origin)


def test_an_unreachable_mock_is_a_safe_refusal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(
        ValueError, match=r"provider mock at http://127.0.0.1:8212 failed \(ConnectError\)"
    ):
        read_mock_keys("http://127.0.0.1:8212", transport=httpx.MockTransport(handler))


async def test_mock_seed_adds_keyless_pools_to_beta(tmp_path: Path) -> None:
    """Alpha keeps the keyed pools; Beta gets keyless Keenable and Tavily pools."""

    settings = Settings(
        _env_file=None,
        environment="development",
        encryption_key_file=tmp_path / ".secret_key",
        auth_jwt_secret=SecretStr("fake-test-jwt-secret-at-least-32-characters"),
    )
    keys = {ProviderName.TAVILY: SecretStr("tvly-dev-mock"), ProviderName.EXA: SecretStr("exa")}
    with pytest.raises(ValueError, match=f"Only a new {MOCK_DEV_DATABASE}"):
        await seed_database(
            tmp_path / DEV_DATABASE, settings, keys, SecretStr(DEV_PASSWORD), mock=True
        )
    database = tmp_path / MOCK_DEV_DATABASE
    projects = await seed_database(database, settings, keys, SecretStr(DEV_PASSWORD), mock=True)

    async with (
        await SQLiteRepository.open(database) as repository,
        repository.session() as session,
    ):
        pools = (
            await session.execute(
                text(
                    "SELECT k.provider_type,k.project_id,c.auth_mode FROM key_pools k "
                    "JOIN provider_credentials c ON c.id=k.credential_id"
                )
            )
        ).all()
        assert set(pools) == {
            ("tavily", str(projects[0].id), "api_key"),
            ("exa", str(projects[0].id), "api_key"),
            ("keenable", str(projects[1].id), "keyless"),
            ("tavily", str(projects[1].id), "keyless"),
        }
        assert not (await session.execute(text("PRAGMA foreign_key_check"))).all()


def test_cli_mock_mode_never_reads_env_file_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for variable in PROVIDER_ENV_VARS.values():
        monkeypatch.delenv(variable, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POLYWEB_ENVIRONMENT=development\n"
        f"POLYWEB_ENCRYPTION_KEY_FILE={tmp_path / '.secret_key'}\n"
        "POLYWEB_EXA_API_KEY=fake-real-looking-exa\n",
        encoding="utf-8",
    )
    origins: list[str] = []

    def fake_mock_keys(origin: str, **_: object) -> dict[ProviderName, SecretStr]:
        origins.append(origin)
        return {ProviderName.TAVILY: SecretStr("tvly-dev-mock")}

    def no_env_keys(_: Path) -> None:
        raise AssertionError("mock mode must not read provider keys from the env file")

    monkeypatch.setattr(seed_dev, "read_mock_keys", fake_mock_keys)
    monkeypatch.setattr(seed_dev, "read_provider_keys", no_env_keys)
    monkeypatch.chdir(tmp_path)

    assert main(["--keys-from-mock", "http://127.0.0.1:8212", "--env-file", str(env_file)]) == 0

    output = capsys.readouterr().out
    assert origins == ["http://127.0.0.1:8212"]
    assert (tmp_path / MOCK_DEV_DATABASE).exists() and not (tmp_path / DEV_DATABASE).exists()
    assert "Imported providers: tavily" in output
    assert "POLYWEB_PROVIDER_MOCK_URL=http://127.0.0.1:8212" in output
    assert "fake-real-looking-exa" not in output and "tvly-dev-mock" not in output

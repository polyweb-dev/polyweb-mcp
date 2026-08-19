from freesearch.secrets import (
    PROVIDER_ENV_VARS,
    ProviderName,
    ProviderSecretResolver,
)


class MemorySecretStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def test_all_seven_providers_have_explicit_environment_names() -> None:
    assert set(PROVIDER_ENV_VARS) == set(ProviderName)
    assert PROVIDER_ENV_VARS[ProviderName.YOU] == "FREESEARCH_YOU_API_KEY"


def test_environment_secret_takes_precedence_over_keyring() -> None:
    store = MemorySecretStore()
    store.set(ProviderName.EXA.value, "keyring-value")
    resolver = ProviderSecretResolver(
        store=store,
        environ={PROVIDER_ENV_VARS[ProviderName.EXA]: "environment-value"},
    )

    secret = resolver.get(ProviderName.EXA)

    assert secret is not None
    assert secret.get_secret_value() == "environment-value"


def test_keyring_secret_can_be_written_and_deleted_without_plaintext_config() -> None:
    store = MemorySecretStore()
    resolver = ProviderSecretResolver(store=store, environ={})

    resolver.set(ProviderName.BRAVE, "brave-secret")
    secret = resolver.get(ProviderName.BRAVE)
    assert secret is not None
    assert secret.get_secret_value() == "brave-secret"

    resolver.delete(ProviderName.BRAVE)
    assert resolver.get(ProviderName.BRAVE) is None

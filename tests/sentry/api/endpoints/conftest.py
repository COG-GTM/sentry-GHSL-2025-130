from uuid import uuid4

import pytest
from sentry_relay.auth import PublicKey, SecretKey


@pytest.fixture
def key_pair() -> tuple[SecretKey, PublicKey]:
    from sentry_relay.auth import generate_key_pair

    return generate_key_pair()


@pytest.fixture
def public_key(key_pair: tuple[SecretKey, PublicKey]) -> PublicKey:
    return key_pair[1]


@pytest.fixture
def private_key(key_pair: tuple[SecretKey, PublicKey]) -> SecretKey:
    return key_pair[0]


@pytest.fixture
def relay_id() -> str:
    return str(uuid4())


@pytest.fixture
def relay(relay_id: str | int, public_key: PublicKey, settings):
    from sentry.models.relay import Relay

    # internal relays are only trusted when their public key is configured
    settings.SENTRY_RELAY_WHITELIST_PK = [*settings.SENTRY_RELAY_WHITELIST_PK, str(public_key)]

    return Relay.objects.create(relay_id=relay_id, public_key=str(public_key), is_internal=True)

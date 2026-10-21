import pytest
from pydantic import ValidationError

from app.config import MAX_RANKING_LIMIT, Settings


def test_settings_validate_limits_and_timezone():
    with pytest.raises(ValidationError, match="DEFAULT_RANKING_LIMIT"):
        Settings(_env_file=None, default_ranking_limit=20, max_ranking_limit=10)
    with pytest.raises(ValidationError, match="unknown IANA timezone"):
        Settings(_env_file=None, app_timezone="Mars/Olympus")


def test_ranking_limit_cannot_exceed_the_verified_adapter_cap():
    # The API, the export and the adapter share one cap: a configured limit
    # must never promise more rows than the adapter can fetch.
    assert Settings(_env_file=None).max_ranking_limit == MAX_RANKING_LIMIT
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_ranking_limit=MAX_RANKING_LIMIT + 1)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, default_ranking_limit=MAX_RANKING_LIMIT + 1)


def test_production_collection_requires_admin_token():
    with pytest.raises(ValidationError, match="ADMIN_TOKEN"):
        Settings(_env_file=None, app_env="production", collection_enabled=True, admin_token=None)
    with pytest.raises(ValidationError, match="at least 24"):
        Settings(
            _env_file=None,
            app_env="production",
            collection_enabled=True,
            admin_token="too-short",
        )
    secret = "a-production-secret-long-enough"
    configured = Settings(
        _env_file=None, app_env="production", collection_enabled=True, admin_token=secret
    )
    assert configured.admin_token_value == secret
    assert secret not in repr(configured.admin_token)

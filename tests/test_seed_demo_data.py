from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import Category, Product, RankObservation, Snapshot
from scripts import seed_demo_data


@pytest.fixture
def demo_settings(settings, monkeypatch):
    # The demo fixture is only permitted in development or test environments;
    # the test settings use app_env=test.
    monkeypatch.setattr(seed_demo_data, "Settings", lambda: settings)
    return settings


@pytest.mark.usefixtures("demo_settings")
def test_demo_fixture_can_be_seeded_and_reset(session_factory):
    seed_demo_data.seed(reset=False)
    with session_factory() as db:
        assert db.scalar(select(func.count(Product.id))) == 12
        assert db.scalar(select(func.count(Category.id))) == 2
        assert db.scalar(select(func.count(RankObservation.id))) > 0
        assert db.scalar(select(func.count(Snapshot.id))) > 0

    # A second run without --reset keeps the existing fixture.
    seed_demo_data.seed(reset=False)
    with session_factory() as db:
        assert db.scalar(select(func.count(Product.id))) == 12

    # The reset replaces the fixture; the category foreign keys refuse to
    # delete a demo category that still owns observations.
    seed_demo_data.seed(reset=True)
    with session_factory() as db:
        assert db.scalar(select(func.count(Product.id))) == 12
        assert db.scalar(select(func.count(Category.id))) == 2
        assert db.scalar(select(func.count(RankObservation.id))) > 0

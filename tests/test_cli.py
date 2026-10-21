from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.models import CollectionRun
from scripts import collect


def cli_args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "limit": 3,
        "category_id": [],
        "no_global": False,
        "with_price_history": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def install_cli(monkeypatch, settings, engine, mock_adapter) -> None:
    monkeypatch.setattr(collect, "Settings", lambda: settings)
    monkeypatch.setattr(collect, "create_database_engine", lambda _url: engine)
    monkeypatch.setattr(collect, "build_adapter", lambda _value: mock_adapter)


def read_outcomes(output: str) -> list[dict[str, Any]]:
    start = output.index("[")
    return json.loads(output[start:])


@pytest.mark.usefixtures("seeded_market")
def test_cli_skips_the_global_scope_when_asked(
    monkeypatch, capsys, settings, engine, mock_adapter, session_factory
):
    install_cli(monkeypatch, settings, engine, mock_adapter)
    with session_factory() as db:
        global_runs_before = len(
            list(db.scalars(select(CollectionRun).where(CollectionRun.scope_key == "global")))
        )
    exit_code = asyncio.run(collect.run(cli_args(no_global=True)))
    captured = capsys.readouterr()
    assert exit_code == 0
    outcomes = read_outcomes(captured.out)
    assert outcomes
    assert all(outcome["scope_key"].startswith("category:") for outcome in outcomes)
    with session_factory() as db:
        global_runs_after = len(
            list(db.scalars(select(CollectionRun).where(CollectionRun.scope_key == "global")))
        )
        category_runs = list(
            db.scalars(select(CollectionRun).where(CollectionRun.scope_key.like("category:%")))
        )
    # The global scope was not collected, the category scope was.
    assert global_runs_after == global_runs_before
    assert category_runs


def test_cli_reports_a_locked_scope_without_a_traceback(
    monkeypatch, capsys, settings, engine, mock_adapter, seeded_market
):
    install_cli(monkeypatch, settings, engine, mock_adapter)
    category_id = seeded_market["category_a"]
    digest = hashlib.sha256(f"category:{category_id}:best_selling".encode()).hexdigest()[:20]
    lock_path = Path(settings.collection_lock_dir) / f"collection-{digest}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        exit_code = asyncio.run(collect.run(cli_args(category_id=[category_id], no_global=True)))
    finally:
        os.close(descriptor)
    captured = capsys.readouterr()
    assert exit_code == 0
    outcomes = read_outcomes(captured.out)
    assert outcomes[0]["status"] == "skipped"
    assert "already running" in outcomes[0]["error"]
    assert "Traceback" not in captured.err


def test_cli_reports_an_unknown_category_without_a_traceback(
    monkeypatch, capsys, settings, engine, mock_adapter
):
    install_cli(monkeypatch, settings, engine, mock_adapter)
    exit_code = asyncio.run(collect.run(cli_args(category_id=[9999])))
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "unknown category" in captured.err
    assert "Traceback" not in captured.err

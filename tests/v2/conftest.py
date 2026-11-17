"""
Shared fixtures for the version 2 tests. Each test gets a fresh in-memory
database seeded with synthetic data and a FakeProvider, so tests are fast,
offline and never touch real logs.
"""

import copy

import pytest

from qmtutor.llm.providers import FakeProvider
from qmtutor.seed import seed
from qmtutor.services.auth import record_consent
from qmtutor.services.context import build_context, load_settings


@pytest.fixture
def settings():
    s = copy.deepcopy(load_settings())
    s["features"]["assess_reasoning_with_llm"] = False   # individual tests switch it on
    return s


@pytest.fixture
def fake():
    return FakeProvider()


@pytest.fixture
def ctx(settings, fake):
    context = build_context(settings, db_path=":memory:", provider=fake)
    seed(context)
    return context


@pytest.fixture
def student(ctx):
    """S001: scaffolded arm, notice acknowledged."""
    user = ctx.users.get("S001")
    record_consent(ctx, user, True)
    return user


def consented(ctx, user_id):
    user = ctx.users.get(user_id)
    record_consent(ctx, user, True)
    return user

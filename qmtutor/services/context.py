"""
Application context: builds the shared objects (database, repositories, LLM
provider, retriever, settings) once, so services and pages receive them
instead of creating their own. Tests build a context with an in-memory
database and a FakeProvider.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from qmtutor.llm.providers import LLMProvider, make_provider
from qmtutor.retrieval.search import EmbeddingRetriever, LexicalRetriever, Retriever
from qmtutor.storage.db import Database, open_database
from qmtutor.storage.repositories import (
    ContentRepository, EvidenceRepository, ExerciseRepository, PolicyRepository, UserRepository,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class AppContext:
    settings: dict
    db: Database
    provider: LLMProvider
    retriever: Retriever
    users: UserRepository
    content: ContentRepository
    policies: PolicyRepository
    exercises: ExerciseRepository
    evidence: EvidenceRepository

    @property
    def model_label(self) -> str:
        return f"{self.provider.name}:{self.provider.model}"


def load_settings(path: str | Path = "config_v2.yaml") -> dict:
    return yaml.safe_load((PROJECT_ROOT / path).read_text(encoding="utf-8"))


def build_context(settings: dict | None = None, db_path: str | None = None,
                  provider: LLMProvider | None = None) -> AppContext:
    settings = settings or load_settings()
    path = db_path or str(PROJECT_ROOT / settings["database"])
    db = open_database(path)
    if settings["retrieval"]["backend"] == "embedding":
        retriever = EmbeddingRetriever(db, settings["retrieval"]["embedding_model"])
    else:
        retriever = LexicalRetriever(db)
    return AppContext(settings=settings, db=db, provider=provider or make_provider(settings["llm"]),
                      retriever=retriever, users=UserRepository(db), content=ContentRepository(db),
                      policies=PolicyRepository(db), exercises=ExerciseRepository(db),
                      evidence=EvidenceRepository(db))

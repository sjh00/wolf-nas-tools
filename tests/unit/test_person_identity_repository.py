"""人员实体仓储测试."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.db.repositories.person_identity_repository import PersonIdentityRepository
from app.db.session import SessionManager


@pytest.fixture
def repo():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    manager = SessionManager()
    manager._engine = engine
    manager._factory = sessionmaker(bind=engine, expire_on_commit=False)
    PersonIdentityRepository._session_manager = manager
    yield PersonIdentityRepository()
    engine.dispose()


def test_person_ensure_and_ref_lookup(repo):
    person = repo.ensure_person(name="演员A", aliases=["A"], images=["a.jpg"])
    assert len(person.PERSON_ID) == 26
    assert repo.decode_person(person)["aliases"] == ["A"]

    repo.upsert_ref(person.PERSON_ID, provider="tmdb", external_id="1")
    found = repo.find_by_ref("tmdb", "1")
    assert found is not None
    assert found.PERSON_ID == person.PERSON_ID
    assert [(item.PROVIDER, item.EXTERNAL_ID) for item in repo.get_refs(person.PERSON_ID)] == [("tmdb", "1")]


def test_person_ref_cannot_be_reassigned(repo):
    first = repo.ensure_person(name="A")
    second = repo.ensure_person(name="B")
    repo.upsert_ref(first.PERSON_ID, provider="douban", external_id="2")

    with pytest.raises(ValueError, match="已属于其他人员"):
        repo.upsert_ref(second.PERSON_ID, provider="douban", external_id="2")

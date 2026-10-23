"""人员实体仓储."""

from __future__ import annotations

import json
from typing import Any

from app.db.models.media_identity import PersonExternalRef, PersonIdentity
from app.db.repositories.base_repository import BaseRepository
from app.utils.ulid import new_ulid


class PersonIdentityRepository(BaseRepository):
    def get_person(self, person_id: str) -> PersonIdentity | None:
        if not person_id:
            return None
        with self.readonly() as db:
            return db.query(PersonIdentity).filter(PersonIdentity.PERSON_ID == person_id).first()

    def find_by_ref(self, provider: str, external_id: str) -> PersonIdentity | None:
        with self.readonly() as db:
            ref = (
                db.query(PersonExternalRef)
                .filter(
                    PersonExternalRef.PROVIDER == provider,
                    PersonExternalRef.EXTERNAL_ID == str(external_id),
                )
                .first()
            )
            if ref is None:
                return None
            return db.query(PersonIdentity).filter(PersonIdentity.PERSON_ID == ref.PERSON_ID).first()

    def ensure_person(
        self,
        *,
        name: str,
        person_id: str | None = None,
        aliases: list[str] | None = None,
        images: list[str] | None = None,
    ) -> PersonIdentity:
        target_id = person_id or new_ulid()
        with self.session() as db:
            person = db.query(PersonIdentity).filter(PersonIdentity.PERSON_ID == target_id).first()
            if person is None:
                person = PersonIdentity(
                    PERSON_ID=target_id,
                    CANONICAL_NAME=name,
                    ALIASES=json.dumps(aliases or [], ensure_ascii=False),
                    IMAGES=json.dumps(images or [], ensure_ascii=False),
                )
                db.add(person)
                db.commit()
                db.refresh(person)
            return person

    def upsert_ref(
        self,
        person_id: str,
        *,
        provider: str,
        external_id: str,
        url: str | None = None,
    ) -> PersonExternalRef:
        with self.session() as db:
            ref = (
                db.query(PersonExternalRef)
                .filter(
                    PersonExternalRef.PROVIDER == provider,
                    PersonExternalRef.EXTERNAL_ID == str(external_id),
                )
                .first()
            )
            if ref is None:
                ref = PersonExternalRef(
                    PERSON_ID=person_id,
                    PROVIDER=provider,
                    EXTERNAL_ID=str(external_id),
                    URL=url,
                )
                db.add(ref)
                db.commit()
                db.refresh(ref)
                return ref
            if ref.PERSON_ID != person_id:
                raise ValueError(f"人员引用 {provider}:{external_id} 已属于其他人员")
            ref.URL = url or ref.URL
            db.commit()
            db.refresh(ref)
            return ref

    def get_refs(self, person_id: str) -> list[PersonExternalRef]:
        with self.readonly() as db:
            return db.query(PersonExternalRef).filter(PersonExternalRef.PERSON_ID == person_id).all()

    @staticmethod
    def decode_person(person: PersonIdentity) -> dict[str, Any]:
        return {
            "person_id": person.PERSON_ID,
            "name": person.CANONICAL_NAME,
            "aliases": json.loads(person.ALIASES or "[]"),
            "images": json.loads(person.IMAGES or "[]"),
        }

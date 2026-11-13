"""SQLite system of record. PostgreSQL is used only when a local URL is passed."""

import json
import threading
from typing import Any

from sqlalchemy import Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "runs"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


class StepRow(Base):
    __tablename__ = "steps"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


class EffectRow(Base):
    __tablename__ = "effects"
    effect_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


class AuditRow(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


class TraceRow(Base):
    __tablename__ = "traces"
    trace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


class ReviewRow(Base):
    __tablename__ = "judge_reviews"
    dataset_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


class ReleaseRow(Base):
    __tablename__ = "releases"
    model_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


class Store:
    def __init__(self, url: str = "sqlite://") -> None:
        kwargs: dict[str, Any] = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            kwargs["poolclass"] = StaticPool
        self.engine = create_engine(url, **kwargs)
        self.kind = "postgres" if url.startswith("postgresql") else "sqlite"
        self._lock = threading.Lock()
        Base.metadata.create_all(self.engine)

    def save_run(self, run_id: str, payload: dict[str, Any]) -> None:
        self._upsert(RunRow, {"run_id": run_id}, {"payload": json.dumps(payload)})

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            row = session.get(RunRow, run_id)
            if row is None:
                return None
            loaded = json.loads(row.payload)
            if not isinstance(loaded, dict):
                raise RuntimeError("run payload was not an object")
            return loaded

    def save_step(self, run_id: str, name: str, payload: dict[str, Any]) -> None:
        body = json.dumps(payload)
        with self._lock, Session(self.engine) as session:
            row = session.get(StepRow, {"run_id": run_id, "name": name})
            if row is None:
                session.add(StepRow(run_id=run_id, name=name, payload=body))
            else:
                row.payload = body
            session.commit()

    def get_step(self, run_id: str, name: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            row = session.get(StepRow, {"run_id": run_id, "name": name})
            if row is None:
                return None
            loaded = json.loads(row.payload)
            if not isinstance(loaded, dict):
                raise RuntimeError("step payload was not an object")
            return loaded

    def apply_effect(self, effect_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock, Session(self.engine) as session:
            row = session.get(EffectRow, effect_key)
            if row is not None:
                loaded = json.loads(row.payload)
                if not isinstance(loaded, dict):
                    raise RuntimeError("effect payload was not an object")
                loaded["idempotent"] = True
                return loaded
            stored = dict(payload)
            stored["idempotent"] = False
            session.add(EffectRow(effect_key=effect_key, payload=json.dumps(stored)))
            session.commit()
            return stored

    def effect_count(self) -> int:
        with Session(self.engine) as session:
            return len(session.scalars(select(EffectRow)).all())

    def add_audit(self, payload: dict[str, Any]) -> None:
        with self._lock, Session(self.engine) as session:
            session.add(AuditRow(payload=json.dumps(payload)))
            session.commit()

    def audit(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.scalars(select(AuditRow).order_by(AuditRow.id)).all()
            return [json.loads(row.payload) for row in rows]

    def add_trace(self, trace_id: str, workflow_id: str, payload: dict[str, Any]) -> None:
        body = json.dumps(payload)
        with self._lock, Session(self.engine) as session:
            row = session.get(TraceRow, trace_id)
            if row is None:
                session.add(TraceRow(trace_id=trace_id, workflow_id=workflow_id, payload=body))
            else:
                row.payload = body
                row.workflow_id = workflow_id
            session.commit()

    def traces(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.scalars(select(TraceRow)).all()
            return [json.loads(row.payload) for row in rows]

    def save_review(self, dataset_version: str, payload: dict[str, Any]) -> None:
        self._upsert(
            ReviewRow,
            {"dataset_version": dataset_version},
            {"payload": json.dumps(payload)},
        )

    def get_review(self, dataset_version: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            row = session.get(ReviewRow, dataset_version)
            if row is None:
                return None
            loaded = json.loads(row.payload)
            if not isinstance(loaded, dict):
                raise RuntimeError("review payload was not an object")
            return loaded

    def save_release(self, model_id: str, payload: dict[str, Any]) -> None:
        self._upsert(ReleaseRow, {"model_id": model_id}, {"payload": json.dumps(payload)})

    def releases(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.scalars(select(ReleaseRow)).all()
            return [json.loads(row.payload) for row in rows]

    def _upsert(self, model: type[Any], key: dict[str, Any], values: dict[str, Any]) -> None:
        with self._lock, Session(self.engine) as session:
            row = session.get(model, key)
            if row is None:
                session.add(model(**key, **values))
            else:
                for name, value in values.items():
                    setattr(row, name, value)
            session.commit()

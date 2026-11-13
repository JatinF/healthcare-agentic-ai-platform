"""Shadow, canary, and active model stages. A failed gate never promotes."""

import zlib
from typing import Any

from healthcare_platform.errors import FlowError
from healthcare_platform.evaluation import Scorecard, release_reasons
from healthcare_platform.identity import Actor, require_scope
from healthcare_platform.store import Store

CANARY_BUCKETS = 10


class Registry:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.ineligible_promotions = 0

    def stage_of(self, model_id: str) -> str | None:
        for row in self.store.releases():
            if row.get("model_id") == model_id:
                stage = row.get("stage")
                return str(stage) if isinstance(stage, str) else None
        return None

    def active(self) -> dict[str, Any] | None:
        for row in self.store.releases():
            if row.get("stage") == "active":
                return row
        return None

    def promote(
        self,
        model_id: str,
        card: Scorecard,
        actor: Actor,
        *,
        stage: str,
    ) -> dict[str, Any]:
        require_scope(actor, "registry.promote")
        if stage not in {"shadow", "canary", "active"}:
            raise FlowError("bad_stage", "stage must be shadow, canary, or active")
        active = self.active()
        active_score = None
        if active is not None and active.get("model_id") != model_id:
            raw = active.get("exact_match")
            if isinstance(raw, float | int):
                active_score = float(raw)
        reasons = release_reasons(card, active_exact_match=active_score)
        if reasons:
            self.store.add_audit(
                {
                    "action": "promotion_rejected",
                    "model_id": model_id,
                    "actor_id": actor.user_id,
                    "reasons": reasons,
                }
            )
            return {"promoted": False, "reasons": reasons, "stage": self.stage_of(model_id)}
        if stage == "active" and active is not None and active.get("model_id") != model_id:
            previous = dict(active)
            previous["stage"] = "retired"
            self.store.save_release(str(previous["model_id"]), previous)
        payload = {
            "model_id": model_id,
            "stage": stage,
            "exact_match": card.exact_match,
            "phi_leaks": card.phi_leaks,
            "actor_id": actor.user_id,
            "eligible": True,
        }
        self.store.save_release(model_id, payload)
        return {"promoted": True, "reasons": [], "stage": stage}

    def rollback(self, actor: Actor) -> dict[str, Any]:
        require_scope(actor, "registry.promote")
        rows = self.store.releases()
        active = next((row for row in rows if row.get("stage") == "active"), None)
        retired = [row for row in rows if row.get("stage") == "retired"]
        if active is None or not retired:
            raise FlowError("nothing_to_roll_back", "no retired release to restore", 409)
        previous = retired[-1]
        current = dict(active)
        current["stage"] = "retired"
        restored = dict(previous)
        restored["stage"] = "active"
        self.store.save_release(str(current["model_id"]), current)
        self.store.save_release(str(restored["model_id"]), restored)
        return {"active": restored["model_id"]}

    def serve(self, case_id: str) -> str:
        active = self.active()
        if active is None:
            raise FlowError("no_active_model", "no active model", 409)
        canaries = [row for row in self.store.releases() if row.get("stage") == "canary"]
        if canaries and zlib.crc32(case_id.encode("utf-8")) % CANARY_BUCKETS == 0:
            return str(canaries[-1]["model_id"])
        return str(active["model_id"])

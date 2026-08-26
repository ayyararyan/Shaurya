"""CON-06: normative object-category labels used across Shaurya artifacts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import field_validator

from .base import ContractModel


class ObjectCategory(StrEnum):
    """Identification status of an object, never its storage or processing state."""

    OBSERVED = "observed"
    DERIVED = "derived"
    ESTIMATED = "estimated"
    SCENARIO = "scenario"
    PROXY = "proxy"
    UNIDENTIFIED = "unidentified"


CATEGORY_SEMANTICS: dict[ObjectCategory, str] = {
    ObjectCategory.OBSERVED: "present directly in an authoritative source",
    ObjectCategory.DERIVED: "computed deterministically from observed data without fitting",
    ObjectCategory.ESTIMATED: "obtained from a fitted statistical or numerical model",
    ObjectCategory.SCENARIO: "computed under an explicit assumption or counterfactual parameter",
    ObjectCategory.PROXY: "an imperfect observable or simulation standing in for a target",
    ObjectCategory.UNIDENTIFIED: (
        "not recoverable from available data without additional information or assumptions"
    ),
}


class ObjectLabel(ContractModel):
    """Serializable label and provenance for one named artifact object."""

    object_name: str
    category: ObjectCategory
    source: str
    construction: str | None = None
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @field_validator("object_name", "source")
    @classmethod
    def _required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("object label names and sources must be non-empty")
        return value.strip()

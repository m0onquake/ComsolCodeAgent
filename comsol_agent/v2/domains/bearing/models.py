"""Strict contracts and minimal-change routing for cylindrical roller bearings."""

from __future__ import annotations

import hashlib
import json
import math
from enum import StrEnum
from typing import Any

from pydantic import Field, computed_field, model_validator

from comsol_agent.v2.contracts.models import ContractModel

BEARING_SCHEMA_VERSION = "1.0"
BUILDER_VERSION = "1.0.0"


class LoadDirection(StrEnum):
    POSITIVE_X = "+X"
    NEGATIVE_X = "-X"
    POSITIVE_Y = "+Y"
    NEGATIVE_Y = "-Y"


class ChangeClass(StrEnum):
    NONE = "none"
    LOAD_PARAMETER = "load_parameter"
    GEOMETRY_PARAMETER = "geometry_parameter"
    ROLLER_COUNT = "roller_count"
    PHASE_PARAMETER = "phase_parameter"
    DIRECTION_PARAMETER = "direction_parameter"
    SOLVER_PARAMETER = "solver_parameter"
    TOPOLOGY = "topology"


class ChangeRoute(StrEnum):
    NOOP = "noop"
    PARAMETER_OVERRIDE = "parameter_override"
    DETERMINISTIC_REBUILD = "deterministic_rebuild"
    UNSUPPORTED_TOPOLOGY = "unsupported_topology"


class BearingSpec(ContractModel):
    """Supported V2 cylindrical-roller specification in explicit engineering units."""

    domain: str = Field(default="bearing", pattern="^bearing$")
    schema_version: str = Field(default=BEARING_SCHEMA_VERSION, pattern="^1\\.0$")
    family: str = Field(default="cylindrical_roller", pattern="^cylindrical_roller$")
    model_dimension: int = Field(default=3, ge=3, le=3)
    roller_count: int = Field(default=12, ge=3, le=24)
    inner_diameter_mm: float = Field(default=40.0, gt=0, le=200)
    outer_diameter_mm: float = Field(default=80.0, gt=0, le=300)
    bearing_width_mm: float = Field(default=18.0, gt=0, le=100)
    roller_diameter_mm: float = Field(default=8.0, gt=0, le=50)
    roller_length_mm: float = Field(default=16.0, gt=0, le=100)
    pitch_radius_mm: float = Field(default=31.0, gt=0, le=150)
    inner_race_outer_radius_mm: float = Field(default=27.0, gt=0, le=150)
    outer_race_inner_radius_mm: float = Field(default=35.0, gt=0, le=150)
    cage_inner_radius_mm: float = Field(default=27.2, gt=0, le=150)
    cage_outer_radius_mm: float = Field(default=34.8, gt=0, le=150)
    cage_pocket_clearance_mm: float = Field(default=0.2, ge=0, le=5)
    radial_clearance_mm: float = Field(default=0.0, ge=0, le=5)
    roller_phase_deg: float = Field(default=0.0, ge=-360, le=360)
    load_direction: LoadDirection = LoadDirection.POSITIVE_X
    target_radial_load_n: float = Field(default=10.099982438539563, gt=0, le=10000)
    mesh_bulk_size_mm: float = Field(default=5.0, gt=0, le=20)
    mesh_contact_size_mm: float = Field(default=2.4, gt=0, le=10)
    solver_relative_tolerance: float = Field(default=1e-3, gt=0, le=0.1)
    provenance: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_geometry(self) -> BearingSpec:
        errors: list[str] = []
        if self.inner_diameter_mm >= self.outer_diameter_mm:
            errors.append("inner diameter must be smaller than outer diameter")
        if self.bearing_width_mm < self.roller_length_mm:
            errors.append("bearing width must be at least roller length")
        if self.inner_diameter_mm / 2 >= self.inner_race_outer_radius_mm:
            errors.append("inner ring must have positive radial thickness")
        if self.outer_race_inner_radius_mm >= self.outer_diameter_mm / 2:
            errors.append("outer ring must have positive radial thickness")
        contact_offset = self.roller_diameter_mm / 2 + self.radial_clearance_mm / 2
        expected_inner = self.pitch_radius_mm - contact_offset
        expected_outer = self.pitch_radius_mm + contact_offset
        if not math.isclose(self.inner_race_outer_radius_mm, expected_inner, abs_tol=1e-6):
            errors.append("inner race radius must match roller radius and radial clearance")
        if not math.isclose(self.outer_race_inner_radius_mm, expected_outer, abs_tol=1e-6):
            errors.append("outer race radius must match roller radius and radial clearance")
        if not (
            self.inner_race_outer_radius_mm
            < self.cage_inner_radius_mm
            < self.cage_outer_radius_mm
            < self.outer_race_inner_radius_mm
        ):
            errors.append("cage radii must lie strictly between the raceways")
        spacing = 2 * self.pitch_radius_mm * math.sin(math.pi / self.roller_count)
        pocket_diameter = self.roller_diameter_mm + 2 * self.cage_pocket_clearance_mm
        if spacing <= pocket_diameter:
            errors.append("rollers or cage pockets overlap circumferentially")
        if self.mesh_contact_size_mm > self.mesh_bulk_size_mm:
            errors.append("contact mesh size cannot exceed bulk mesh size")
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @computed_field
    @property
    def topology_signature(self) -> str:
        # Count is deliberately excluded: changing it is a deterministic topology
        # rebuild, but remains in the same supported cylindrical topology family.
        payload = {
            "family": self.family,
            "dimension": self.model_dimension,
            "contact_topology": "two_global_raceway_pairs",
            "cage": "boolean_pocket_ring",
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    @computed_field
    @property
    def build_signature(self) -> str:
        payload = self.model_dump(mode="json", exclude={"provenance", "build_signature"})
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def comsol_parameters(self) -> dict[str, str]:
        axis = (
            "x"
            if self.load_direction in {LoadDirection.POSITIVE_X, LoadDirection.NEGATIVE_X}
            else "y"
        )
        sign = (
            -1 if self.load_direction in {LoadDirection.NEGATIVE_X, LoadDirection.NEGATIVE_Y} else 1
        )
        return {
            "inner_diameter": f"{self.inner_diameter_mm:.12g}[mm]",
            "outer_diameter": f"{self.outer_diameter_mm:.12g}[mm]",
            "bearing_width": f"{self.bearing_width_mm:.12g}[mm]",
            "roller_diameter": f"{self.roller_diameter_mm:.12g}[mm]",
            "roller_length": f"{self.roller_length_mm:.12g}[mm]",
            "pitch_radius": f"{self.pitch_radius_mm:.12g}[mm]",
            "inner_race_outer_radius": f"{self.inner_race_outer_radius_mm:.12g}[mm]",
            "outer_race_inner_radius": f"{self.outer_race_inner_radius_mm:.12g}[mm]",
            "cage_inner_radius": f"{self.cage_inner_radius_mm:.12g}[mm]",
            "cage_outer_radius": f"{self.cage_outer_radius_mm:.12g}[mm]",
            "cage_pocket_clearance": f"{self.cage_pocket_clearance_mm:.12g}[mm]",
            "radial_clearance": f"{self.radial_clearance_mm:.12g}[mm]",
            "roller_angular_offset_deg": f"{self.roller_phase_deg:.12g}[deg]",
            "radial_load": f"{self.target_radial_load_n:.15g}[N]",
            "mesh_bulk_size": f"{self.mesh_bulk_size_mm:.12g}[mm]",
            "mesh_contact_size": f"{self.mesh_contact_size_mm:.12g}[mm]",
            "load_axis": axis,
            "load_sign": str(sign),
        }


class FieldChange(ContractModel):
    field: str
    before: Any
    after: Any
    change_class: ChangeClass


class BearingChangeSet(ContractModel):
    previous_signature: str
    requested_signature: str
    topology_unchanged: bool
    changes: tuple[FieldChange, ...] = ()
    route: ChangeRoute
    requires_llm: bool = False
    reason: str


_LOAD_FIELDS = frozenset({"target_radial_load_n"})
_GEOMETRY_FIELDS = frozenset(
    {
        "inner_diameter_mm",
        "outer_diameter_mm",
        "bearing_width_mm",
        "roller_diameter_mm",
        "roller_length_mm",
        "pitch_radius_mm",
        "inner_race_outer_radius_mm",
        "outer_race_inner_radius_mm",
        "cage_inner_radius_mm",
        "cage_outer_radius_mm",
        "cage_pocket_clearance_mm",
        "radial_clearance_mm",
    }
)
_SOLVER_FIELDS = frozenset(
    {"mesh_bulk_size_mm", "mesh_contact_size_mm", "solver_relative_tolerance"}
)


def _change_class(field: str) -> ChangeClass:
    if field in _LOAD_FIELDS:
        return ChangeClass.LOAD_PARAMETER
    if field in _GEOMETRY_FIELDS:
        return ChangeClass.GEOMETRY_PARAMETER
    if field == "roller_count":
        return ChangeClass.ROLLER_COUNT
    if field == "roller_phase_deg":
        return ChangeClass.PHASE_PARAMETER
    if field == "load_direction":
        return ChangeClass.DIRECTION_PARAMETER
    if field in _SOLVER_FIELDS:
        return ChangeClass.SOLVER_PARAMETER
    return ChangeClass.TOPOLOGY


def classify_changes(previous: BearingSpec, requested: BearingSpec) -> BearingChangeSet:
    ignored = {"provenance", "build_signature", "topology_signature"}
    before = previous.model_dump(mode="json", exclude=ignored)
    after = requested.model_dump(mode="json", exclude=ignored)
    changes = tuple(
        FieldChange(
            field=name, before=before[name], after=after[name], change_class=_change_class(name)
        )
        for name in sorted(before)
        if before[name] != after[name]
    )
    topology_unchanged = previous.topology_signature == requested.topology_signature
    classes = {change.change_class for change in changes}
    if not changes:
        route, reason = ChangeRoute.NOOP, "specification is unchanged"
    elif not topology_unchanged or ChangeClass.TOPOLOGY in classes:
        route, reason = (
            ChangeRoute.UNSUPPORTED_TOPOLOGY,
            "request changes an unsupported topology contract",
        )
    elif classes & {
        ChangeClass.ROLLER_COUNT,
        ChangeClass.GEOMETRY_PARAMETER,
        ChangeClass.PHASE_PARAMETER,
    }:
        route, reason = (
            ChangeRoute.DETERMINISTIC_REBUILD,
            "geometry, repeated entities, or phase-dependent selections require "
            "the registered deterministic builder",
        )
    else:
        route, reason = (
            ChangeRoute.PARAMETER_OVERRIDE,
            "supported same-topology fields map to typed COMSOL parameters",
        )
    return BearingChangeSet(
        previous_signature=previous.build_signature,
        requested_signature=requested.build_signature,
        topology_unchanged=topology_unchanged,
        changes=changes,
        route=route,
        requires_llm=False,
        reason=reason,
    )

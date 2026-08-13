# ruff: noqa: E501
"""Typed bearing-domain parameters, units, provenance, and feasibility gates.

The objects in this module are deliberately independent from COMSOL.  A
topology builder receives a validated :class:`BearingModelInput`; it must not
guess dimensions from a generic dictionary while constructing geometry.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar


class BearingParameterError(ValueError):
    """Raised when a bearing request is incomplete or geometrically impossible."""


_UNITS: dict[str, tuple[str, float, str]] = {
    "m": ("length", 1.0, "m"),
    "mm": ("length", 1e-3, "mm"),
    "um": ("length", 1e-6, "um"),
    "µm": ("length", 1e-6, "um"),
    "rad": ("angle", 1.0, "rad"),
    "deg": ("angle", math.pi / 180.0, "deg"),
    "n": ("force", 1.0, "N"),
    "kn": ("force", 1e3, "kN"),
    "n*m": ("moment", 1.0, "N*m"),
    "nm": ("moment", 1.0, "N*m"),
    "pa": ("pressure", 1.0, "Pa"),
    "mpa": ("pressure", 1e6, "MPa"),
    "gpa": ("pressure", 1e9, "GPa"),
    "kg/m^3": ("density", 1.0, "kg/m^3"),
    "1": ("dimensionless", 1.0, "1"),
}


@dataclass(frozen=True)
class ParameterValue:
    """A normalized scalar plus its source and original representation."""

    name: str
    value_si: float
    dimension: str
    unit: str
    original: str
    source: str

    def comsol(self) -> str:
        if self.dimension == "dimensionless":
            return f"{self.value_si:.12g}"
        return f"{self.value_si:.12g}[{_si_unit(self.dimension)}]"

    def in_unit(self, unit: str) -> float:
        dimension, factor, _ = _unit_definition(unit)
        if dimension != self.dimension:
            raise BearingParameterError(
                f"{self.name}: cannot convert {self.dimension} to {dimension} ({unit})."
            )
        return self.value_si / factor


def parse_parameter(
    name: str,
    raw: Any,
    *,
    dimension: str,
    source: str,
    default_unit: str | None = None,
) -> ParameterValue:
    """Parse one scalar and reject ambiguous bare dimensional values."""
    if isinstance(raw, bool):
        raise BearingParameterError(f"{name}: boolean is not a numeric parameter.")
    text = str(raw).strip().replace("μ", "µ")
    match = re.fullmatch(
        r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(?:\[\s*([^\]]+)\s*\]|([^\s]+))?",
        text,
    )
    if not match:
        raise BearingParameterError(
            f"{name}: expected a scalar with units, got {raw!r}; example: 25[mm]."
        )
    number = float(match.group(1))
    unit = (match.group(2) or match.group(3) or default_unit or "").strip()
    if not unit:
        if dimension != "dimensionless":
            raise BearingParameterError(f"{name}: a {dimension} unit is required.")
        unit = "1"
    parsed_dimension, factor, canonical = _unit_definition(unit)
    if parsed_dimension != dimension:
        raise BearingParameterError(
            f"{name}: expected {dimension}, received {parsed_dimension} unit {unit!r}."
        )
    if not math.isfinite(number):
        raise BearingParameterError(f"{name}: value must be finite.")
    return ParameterValue(name, number * factor, dimension, canonical, text, source)


def _unit_definition(unit: str) -> tuple[str, float, str]:
    normalized = re.sub(r"\s+", "", unit).lower()
    if normalized not in _UNITS:
        raise BearingParameterError(f"Unsupported unit {unit!r}.")
    return _UNITS[normalized]


def _si_unit(dimension: str) -> str:
    return {
        "length": "m",
        "angle": "rad",
        "force": "N",
        "moment": "N*m",
        "pressure": "Pa",
        "density": "kg/m^3",
    }[dimension]


@dataclass(frozen=True)
class MaterialParameters:
    name: str
    youngs_modulus: ParameterValue
    poisson_ratio: ParameterValue
    density: ParameterValue


@dataclass(frozen=True)
class LoadCase:
    radial_x: ParameterValue
    radial_y: ParameterValue
    axial: ParameterValue
    moment_x: ParameterValue
    moment_y: ParameterValue

    @property
    def mode(self) -> str:
        radial = math.hypot(self.radial_x.value_si, self.radial_y.value_si) > 0
        axial = abs(self.axial.value_si) > 0
        if radial and axial:
            return "combined_radial_axial"
        if axial:
            return "axial"
        if radial:
            return "radial"
        return "unloaded"


@dataclass(frozen=True)
class CommonBearingParameters:
    inner_diameter: ParameterValue
    outer_diameter: ParameterValue
    bearing_width: ParameterValue
    rolling_element_count: int
    pitch_diameter: ParameterValue
    radial_clearance: ParameterValue
    axial_clearance: ParameterValue
    friction_coefficient: ParameterValue
    mesh_bulk_size: ParameterValue
    mesh_contact_size: ParameterValue
    load_steps: int
    solver_relative_tolerance: float
    material: MaterialParameters


@dataclass(frozen=True)
class TaperedRollerParameters:
    roller_large_diameter: ParameterValue
    roller_small_diameter: ParameterValue
    roller_length: ParameterValue
    roller_cone_angle: ParameterValue
    inner_raceway_angle: ParameterValue
    outer_raceway_angle: ParameterValue
    contact_angle: ParameterValue
    flange_height: ParameterValue
    flange_thickness: ParameterValue
    initial_interference: ParameterValue


@dataclass(frozen=True)
class AngularContactBallParameters:
    ball_diameter: ParameterValue
    inner_groove_curvature: float
    outer_groove_curvature: float
    contact_angle: ParameterValue
    rows: int
    preload_direction: str


@dataclass(frozen=True)
class NeedleRollerParameters:
    needle_diameter: ParameterValue
    needle_length: ParameterValue
    end_crowning: ParameterValue
    cage_mode: str

    @property
    def aspect_ratio(self) -> float:
        return self.needle_length.value_si / self.needle_diameter.value_si


@dataclass(frozen=True)
class ThrustBearingParameters:
    rolling_element_form: str
    rolling_element_diameter: ParameterValue
    washer_thickness: ParameterValue
    axial_load_face: str


@dataclass(frozen=True)
class SphericalRollerParameters:
    roller_length: ParameterValue
    roller_max_diameter: ParameterValue
    roller_profile_radius: ParameterValue
    spherical_raceway_radius: ParameterValue
    rows: int
    self_alignment_angle: ParameterValue


FamilyParameters = (
    TaperedRollerParameters
    | AngularContactBallParameters
    | NeedleRollerParameters
    | ThrustBearingParameters
    | SphericalRollerParameters
)


@dataclass(frozen=True)
class BearingModelInput:
    family: str
    common: CommonBearingParameters
    family_parameters: FamilyParameters
    load: LoadCase
    assumptions: tuple[str, ...] = ()
    parameter_sources: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    FAMILY_BUILDERS: ClassVar[dict[str, str]] = {
        "tapered_roller": "tapered_roller",
        "angular_contact_ball": "angular_contact_ball",
        "needle_roller": "needle_roller",
        "thrust_bearing": "thrust_bearing",
        "spherical_roller": "spherical_roller",
    }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_COMMON_DEFAULTS: dict[str, Any] = {
    "inner_diameter": "40[mm]",
    "outer_diameter": "80[mm]",
    "bearing_width": "18[mm]",
    "rolling_element_count": 12,
    "pitch_diameter": "62[mm]",
    "radial_clearance": "0[um]",
    "axial_clearance": "20[um]",
    "friction_coefficient": 0.05,
    "mesh_bulk_size": "3[mm]",
    "mesh_contact_size": "0.8[mm]",
    "load_steps": 8,
    "solver_relative_tolerance": 1e-3,
    "youngs_modulus": "210[GPa]",
    "poisson_ratio": 0.30,
    "density": "7850[kg/m^3]",
    "radial_load_x": "0[N]",
    "radial_load_y": "-1000[N]",
    "axial_load": "0[N]",
    "moment_x": "0[N*m]",
    "moment_y": "0[N*m]",
}

_FAMILY_DEFAULTS: dict[str, dict[str, Any]] = {
    "tapered_roller": {
        "roller_large_diameter": "10[mm]",
        "roller_small_diameter": "7[mm]",
        "roller_length": "16[mm]",
        "roller_cone_angle": "5.3558[deg]",
        "inner_raceway_angle": "22.7116[deg]",
        "outer_raceway_angle": "12[deg]",
        "contact_angle": "17.3558[deg]",
        "flange_height": "2[mm]",
        "flange_thickness": "2[mm]",
        "initial_interference": "0[um]",
    },
    "angular_contact_ball": {
        "ball_diameter": "9[mm]",
        "inner_groove_curvature": 0.52,
        "outer_groove_curvature": 0.54,
        "contact_angle": "25[deg]",
        "rows": 1,
        "preload_direction": "positive_axial",
    },
    "needle_roller": {
        "needle_diameter": "3[mm]",
        "needle_length": "15[mm]",
        "end_crowning": "20[um]",
        "cage_mode": "caged",
    },
    "thrust_bearing": {
        "rolling_element_form": "ball",
        "rolling_element_diameter": "9[mm]",
        "washer_thickness": "5[mm]",
        "axial_load_face": "shaft_washer",
        "radial_load_y": "0[N]",
        "axial_load": "-1000[N]",
    },
    "spherical_roller": {
        "roller_length": "16[mm]",
        "roller_max_diameter": "9[mm]",
        "roller_profile_radius": "24[mm]",
        "spherical_raceway_radius": "34[mm]",
        "rows": 2,
        "self_alignment_angle": "2[deg]",
    },
}


def build_bearing_model_input(
    family: str,
    params: dict[str, Any],
    *,
    allow_defaults: bool = False,
) -> BearingModelInput:
    """Resolve a typed request and run family-specific feasibility checks."""
    if family not in BearingModelInput.FAMILY_BUILDERS:
        raise BearingParameterError(
            f"No typed topology parameter model for bearing family {family!r}."
        )
    supplied = {str(key).strip(): value for key, value in params.items() if value not in (None, "")}
    defaults = {**_COMMON_DEFAULTS, **_FAMILY_DEFAULTS[family]}
    required = _required_parameters(family)
    missing = [name for name in required if name not in supplied]
    if missing and not allow_defaults:
        raise BearingParameterError(
            f"{family}: missing required topology parameters: {', '.join(missing)}."
        )
    resolved = {**defaults, **supplied} if allow_defaults else supplied
    sources = {name: ("user" if name in supplied else "family_default") for name in resolved}
    assumptions = tuple(
        f"{name}={defaults[name]} selected from {family} engineering defaults"
        for name in resolved
        if name not in supplied
    )
    common = _build_common(resolved, sources)
    load = _build_load(resolved, sources)
    specific = _build_family(family, resolved, sources)
    warnings = tuple(_validate_feasibility(family, common, specific, load))
    return BearingModelInput(family, common, specific, load, assumptions, sources, warnings)


def _required_parameters(family: str) -> tuple[str, ...]:
    shared = (
        "inner_diameter",
        "outer_diameter",
        "bearing_width",
        "rolling_element_count",
        "pitch_diameter",
    )
    family_required = {
        "tapered_roller": (
            "roller_large_diameter",
            "roller_small_diameter",
            "roller_length",
            "roller_cone_angle",
            "inner_raceway_angle",
            "outer_raceway_angle",
            "contact_angle",
        ),
        "angular_contact_ball": ("ball_diameter", "contact_angle", "rows", "preload_direction"),
        "needle_roller": ("needle_diameter", "needle_length", "cage_mode"),
        "thrust_bearing": ("rolling_element_form", "rolling_element_diameter", "axial_load_face"),
        "spherical_roller": (
            "roller_length",
            "roller_max_diameter",
            "roller_profile_radius",
            "spherical_raceway_radius",
            "rows",
            "self_alignment_angle",
        ),
    }
    return shared + family_required[family]


def _q(
    resolved: dict[str, Any], sources: dict[str, str], name: str, dimension: str
) -> ParameterValue:
    return parse_parameter(name, resolved[name], dimension=dimension, source=sources[name])


def _build_common(resolved: dict[str, Any], sources: dict[str, str]) -> CommonBearingParameters:
    material = MaterialParameters(
        str(resolved.get("material", "bearing_steel")),
        _q(resolved, sources, "youngs_modulus", "pressure"),
        _q(resolved, sources, "poisson_ratio", "dimensionless"),
        _q(resolved, sources, "density", "density"),
    )
    return CommonBearingParameters(
        _q(resolved, sources, "inner_diameter", "length"),
        _q(resolved, sources, "outer_diameter", "length"),
        _q(resolved, sources, "bearing_width", "length"),
        _positive_int("rolling_element_count", resolved["rolling_element_count"]),
        _q(resolved, sources, "pitch_diameter", "length"),
        _q(resolved, sources, "radial_clearance", "length"),
        _q(resolved, sources, "axial_clearance", "length"),
        _q(resolved, sources, "friction_coefficient", "dimensionless"),
        _q(resolved, sources, "mesh_bulk_size", "length"),
        _q(resolved, sources, "mesh_contact_size", "length"),
        _positive_int("load_steps", resolved["load_steps"]),
        float(resolved["solver_relative_tolerance"]),
        material,
    )


def _build_load(resolved: dict[str, Any], sources: dict[str, str]) -> LoadCase:
    return LoadCase(
        _q(resolved, sources, "radial_load_x", "force"),
        _q(resolved, sources, "radial_load_y", "force"),
        _q(resolved, sources, "axial_load", "force"),
        _q(resolved, sources, "moment_x", "moment"),
        _q(resolved, sources, "moment_y", "moment"),
    )


def _build_family(family: str, p: dict[str, Any], s: dict[str, str]) -> FamilyParameters:
    if family == "tapered_roller":
        return TaperedRollerParameters(
            _q(p, s, "roller_large_diameter", "length"),
            _q(p, s, "roller_small_diameter", "length"),
            _q(p, s, "roller_length", "length"),
            _q(p, s, "roller_cone_angle", "angle"),
            _q(p, s, "inner_raceway_angle", "angle"),
            _q(p, s, "outer_raceway_angle", "angle"),
            _q(p, s, "contact_angle", "angle"),
            _q(p, s, "flange_height", "length"),
            _q(p, s, "flange_thickness", "length"),
            _q(p, s, "initial_interference", "length"),
        )
    if family == "angular_contact_ball":
        return AngularContactBallParameters(
            _q(p, s, "ball_diameter", "length"),
            float(p["inner_groove_curvature"]),
            float(p["outer_groove_curvature"]),
            _q(p, s, "contact_angle", "angle"),
            _positive_int("rows", p["rows"]),
            str(p["preload_direction"]),
        )
    if family == "needle_roller":
        return NeedleRollerParameters(
            _q(p, s, "needle_diameter", "length"),
            _q(p, s, "needle_length", "length"),
            _q(p, s, "end_crowning", "length"),
            str(p["cage_mode"]),
        )
    if family == "thrust_bearing":
        return ThrustBearingParameters(
            str(p["rolling_element_form"]),
            _q(p, s, "rolling_element_diameter", "length"),
            _q(p, s, "washer_thickness", "length"),
            str(p["axial_load_face"]),
        )
    return SphericalRollerParameters(
        _q(p, s, "roller_length", "length"),
        _q(p, s, "roller_max_diameter", "length"),
        _q(p, s, "roller_profile_radius", "length"),
        _q(p, s, "spherical_raceway_radius", "length"),
        _positive_int("rows", p["rows"]),
        _q(p, s, "self_alignment_angle", "angle"),
    )


def _positive_int(name: str, raw: Any) -> int:
    value = int(raw)
    if value <= 0 or str(value) != str(raw).strip().split(".")[0]:
        raise BearingParameterError(f"{name}: expected a positive integer, got {raw!r}.")
    return value


def _validate_feasibility(
    family: str,
    common: CommonBearingParameters,
    specific: FamilyParameters,
    load: LoadCase,
) -> list[str]:
    inner = common.inner_diameter.value_si
    outer = common.outer_diameter.value_si
    pitch = common.pitch_diameter.value_si
    width = common.bearing_width.value_si
    if not 0 < inner < pitch < outer:
        raise BearingParameterError(
            "Geometry invariant failed: inner_diameter < pitch_diameter < outer_diameter is required."
        )
    if width <= 0 or common.mesh_contact_size.value_si >= common.mesh_bulk_size.value_si:
        raise BearingParameterError(
            "Geometry/mesh invariant failed: width must be positive and contact mesh must be finer than bulk mesh."
        )
    if not 0 <= common.friction_coefficient.value_si <= 1:
        raise BearingParameterError("friction_coefficient must be between 0 and 1.")
    warnings: list[str] = []
    radial_envelope = min(pitch - inner, outer - pitch)
    if family == "tapered_roller":
        assert isinstance(specific, TaperedRollerParameters)
        large = specific.roller_large_diameter.value_si
        small = specific.roller_small_diameter.value_si
        length = specific.roller_length.value_si
        if not 0 < small < large < radial_envelope:
            raise BearingParameterError(
                "Tapered roller invariant failed: 0 < small end < large end < available radial envelope."
            )
        if length > width:
            raise BearingParameterError("Tapered roller length exceeds bearing width.")
        if not 0 <= specific.initial_interference.value_si <= 10e-6:
            raise BearingParameterError(
                "Tapered initial_interference must be between 0 and 10 um."
            )
        geometric_angle = math.atan2((large - small) / 2.0, length)
        if abs(geometric_angle - specific.roller_cone_angle.value_si) > math.radians(0.25):
            raise BearingParameterError(
                "roller_cone_angle is inconsistent with large/small diameters and roller_length (>0.25 deg)."
            )
        if not (
            0
            < specific.outer_raceway_angle.value_si
            < specific.inner_raceway_angle.value_si
            < math.radians(45)
        ):
            raise BearingParameterError(
                "Tapered raceway invariant failed: 0 < outer_raceway_angle < inner_raceway_angle < 45 deg."
            )
        axis_from_raceways = (
            specific.inner_raceway_angle.value_si
            + specific.outer_raceway_angle.value_si
        ) / 2
        half_included_angle = (
            specific.inner_raceway_angle.value_si
            - specific.outer_raceway_angle.value_si
        ) / 2
        if abs(axis_from_raceways - specific.contact_angle.value_si) > math.radians(0.25):
            raise BearingParameterError(
                "contact_angle must equal the mean inner/outer raceway angle within 0.25 deg."
            )
        if abs(half_included_angle - specific.roller_cone_angle.value_si) > math.radians(
            0.25
        ):
            raise BearingParameterError(
                "roller_cone_angle must equal half the inner/outer raceway angle difference within 0.25 deg."
            )
    elif family == "angular_contact_ball":
        assert isinstance(specific, AngularContactBallParameters)
        if specific.rows not in {1, 2}:
            raise BearingParameterError("Angular-contact rows must be 1 or 2.")
        if not math.radians(5) <= specific.contact_angle.value_si <= math.radians(45):
            raise BearingParameterError("Angular-contact angle must be between 5 and 45 deg.")
        if (
            not 0.5 <= specific.inner_groove_curvature <= 0.65
            or not 0.5 <= specific.outer_groove_curvature <= 0.65
        ):
            raise BearingParameterError("Groove curvature ratios must be in [0.50, 0.65].")
    elif family == "needle_roller":
        assert isinstance(specific, NeedleRollerParameters)
        if specific.aspect_ratio < 4:
            raise BearingParameterError("Needle roller length/diameter ratio must be at least 4.")
        if specific.needle_length.value_si > width:
            raise BearingParameterError("Needle length exceeds bearing width.")
    elif family == "thrust_bearing":
        assert isinstance(specific, ThrustBearingParameters)
        if load.mode not in {"axial", "combined_radial_axial"}:
            raise BearingParameterError("Thrust bearing requires a non-zero axial load.")
        if specific.rolling_element_form not in {"ball", "cylindrical_roller", "tapered_roller"}:
            raise BearingParameterError("Unsupported thrust rolling_element_form.")
    else:
        assert isinstance(specific, SphericalRollerParameters)
        if specific.rows != 2:
            raise BearingParameterError(
                "Spherical roller topology currently requires a double-row layout."
            )
        if specific.spherical_raceway_radius.value_si <= pitch / 2:
            raise BearingParameterError("Spherical raceway radius must exceed pitch radius.")
    if load.mode == "unloaded":
        warnings.append(
            "No external load is defined; geometry-only generation is allowed but solve verification is not."
        )
    return warnings

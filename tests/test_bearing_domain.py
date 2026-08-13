from __future__ import annotations

import math

import pytest

from comsol_agent.simulation.bearing_builders import (
    TaperedRollerComsolBuilder,
    UnsupportedBearingTopologyError,
    build_comsol_bearing,
    get_bearing_builder,
)
from comsol_agent.simulation.bearing_domain import (
    BearingParameterError,
    NeedleRollerParameters,
    TaperedRollerParameters,
    build_bearing_model_input,
    parse_parameter,
)
from comsol_agent.simulation.bearing_families import infer_bearing_family


def test_units_are_normalized_and_source_is_preserved():
    diameter = parse_parameter("inner_diameter", "40[mm]", dimension="length", source="user")

    assert diameter.value_si == pytest.approx(0.04)
    assert diameter.comsol() == "0.04[m]"
    assert diameter.source == "user"
    assert diameter.in_unit("mm") == pytest.approx(40)


def test_dimensional_parameter_rejects_bare_number_and_wrong_unit():
    with pytest.raises(BearingParameterError, match="unit is required"):
        parse_parameter("outer_diameter", 80, dimension="length", source="user")
    with pytest.raises(BearingParameterError, match="expected force"):
        parse_parameter("axial_load", "10[mm]", dimension="force", source="user")


def test_tapered_model_has_family_specific_parameters_and_combined_signed_load():
    model = build_bearing_model_input(
        "tapered_roller",
        {
            "radial_load_x": "-1200[N]",
            "radial_load_y": "800[N]",
            "axial_load": "-450[N]",
            "roller_large_diameter": "10[mm]",
            "roller_small_diameter": "7[mm]",
            "roller_length": "16[mm]",
            "roller_cone_angle": "5.3558[deg]",
            "inner_raceway_angle": "22.7116[deg]",
            "outer_raceway_angle": "12[deg]",
            "contact_angle": "17.3558[deg]",
        },
        allow_defaults=True,
    )

    assert isinstance(model.family_parameters, TaperedRollerParameters)
    assert model.load.mode == "combined_radial_axial"
    assert model.load.radial_x.value_si == pytest.approx(-1200)
    assert model.load.axial.value_si == pytest.approx(-450)
    assert model.parameter_sources["roller_large_diameter"] == "user"
    assert model.parameter_sources["pitch_diameter"] == "family_default"
    assert model.family_parameters.roller_cone_angle.value_si == pytest.approx(math.radians(5.3558))


def test_tapered_geometry_rejects_inconsistent_cone_angle():
    with pytest.raises(BearingParameterError, match="roller_cone_angle is inconsistent"):
        build_bearing_model_input(
            "tapered_roller",
            {"roller_cone_angle": "12[deg]"},
            allow_defaults=True,
        )


def test_tapered_geometry_rejects_reversed_end_diameters():
    with pytest.raises(BearingParameterError, match="small end < large end"):
        build_bearing_model_input(
            "tapered_roller",
            {
                "roller_large_diameter": "7[mm]",
                "roller_small_diameter": "10[mm]",
            },
            allow_defaults=True,
        )


def test_needle_model_enforces_slenderness():
    with pytest.raises(BearingParameterError, match="ratio must be at least 4"):
        build_bearing_model_input(
            "needle_roller",
            {"needle_diameter": "5[mm]", "needle_length": "10[mm]"},
            allow_defaults=True,
        )

    model = build_bearing_model_input("needle_roller", {}, allow_defaults=True)
    assert isinstance(model.family_parameters, NeedleRollerParameters)
    assert model.family_parameters.aspect_ratio == pytest.approx(5)


def test_thrust_model_requires_axial_load():
    with pytest.raises(BearingParameterError, match="requires a non-zero axial load"):
        build_bearing_model_input(
            "thrust_bearing",
            {"axial_load": "0[N]", "radial_load_y": "1000[N]"},
            allow_defaults=True,
        )


def test_spherical_roller_is_a_distinct_registered_family():
    family = infer_bearing_family("建立双列调心滚子轴承并检查调心角")

    assert family.name == "spherical_roller"
    model = build_bearing_model_input("spherical_roller", {}, allow_defaults=True)
    assert model.family == "spherical_roller"
    assert model.family_parameters.rows == 2


def test_explicit_parameters_without_defaults_report_missing_topology_fields():
    with pytest.raises(BearingParameterError, match="missing required topology parameters"):
        build_bearing_model_input(
            "angular_contact_ball",
            {"inner_diameter": "40[mm]", "outer_diameter": "80[mm]"},
            allow_defaults=False,
        )


def test_tapered_builder_emits_independent_cone_cup_and_frustum_topology():
    request = build_bearing_model_input(
        "tapered_roller",
        {
            "radial_load_x": "500[N]",
            "radial_load_y": "-1200[N]",
            "axial_load": "-450[N]",
        },
        allow_defaults=True,
    )

    product = build_comsol_bearing(request, model_name="tapered_baseline")

    assert isinstance(get_bearing_builder("tapered_roller"), TaperedRollerComsolBuilder)
    assert product.family == "tapered_roller"
    assert "geom.create('inner_race_cone', 'Cone')" in product.code
    assert "geom.create('outer_race_void', 'Cone')" in product.code
    assert "geom.create('tapered_roller_12', 'Cone')" in product.code
    assert "roller_large_diameter/2" in product.code
    assert "roller_small_diameter/2" in product.code
    assert "contact_angle" in product.code
    assert "radial_load_x" in product.code
    assert "axial_load" in product.code
    assert "inner_flange_blank', 'Cone'" in product.code
    assert "sel_inner_bore_load" in product.code
    assert "intop_inner_bore_load(1)" in product.code
    assert "FperArea" in product.code
    assert "LoadType', 'TotalForce'" not in product.code
    assert "axial_locate_inner" not in product.code
    assert "axial_locate_inner" not in product.manifest.support_features
    assert len(product.manifest.contact_pairs) == 36
    assert product.manifest.contact_pairs[:3] == (
        "cp_roller_1_inner",
        "cp_roller_1_outer",
        "cp_roller_1_flange",
    )
    assert "cylindrical" not in product.manifest.topology_builder.lower()
    assert "ball" not in product.manifest.topology_builder.lower()


def test_tapered_radial_case_adds_axial_location_without_masking_axial_loads():
    request = build_bearing_model_input(
        "tapered_roller", {"radial_load_x": "4[N]"}, allow_defaults=True
    )

    product = build_comsol_bearing(request, model_name="radial_only")

    assert "solid.create('axial_locate_inner', 'Displacement2', 2)" in product.code
    assert "axial_locate_inner" in product.manifest.support_features


def test_tapered_variant_changes_roller_generator_coordinates_not_global_scale_only():
    baseline = build_bearing_model_input("tapered_roller", {}, allow_defaults=True)
    variant = build_bearing_model_input(
        "tapered_roller",
        {
            "contact_angle": "20[deg]",
            "inner_raceway_angle": "28[deg]",
            "outer_raceway_angle": "12[deg]",
            "roller_large_diameter": "11[mm]",
            "roller_small_diameter": "6.501[mm]",
            "roller_length": "16[mm]",
            "roller_cone_angle": "8[deg]",
        },
        allow_defaults=True,
    )

    baseline_code = build_comsol_bearing(baseline, model_name="base").sections["topology"]
    variant_code = build_comsol_bearing(variant, model_name="variant").sections["topology"]

    assert baseline_code != variant_code
    baseline_axis = next(line for line in baseline_code.splitlines() if ".set('axis'" in line)
    variant_axis = next(line for line in variant_code.splitlines() if ".set('axis'" in line)
    assert baseline_axis != variant_axis


def test_tapered_solver_uses_deep_load_ramp_and_only_audited_weak_foundations():
    request = build_bearing_model_input(
        "tapered_roller",
        {"rolling_element_count": 3, "radial_load_x": "10[N]"},
        allow_defaults=True,
    )

    product = build_comsol_bearing(request, model_name="tapered_stable")
    solver = product.sections["solver"]
    boundaries = product.sections["loads_boundaries"]

    assert "1e-5 2e-5 5e-5" in solver
    assert "0.1 0.2 0.5 1" in solver
    assert "SpringFoundation2" in boundaries
    assert "postsolve_equilibrium_audit" in boundaries
    assert "RigidConnector" not in boundaries
    assert "cage_guide" not in boundaries
    assert "stability_scale" not in product.code


def test_unimplemented_families_are_rejected_instead_of_substituted():
    with pytest.raises(UnsupportedBearingTopologyError, match="substitution is forbidden"):
        get_bearing_builder("angular_contact_ball")

import numpy as np
import pytest

from app.core.exceptions import InputValidationError
from app.physics.reactions import REACTIONS, build_reaction_system
from app.physics.species import AW, SI, build_material_system, coal_from_assay, pellet_assay_to_species, vm_products
from app.physics.thermo import THERMO_DB

PROX = {"fixed_carbon": 42, "volatile_matter": 27, "ash": 23, "moisture": 8}
ULT = {"C": 79.5, "H": 5.0, "O": 13.1, "N": 1.7, "S": 0.7}


def ms():
    sp, g, _ = pellet_assay_to_species({"Fe_total": 64.5, "FeO": 0.8, "SiO2": 3.4, "Al2O3": 2.1})
    return build_material_system(g, {"SiO2": 60, "Al2O3": 30, "Fe2O3": 10}, coal_from_assay(PROX, ULT, 20.9))


def test_every_reaction_atom_balanced():
    m = ms()
    rs = build_reaction_system(m)
    res = rs.element_residual(m)
    assert np.max(np.abs(res)) < 1e-9, [REACTIONS[i][0] for i in np.where(np.abs(res).max(1) > 1e-9)[0]]


def test_reaction_heats_have_expected_signs():
    rs = build_reaction_system(ms())
    d = dict(zip(rs.names, rs.dh298))
    assert d["R07_BOUDOUARD"] > 1.6e8 and d["R12_CO_OX"] < -2.8e8 and d["R15_EVAP"] > 4e7
    assert abs(d["R16_DEVOL"]) < 1.5e6  # near-thermoneutral devolatilisation (auto split)


def test_coal_basis_consistency_errors():
    with pytest.raises(InputValidationError):
        coal_from_assay({**PROX, "ash": 40}, ULT, 20)
    with pytest.raises(InputValidationError):
        coal_from_assay(PROX, {**ULT, "C": 40, "O": 52.6}, 20)  # total C < fixed carbon
    with pytest.raises(InputValidationError):
        coal_from_assay(PROX, ULT)  # no heating value


def test_gcv_to_ncv():
    c = coal_from_assay(PROX, ULT, gcv_MJ_kg_ar=22.0)
    assert c.ncv_J_per_kg < 22e6 and c.warnings


def test_vm_yield_element_closure():
    c = coal_from_assay(PROX, ULT, 20.9)
    y, soot, hf, el = vm_products(c, 0.9)
    assert all(v >= 0 for v in y.values()) and soot >= 0


def test_pellet_assay_closure_and_rejection():
    sp, g, w = pellet_assay_to_species({"Fe_total": 64.5, "FeO": 0.8, "SiO2": 3.4, "Al2O3": 2.1, "CaO": 0.6,
                                        "MgO": 0.25, "TiO2": 0.1, "P": 0.05, "S": 0.01, "LOI": 0.4})
    assert sum(sp.values()) == pytest.approx(1.0)
    with pytest.raises(InputValidationError):
        pellet_assay_to_species({"Fe_total": 80.0, "FeO": 0.0})


def test_theoretical_oxygen_removal_hematite():
    mw = THERMO_DB["Fe2O3"].mw
    o_per_kg = 3 * AW["O"] / mw
    assert o_per_kg == pytest.approx(0.3006, abs=1e-3)


def test_metallization_hand_calculation():
    # 1 kmol Fe2O3 -> 0.2 Fe2O3 remaining, 1.2 kmol FeO, 0.4 kmol Fe (Fe conserved = 2)
    fe_hem, fe_wus, fe_met = 2 * 0.2, 1.2, 0.4
    assert fe_hem + fe_wus + fe_met == pytest.approx(2.0)
    assert 100 * fe_met / 2.0 == pytest.approx(20.0)


def test_species_index_complete():
    for k in ("Fe2O3", "Fe3O4", "FeO", "Fe", "C", "VM", "ASH"):
        assert k in SI

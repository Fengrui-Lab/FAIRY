"""ORACLE auditor: claims cannot exceed completed candidate evidence."""

import ast
import pytest


def rows():
    return [
        dict(
            candidate_id="a",
            input_fingerprint="same",
            feasible=True,
            root_yield=100,
            wheat_yield=40,
            net_operating_margin=50,
        ),
        dict(
            candidate_id="b",
            input_fingerprint="same",
            feasible=True,
            root_yield=90,
            wheat_yield=45,
            net_operating_margin=60,
        ),
    ]


def test_yield_and_margin_are_distinct(C):
    a = C.select_candidates(rows(), ["a", "b"], "root_yield")
    b = C.select_candidates(rows(), ["a", "b"], "net_operating_margin")
    assert a["best"]["candidate_id"] == "a" and b["best"]["candidate_id"] == "b"
    assert (
        a["status"] == "best_in_declared_finite_grid" and not a["global_optimum_proven"]
    )
    assert set(a["pareto_candidate_ids"]) == {"a", "b"}


def test_rotation_does_not_add_incommensurable_products(C):
    r = rows()
    r[1]["wheat_yield"] = 10000
    assert (
        C.select_candidates(r, ["a", "b"], "rotation_yield")["best"]["candidate_id"]
        == "a"
    )


def test_incomplete_grid_not_optimal(C):
    r = C.select_candidates(rows()[:1], ["a", "b"], "root_yield")
    assert r["status"] == "best_tested_only" and not r["complete"]


def test_runtime_error_not_proof_of_infeasibility(C):
    r = rows()
    r[1].update(feasible=False, execution_status="runtime_error")
    a = C.select_candidates(r, ["a", "b"], "root_yield")
    assert not a["complete"] and a["status"] == "best_tested_only"


def test_inputs_must_be_identical(C):
    r = rows()
    r[1]["input_fingerprint"] = "changed soil or prices"
    with pytest.raises(ValueError):
        C.select_candidates(r, ["a", "b"], "root_yield")


@pytest.mark.parametrize("mutation", ["duplicate", "undeclared", "nan", "negative"])
def test_invalid_search_results_rejected(C, mutation):
    r = rows()
    if mutation == "duplicate":
        r.append(r[0])
    if mutation == "undeclared":
        r[0]["candidate_id"] = "x"
    if mutation == "nan":
        r[0]["root_yield"] = float("nan")
    if mutation == "negative":
        r[0]["wheat_yield"] = -1
    with pytest.raises(ValueError):
        C.select_candidates(r, ["a", "b"], "root_yield")


def test_no_runs_and_no_feasible(C):
    assert C.select_candidates([], ["a"], "root_yield")["status"] == "not_run"
    r = rows()
    r[0]["feasible"] = r[1]["feasible"] = False
    assert C.select_candidates(r, ["a", "b"], "root_yield")["best"] is None


def test_policy_controller_has_no_private_engine_access():
    from conftest import EXT

    tree = ast.parse((EXT / "sugarbeet/oracle.py").read_text())
    cls = next(
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "PublicController"
    )
    forbidden = {
        "backends",
        "model",
        "native",
        "_ridges",
        "set_variable",
        "_send_signal",
        "harvest_now",
        "queue",
    }
    assert (
        not {n.attr for n in ast.walk(cls) if isinstance(n, ast.Attribute)} & forbidden
    )


def test_grid_unique_and_agronomic_axes():
    from conftest import load, EXT

    module = load("isolated_beet_review.oracle", EXT / "sugarbeet/oracle.py")
    assert len(module.policy_grid(False)) == 24
    assert len(module.policy_grid(True)) == 48
    assert len({p.candidate_id for p in module.policy_grid(True)}) == 48
    assert all(
        p.beet_n_kg_ha <= 180 and p.beet_harvest_offset_days >= 0
        for p in module.policy_grid(True)
    )

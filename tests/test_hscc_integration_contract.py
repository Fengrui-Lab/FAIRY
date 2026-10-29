from types import SimpleNamespace
from fairy.agents.jev.menu import build_arg_menu
from fairy.contracts.cli import fingerprint


def test_optional_fertilizer_default_is_preserved_in_menu():
    tool=SimpleNamespace(class_name='TractorApp',name='base_fertilize')
    arg=SimpleNamespace(name='total_kg',arg_type='float | None',has_default=True,default=None)
    menu=build_arg_menu(tool,arg,descriptions={},numbers=[200],num_ridges=64)
    assert menu.options['default (null)'] is None
    assert 200.0 in menu.options.values()


def test_wofost_data_are_part_of_runtime_identity():
    ident=fingerprint()
    assert any(p.startswith('fairy/physics/data/wofost/') and p.endswith('.json') for p in ident['files'])
    assert any(p.endswith('.gz') and p.startswith('fairy/scenarios/') for p in ident['files'])
    assert any(p.endswith('.conf') and p.startswith('fairy/physics/data/') for p in ident['files'])
    assert ident['dependencies']['pcse']

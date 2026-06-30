def after_observation(*args, **kwargs):
    return True


def after_any_of(*args, **kwargs):
    return True


def and_(*predicates):
    return lambda *args, **kwargs: all(
        predicate(*args, **kwargs) if callable(predicate) else bool(predicate)
        for predicate in predicates
    )


def or_(*predicates):
    return lambda *args, **kwargs: any(
        predicate(*args, **kwargs) if callable(predicate) else bool(predicate)
        for predicate in predicates
    )


def arg_equals(*args, **kwargs):
    return True


def max_arg(*args, **kwargs):
    return True


def min_arg(*args, **kwargs):
    return True


def targets_ridges_overlap(*args, **kwargs):
    return True


def tool_called(*args, **kwargs):
    return True


def any_tool_called(*args, **kwargs):
    return True


def ordered_tools(*args, **kwargs):
    return True


def no_tool_called(*args, **kwargs):
    return True

"""Keep execution-only task overrides out of upstream scenario constructors."""
def instantiate(cls, kwargs):
    values = dict(kwargs)
    task = values.pop('agent_task_override', None)
    scenario = cls(**values)
    if task is not None:
        if not isinstance(task, str):
            raise ValueError('agent_task_override must be text')
        scenario.agent_task_override = task
    return scenario

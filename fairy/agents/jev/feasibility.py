"""Local menu infeasibility is a constraint, never an executed tool failure."""
VERSION='public-feasibility-v1'
class ToolNotReady(ValueError):
    def __init__(self,tool,argument,arguments):
        self.tool,self.argument,self.arguments=tool,argument,dict(arguments)
        super().__init__(f'{tool}.{argument} has no legal value for selected scope {arguments}; replenish resources, select a feasible target or wait for readiness.')

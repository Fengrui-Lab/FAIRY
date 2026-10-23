"""Compatibility entry points; crop integration now has one shared timeline.

Use FarmPhysicsState.crop. This module contains no environmental update loop.
"""

def initialize_from_ridges(world, target_sim_time):
    return world.physics.crop.initialize_from_ridges(world, target_sim_time)

def sync_public_fields(world):
    return world.physics.crop.sync_public_fields(world)

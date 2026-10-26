"""Explicit public agriculture service classes, registered in a fixed order."""
from .base import SharedFarmService
from .world import WorldService
from .farm import FarmService
from .weather import WeatherService
from .sensor import SensorService
from .field_ops import FieldOpsService
from .tractor import TractorService
from .drone import DroneService
from .robot import RobotService


SERVICE_CLASSES = (WorldService, FarmService, WeatherService, SensorService,
                   FieldOpsService, TractorService, DroneService, RobotService)

__all__ = ["SharedFarmService", "WorldService", "FarmService", "WeatherService",
           "SensorService", "FieldOpsService", "TractorService", "DroneService",
           "RobotService", "SERVICE_CLASSES"]

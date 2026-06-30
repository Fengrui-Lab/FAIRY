## Migrated Scenario Class Defaults

- ARE FARM scenarios often define runtime configuration such as `start_time`,
  `duration`, `queue_based_loop`, and `time_increment_in_seconds` as class
  attributes on `Scenario` subclasses.
- FAIRY's `Scenario` base is a dataclass, so inherited field defaults can
  shadow those class attributes on new instances. If `start_time` falls back to
  `None`, `Engine` starts at Unix timestamp `0` and full-season weather/physics
  logs drift to 1970.
- `Scenario.__post_init__` now copies subclass class attributes onto the
  instance only when the instance still equals the base dataclass default.
  Explicit constructor values still win.

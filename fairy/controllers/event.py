from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable


@dataclass
class Event(ABC):
    """
    Base class for all events in the system.
    """

    time_start: float  # time at which the event is scheduled to start
    time_duration: float  # Duration of the event in times
    time_started: float | None = None
    time_completed: float | None = None
    triggered: bool = False

    def start(self, time_started):
        """
        Starts the event.
        This method should be overridden by subclasses to define specific event behavior.
        """
        self.time_started = time_started
        self.triggered = True

    def complete(self, time_completed):
        """
        Completes the event.
        """
        self.time_completed = time_completed

    def has_elapsed_duration(self, current_time) -> bool:
        """
        Checks whether the event has run for its configured duration.
        """
        if self.time_started is None:
            return False

        times_elapsed = current_time - self.time_started + 1
        return times_elapsed >= self.time_duration

    @abstractmethod
    def step(self):
        """
        Advances the event by one time step.
        This method should be overridden by subclasses to define specific event behavior.
        """
        ...


@dataclass
class NotificationEvent(Event):
    """
    Simple event that emits a single notification message when triggered.
    """

    message: str = ""
    callback: Callable[[], None] | None = None

    def step(self):
        if self.callback is not None:
            self.callback()
        return self.message

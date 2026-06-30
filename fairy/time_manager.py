import time

class TimeManager:
    """
    A class for managing time in the simulation.
    """

    def __init__(self):
        current_time = time.time()

        # This is the actual real time, not the simulated time, with which we measure actual time passed.
        self.real_start_time: float | None = current_time
        # This is the simulated start time, that we can set manually to a given time.
        self.start_time: float | None = current_time
        # The offset added to the time passed. This is used to take into account the pauses.
        self.offset: float = 0

    def time(self) -> float:
        """
        Returns the current time, which is the sum of the start time and the time passed.

        Returns:
            float: The current time.
        """
        if self.start_time is None:
            raise Exception("start_time cannot be None")
        return self.start_time + self.time_passed()

    def time_passed(self) -> float:
        """
        Returns the time passed since the start time, taking into account any pauses.

        Returns:
            float: The time passed.
        """
        if self.real_start_time is None:
            raise Exception("real_start_time cannot be null")
        return self.real_time_passed() + self.offset

    def real_time_passed(self) -> float:
        """
        Returns the real time passed since the start time, without considering any pauses.

        Returns:
            float: The real time passed.
        """
        if self.real_start_time is None:
            raise Exception("real_start_time cannot be null")
        return time.time() - self.real_start_time

    def reset(self, start_time: float | None = None) -> None:
        """
        Resets the start time to the current time, or to the specified `start_time` if provided.

        Args:
            start_time (float | None): The new start time. Defaults to current time.
        """
        current_time = time.time()
        if start_time is None:
            self.start_time = current_time
        else:
            self.start_time = start_time
        self.real_start_time = current_time

        # Reset other variables
        self.offset = 0

    def set_offset(self, offset: float) -> None:
        self.offset = offset

    def add_offset(self, offset: float) -> None:
        self.offset += offset
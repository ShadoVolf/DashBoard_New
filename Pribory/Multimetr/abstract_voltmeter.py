from abc import ABC, abstractmethod
import time


class AbstractVoltmeter(ABC):
    @abstractmethod
    def connect(self):
        pass

    @abstractmethod
    def disconnect(self):
        pass

    @abstractmethod
    def setup(self, measurement_type):
        pass

    @abstractmethod
    def read(self):
        pass

    @abstractmethod
    def get_id(self):
        pass

    @abstractmethod
    def set_emulate(self, emulate):
        pass
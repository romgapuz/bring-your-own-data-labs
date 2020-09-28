import abc
from clevercsv.detect_type import TypeDetector


class ValidationRule(metaclass=abc.ABCMeta):
    @classmethod
    def __subclasshook__(cls, subclass):
        return (hasattr(subclass, 'validate') and
                callable(subclass.validate) or
                NotImplemented)

    @abc.abstractmethod
    def validate(self, obj):
        raise NotImplementedError

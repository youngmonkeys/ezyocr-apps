import importlib.util


class OcrBackend:
    name = ""

    @classmethod
    def available(cls):
        return True

    def load(self, options):
        raise NotImplementedError

    def read_lines(self, image):
        raise NotImplementedError


def has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False

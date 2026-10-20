from dataclasses import dataclass


@dataclass(frozen=True)
class RecognitionContext:
    lines: list
    image: object
    barcode: str | None = None


class BusinessScript:
    name = "business_script"
    key_field = "tracking_number"
    required_fields = ()
    home_path = "/"
    media_link_path = None

    def extract(self, ctx):
        raise NotImplementedError

    def is_complete(self, result):
        return all(result.get(name) for name in (self.key_field, *self.required_fields))

    def has_any_field(self, result):
        return any(result.get(name) for name in (self.key_field, *self.required_fields))

from ezyocr.business.base import BusinessScript
from ezyocr.recognition.extract import extract_waybill


class WaybillCnScript(BusinessScript):
    name = "waybill_cn"
    key_field = "tracking_number"
    required_fields = ("tracking_number", "customer_code")
    media_link_path = "/ezydelivery/api/v1/delivery-order-codes/{code}/medias/{media_id}"

    def extract(self, ctx):
        result = extract_waybill(ctx.lines, ctx.image)
        result["tracking_number"] = result["tracking_number"] or ctx.barcode
        return result

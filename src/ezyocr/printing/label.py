def build_label(settings, tracking_number, customer_code):
    builders = {"zpl": build_zpl, "tspl": build_tspl}
    builder = builders.get(settings.language.lower())
    if builder is None:
        raise ValueError(f"Unsupported printer language: {settings.language}")
    return builder(settings, tracking_number, customer_code or "")


def build_zpl(settings, tracking_number, customer_code):
    dots_per_mm = settings.dpi / 25.4
    width = round(settings.label_width_mm * dots_per_mm)
    height = round(settings.label_height_mm * dots_per_mm)
    return "\n".join([
        "^XA",
        "^CI28",
        f"^PW{width}",
        f"^LL{height}",
        f"^FO30,20^A0N,70,70^FD{_zpl_text(customer_code)}^FS",
        f"^FO30,110^BY2^BCN,90,Y,N,N^FD{_zpl_text(tracking_number)}^FS",
        "^XZ",
        "",
    ]).encode("utf-8")


def build_tspl(settings, tracking_number, customer_code):
    return "\r\n".join([
        f"SIZE {settings.label_width_mm} mm, {settings.label_height_mm} mm",
        "GAP 2 mm, 0 mm",
        "DIRECTION 1",
        "CLS",
        f'TEXT 30,20,"5",0,1,1,"{_tspl_text(customer_code)}"',
        f'BARCODE 30,110,"128",90,1,0,2,4,"{_tspl_text(tracking_number)}"',
        "PRINT 1,1",
        "",
    ]).encode("utf-8")


def _zpl_text(value):
    return value.replace("^", "").replace("~", "")


def _tspl_text(value):
    return value.replace('"', "")

import re
from collections import Counter

import zxingcpp

CUSTOMER_CODE_RE = re.compile(r"(?<![A-Za-z])([A-Za-z]{2,4})-?(\d{2,4})(?!\d)")
CUSTOMER_NUMBER_RE = re.compile(r"[（(](\d{3,})[)）]")
KST_CODE_RE = re.compile(r"(?<![A-Za-z])KST-?(\d{3,})", re.IGNORECASE)
CUSTOMER_CODE_DIGITS = 4

FULL_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
GLUED_PHONE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*?)(1[3-9]\d{9})$")
MASKED_PHONE_RE = re.compile(r"\d{0,3}[*^][*^ ]*\d{4}")
VIRTUAL_PHONE_RE = re.compile(r"1[3-9]\d{9}转\d+")
TRACKING_RE = re.compile(r"[A-Z]{0,4}\d{11,20}")
QR_TRACKING_RE = re.compile(r"^([A-Z]{2,4}\d{9,20})")
NUMBER_RE = re.compile(r"\d+")
MIN_EXCLUDED_PART = 5
MAX_PIECE_SUFFIX = 4
PIECE_RE = re.compile(r"(?<![\d/])(\d{1,3})/\d{1,3}(?![\d/])")
ADDRESS_HINT_RE =re.compile(r"省|自治区|市|区|县|镇")
SENDER_RE = re.compile(r"^寄[件方人]?[:：]?")
RECEIVE_RE = re.compile(r"^收(?!.*(?:存根|签名|签收|代理))")
NAME_PREFIX_RE = re.compile(r"^(?:收[件货方人]*)?(?:姓名)?[:：]?")
NAME_SUFFIX_RE = re.compile(r"(?:联系方式|联系电话|电话|手机|虚拟号码|隐私号码)[:：]?$")
ADDRESS_STOP_WORDS = (
    "到付", "现付", "寄付", "已验视", "托寄物", "品类", "备注", "签收", "运单号", "母单号", "KG", "kg",
    "网点", "品名", "件数", "重量", "包装", "货物", "物品",
)
MATRIX_FORMATS = {"QRCode", "DataMatrix", "PDF417", "Aztec", "MicroQRCode"}
CARRIERS = (
    ("中通快运", ("中通快运", "ZTO FREIGHT")),
    ("中通", ("中通", "ZTO")),
    ("圆通", ("圆通", "YTO")),
    ("韵达", ("韵达", "yunda")),
    ("申通", ("申通", "STO")),
    ("极兔", ("极兔", "J&T")),
    ("顺丰", ("顺丰", "SF EXPRESS")),
    ("顺心捷达", ("顺心",)),
    ("京东", ("京东", "JDL")),
    ("EMS", ("EMS", "中国邮政")),
    ("跨越速运", ("跨越", "KYE")),
    ("德邦", ("德邦", "DEPPON")),
    ("安能物流", ("安能", "ane56")),
    ("百世快运", ("百世", "BEST FREIGHT")),
    ("壹米滴答", ("壹米", "滴答")),
    ("融辉物流", ("融辉", "融速达")),
)
TRACKING_CARRIERS = (
    ("SF", "顺丰"),
    ("JD", "京东"),
    ("YT", "圆通"),
    ("KYE", "跨越速运"),
)


def compact(text):
    return re.sub(r"\s+", "", text)


def find_phone(text):
    match = FULL_PHONE_RE.search(text)
    if match:
        return compact(text[:match.start()]), match.group()
    flat = compact(text)
    match = FULL_PHONE_RE.search(flat)
    if match:
        return flat[:match.start()], match.group()
    match = GLUED_PHONE_RE.match(flat)
    if match:
        return match.group(1), match.group(2)
    match = MASKED_PHONE_RE.search(text)
    if match:
        return text[:match.start()], compact(match.group())
    return None


def clean_name(name):
    name = NAME_PREFIX_RE.sub("", compact(name))
    name = NAME_SUFFIX_RE.sub("", name)
    return name.strip(" :：/|-")


def decode_barcodes(image):
    linear, matrix = [], []
    for barcode in zxingcpp.read_barcodes(image):
        if barcode.format.name in MATRIX_FORMATS:
            matrix.append(barcode.text)
        else:
            linear.append(barcode.text)
    return linear, matrix


def tracking_from_barcodes(linear, matrix):
    candidates = [v for v in linear if TRACKING_RE.fullmatch(v)]
    if candidates:
        return Counter(candidates).most_common(1)[0][0], "barcode"
    for value in matrix:
        match = QR_TRACKING_RE.match(value)
        if match:
            return match.group(1), "qrcode"
    return None, None


def pick_tracking(lines, image):
    tracking, source = tracking_from_barcodes(*decode_barcodes(image))
    if tracking:
        return tracking, source

    counts = Counter()
    best = {}
    for line in lines:
        if "母单号" in line.text:
            continue
        for value in TRACKING_RE.findall(compact(FULL_PHONE_RE.sub(" ", line.text))):
            if FULL_PHONE_RE.fullmatch(value):
                continue
            counts[value] += 1
            if line.horizontal:
                best[value] = max(best.get(value, 0), line.score)
    if not best:
        return None, None
    value = max(best, key=lambda v: (counts[v], best[v]))
    return value, "ocr"


def pick_master_tracking(lines, tracking):
    for line in lines:
        if "母单号" in line.text:
            match = TRACKING_RE.search(compact(line.text))
            if match:
                return match.group()
    if not tracking:
        return None
    pieces = {int(n) for line in lines for n in PIECE_RE.findall(compact(line.text))}
    for line in lines:
        for value in TRACKING_RE.findall(compact(line.text)):
            suffix = tracking[len(value):]
            if (
                value != tracking
                and tracking.startswith(value)
                and len(suffix) <= MAX_PIECE_SUFFIX
                and suffix.isdigit()
                and int(suffix) in pieces
            ):
                return value
    return None


def detect_carrier(lines, tracking):
    text = " ".join(line.text for line in lines)
    for name, keywords in CARRIERS:
        if any(keyword in text for keyword in keywords):
            return name
    for prefix, name in TRACKING_CARRIERS:
        if tracking and tracking.startswith(prefix):
            return name
    return None


def collect_address(lines, start, end_y, left_x, skip):
    parts = []
    for line in sorted(lines, key=lambda l: (l.cy, l.x1)):
        if line in skip or not line.horizontal:
            continue
        same_row_right = start.same_row(line) and line.x1 >= start.x2 - 10
        if line.cy >= end_y or not (line.cy > start.cy or same_row_right):
            continue
        if line.x1 < left_x - 80 or line.text == "收":
            continue
        if any(word in line.text for word in ADDRESS_STOP_WORDS):
            break
        parts.append(line.text)
    return "".join(compact(p) for p in parts) or None


def extract_recipient(lines):
    horizontal = [l for l in lines if l.horizontal]
    sender_ys = [l.y1 for l in horizontal if SENDER_RE.match(l.text)]
    receive_marks = sorted((l for l in horizontal if RECEIVE_RE.match(l.text)), key=lambda l: l.y1)
    receive_mark = receive_marks[0] if receive_marks else None
    top_y = float("-inf")
    if receive_mark and any(y < receive_mark.y1 for y in sender_ys):
        top_y = receive_mark.y1 - receive_mark.height
    sender_y = min((y for y in sender_ys if y > top_y), default=float("inf"))

    phones = []
    for line in horizontal:
        if line.y1 >= sender_y or line.cy <= top_y:
            continue
        found = find_phone(line.text)
        if found:
            phones.append((line, found))
    phones.sort(key=lambda item: item[0].cy)
    phones = [
        item for item in phones
        if not (
            VIRTUAL_PHONE_RE.search(compact(item[0].text))
            and any(0 < other.cy - item[0].cy <= 3 * item[0].height for other, _ in phones)
        )
    ]

    if phones:
        if receive_mark:
            phone_line, (name_part, phone) = min(phones, key=lambda item: abs(item[0].cy - receive_mark.cy))
        else:
            phone_line, (name_part, phone) = phones[0]
        row = [l for l in horizontal if l is not phone_line and phone_line.same_row(l) and l.x2 <= phone_line.x1 + 10]
        name = clean_name("".join(l.text for l in sorted(row, key=lambda l: l.x1)) + name_part)
        if not name and receive_mark and len(receive_mark.text) > 1:
            name = clean_name(receive_mark.text)
        later_phones = [l.y1 for l, _ in phones if l.cy > phone_line.cy and not phone_line.same_row(l)]
        end_y = min([sender_y, *later_phones])
        left_x = min([phone_line.x1, *(l.x1 for l in row), *([receive_mark.x1] if receive_mark else [])])
        address = collect_address(horizontal, phone_line, end_y, left_x, {phone_line, *row, receive_mark})
        return {"name": name.replace("^", "*") or None, "phone": phone.replace("^", "*"), "address": address}

    anchors = [l for l in horizontal if top_y < l.cy and l.y1 < sender_y and ADDRESS_HINT_RE.search(l.text)]
    if receive_mark:
        anchors.sort(key=lambda l: abs(l.cy - receive_mark.cy))
    if not anchors:
        return {"name": None, "phone": None, "address": None}
    first = anchors[0]
    head = compact(first.text)
    match = re.match(r"^([A-Za-z0-9]+)[/|\s]*(.*)$", head)
    name, address_head = (match.group(1), match.group(2)) if match else (None, head)
    rest = collect_address(horizontal, first, sender_y, first.x1, {receive_mark})
    return {"name": name, "phone": None, "address": address_head + (rest or "")}


def kst_codes(text):
    return [number[:CUSTOMER_CODE_DIGITS] for number in KST_CODE_RE.findall(text)]


def extract_customer_code(recipient, customers=()):
    kst = Counter()
    codes = Counter()
    numbers = Counter()
    for text in (recipient["name"], recipient["address"]):
        flat = compact(text or "")
        kst.update(kst_codes(flat))
        for prefix, number in CUSTOMER_CODE_RE.findall(flat):
            if prefix.upper() == "KST":
                continue
            codes[prefix.upper() + number] += 1
            numbers[number] += 1
        for number in CUSTOMER_NUMBER_RE.findall(flat):
            numbers[number[:CUSTOMER_CODE_DIGITS]] += 1

    candidates = [c for c, _ in kst.most_common()]
    candidates += [c for c, _ in codes.most_common()]
    candidates += [n for n, _ in numbers.most_common() if not any(c.endswith(n) for c in candidates)]

    if kst:
        return kst.most_common(1)[0][0], "kst", candidates
    if customers:
        for code, _ in codes.most_common():
            if code in customers:
                return code, "customer_list", candidates
        for number, _ in numbers.most_common():
            matches = [c for c in customers if re.fullmatch(r"[A-Z]+" + number, c)]
            if len(matches) == 1:
                return matches[0], "customer_list_number", candidates
    if codes:
        code = max(codes, key=lambda c: (codes[c] + numbers[re.sub(r"^[A-Z]+", "", c)], len(c)))
        return code, "ocr", candidates
    if numbers:
        return numbers.most_common(1)[0][0], "number", candidates
    return None, None, candidates


def codes_from_address_lines(lines):
    kst = Counter()
    codes = Counter()
    for line in lines:
        if ADDRESS_HINT_RE.search(line.text):
            flat = compact(line.text)
            kst.update(kst_codes(flat))
            for prefix, number in CUSTOMER_CODE_RE.findall(flat):
                if prefix.upper() != "KST":
                    codes[prefix.upper() + number] += 1
    return [c for c, _ in kst.most_common()] + [c for c, _ in codes.most_common()]


def longest_number(texts, excluded):
    best = None
    for text in texts:
        flat = compact(text or "")
        for pattern in (TRACKING_RE, FULL_PHONE_RE, MASKED_PHONE_RE):
            flat = pattern.sub(" ", flat)
        for number in NUMBER_RE.findall(flat):
            if len(number) >= MIN_EXCLUDED_PART and any(number in value for value in excluded):
                continue
            if best is None or len(number) > len(best):
                best = number
    return best


def extract_waybill(lines, image, customers=()):
    tracking, source = pick_tracking(lines, image)
    master_tracking = pick_master_tracking(lines, tracking)
    recipient = extract_recipient(lines)
    customer_code, customer_source, candidates = extract_customer_code(recipient, customers)
    if not candidates:
        candidates = codes_from_address_lines(lines)
        if candidates:
            known = [c for c in candidates if c in customers]
            customer_code = (known or candidates)[0]
            customer_source = "customer_list" if known else "address_line"
    if not candidates:
        excluded = [v for v in (tracking, master_tracking, recipient["phone"]) if v]
        number = longest_number((recipient["name"], recipient["address"]), excluded)
        number = number or longest_number((line.text for line in lines), excluded)
        if number:
            customer_code, customer_source, candidates = number, "longest_number", [number]
    return {
        "carrier": detect_carrier(lines, tracking),
        "tracking_number": tracking,
        "tracking_source": source,
        "master_tracking_number": master_tracking,
        "customer_code": customer_code,
        "customer_code_source": customer_source,
        "customer_candidates": candidates,
    }

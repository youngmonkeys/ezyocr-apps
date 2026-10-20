class Line:
    def __init__(self, text, score, box):
        self.text = text.strip()
        self.score = min(max(float(score), 0.0), 1.0)
        self.x1, self.y1, self.x2, self.y2 = (int(v) for v in box)

    @property
    def cy(self):
        return (self.y1 + self.y2) / 2

    @property
    def height(self):
        return self.y2 - self.y1

    @property
    def horizontal(self):
        return (self.x2 - self.x1) >= 0.7 * self.height

    def same_row(self, other):
        overlap = min(self.y2, other.y2) - max(self.y1, other.y1)
        return overlap > 0.5 * min(self.height, other.height)


def make_lines(items):
    return [Line(text, score, box) for text, score, box in items if text and text.strip()]


def box_from_points(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)

from workers.critical.print_worker import _build_escpos_ticket, _ticket_escpos_sequence


class Rec:
    def __init__(self):
        self.out = b""

    def _raw(self, b):
        self.out += b if isinstance(b, bytes) else b.encode()

    def text(self, s):
        self.out += s.encode()

    def set(self, **kw):
        pass

    def cut(self, **kw):
        pass


def _check(data: bytes):
    assert b"\x1dkE\x05OXFJZ\n" in data  # format B, no NUL terminator
    assert b"\x1dv0" not in data  # no raster


def test_raw_builder():
    _check(_build_escpos_ticket("OXFJZ", "G", "SITE"))


def test_escpos_sequence():
    r = Rec()
    _ticket_escpos_sequence(r, barcode="OXFJZ", gate_name="G", site_name="SITE",
                            date_str="d", time_str="t")
    _check(r.out)

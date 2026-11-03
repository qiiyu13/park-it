"""Tests for Compass controller parser."""



from protocols.compass.parser import parse_stat


class TestParseStat:
    """Test STAT response parser."""

    def test_empty_response(self):
        """Empty response has no inputs."""
        result = parse_stat(b"")
        assert result["in1"] is False
        assert result["in2"] is False
        assert result["in3"] is False
        assert result["in4"] is False
        assert result["wiegand_w"] is None
        assert result["wiegand_x"] is None

    def test_in2_on(self):
        """Detect IN2 ON."""
        result = parse_stat(b"\xa6STATIN2ON\xa9")
        assert result["in2"] is True
        assert result["in1"] is False

    def test_in1_on(self):
        """Detect IN1 ON."""
        result = parse_stat(b"\xa6STATIN1ON\xa9")
        assert result["in1"] is True

    def test_wiegand_w(self):
        """Parse Wiegand W (RFID) card."""
        # Card hex = 1234 -> decimal = 4660
        result = parse_stat(b"\xa6STATW1234\xa9")
        assert result["wiegand_w"] == "4660"
        assert result["wiegand_x"] is None

    def test_wiegand_x(self):
        """Parse Wiegand X (UHF) card."""
        result = parse_stat(b"\xa6STATXABCD\xa9")
        assert result["wiegand_x"] == "43981"
        assert result["wiegand_w"] is None

    def test_multiple_inputs(self):
        """Multiple inputs active."""
        result = parse_stat(b"\xa6STATIN2ONIN4ONW1234\xa9")
        assert result["in2"] is True
        assert result["in4"] is True
        assert result["wiegand_w"] == "4660"

    def test_stat1_format(self):
        """STAT1 is the short form of '01' → IN2."""
        result = parse_stat(b"\xa6STAT1\xa9")
        assert result["in2"] is True
        assert result["in1"] is False

    def test_stat10_format(self):
        """STAT10 is the short form of the IN1/IN2 mask → IN1."""
        result = parse_stat(b"\xa6STAT10\xa9")
        assert result["in1"] is True
        assert result["in2"] is False

    def test_stat11_format(self):
        """STAT11 asserts both short-form inputs."""
        result = parse_stat(b"\xa6STAT11\xa9")
        assert result["in1"] is True
        assert result["in2"] is True

    def test_stat00_format(self):
        """STAT00 / STAT0 assert neither input."""
        result = parse_stat(b"\xa6STAT0\xa9")
        assert result["in1"] is False
        assert result["in2"] is False


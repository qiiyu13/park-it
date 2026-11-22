"""Pure test (no DB): a single-type lane supplies the vehicle type, a mixed lane does not."""

import asyncio
from types import SimpleNamespace

from api.app.services.transaction import lane_vehicle_type_id


class FakeDB:
    def __init__(self, hw):
        self.gate = None if hw is None else SimpleNamespace(hardware_config=hw)

    async def get(self, _model, _id):
        return self.gate


def run(hw, gate_out_id=1):
    return asyncio.run(lane_vehicle_type_id(FakeDB(hw), gate_out_id))


def test_single_lane_returns_default_type():
    assert run({"lane_type": "SINGLE", "default_vehicle_type_id": 2}) == 2


def test_mixed_lane_returns_none():
    assert run({"lane_type": "MIXED", "default_vehicle_type_id": 2}) is None


def test_missing_gate_or_default_returns_none():
    assert run(None) is None
    assert run({"lane_type": "SINGLE"}) is None
    assert run({"lane_type": "SINGLE", "default_vehicle_type_id": 2}, gate_out_id=None) is None

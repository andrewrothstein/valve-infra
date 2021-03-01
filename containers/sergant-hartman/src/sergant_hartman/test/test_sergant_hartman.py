import attr
import copy
from unittest.mock import create_autospec
from twisted.trial.unittest import SynchronousTestCase
from twisted.internet import defer
from klein import Klein
from treq.testing import StubTreq
from .. import (
    SergantHartman,
)
from .._service import (
    pdu_added_to_machine,
    ready_for_service_disabled,
    MarsAPI,
    BootsAPI,
    PDUGatewayAPI
)


@attr.s
class StubMachines(object):
    _app = Klein()
    _machines = attr.ib()

    def resource(self):
        return self._app.resource()


class SergantHartmanTests(SynchronousTestCase):
    def setUp(self):
        self.machine_without_pdu = {
            "full_name": "gfx8-2",
            "base_name": "gfx8",
            "tags": [
                "amdgpu:family::CZ",
                "amdgpu:codename::STONEY",
                "amdgpu:APU",
                "amdgpu:gfxversion::gfx8"
            ],
            "mac_address": "10:62:e5:0e:0a:54",
            "ip_address": "10.42.0.11",
            "pdu_port_id": None,
            "ready_for_service": False,
            "is_retired": False,
            "first_seen": "2021-03-01T13:22:30.748265Z",
            "last_updated": "2021-03-01T13:22:30.748328Z",
            "pdu": None
        }
        self.machine_with_pdu = copy.deepcopy(self.machine_without_pdu)
        self.machine_with_pdu['pdu_port_id'] = '1'
        self.machine_with_pdu['pdu'] = 'a-test-pdu'

        service = StubMachines([])
        treq = StubTreq(service.resource())

        self.mars = create_autospec(MarsAPI, spec_set=True)
        self.boots = create_autospec(BootsAPI, spec_set=True)
        self.pdu_gateway = create_autospec(PDUGatewayAPI, spec_set=True)
        self.hartman = SergantHartman(
            treq=treq,
            mars_api=self.mars,
            boots_api=self.boots,
            pdu_gateway_api=self.pdu_gateway,
            num_reps=3,
        )
        self.client = StubTreq(self.hartman.resource())

    @defer.inlineCallbacks
    def get(self, url):
        response = yield self.client.get(url)
        self.assertEqual(response.code, 200)
        content = yield response.json()
        defer.returnValue(content)

    def test_empty_machines(self):
        content = self.successResultOf(self.get(u"http://test.invalid/"))
        self.assertEqual(content, {})

    def test_non_existing_machine(self):
        failure = self.failureResultOf(
            self.get(u"http://test.invalid/rollcall/de:ad:be:ef:ca:fe"))
        self.assertEqual(failure.getErrorMessage(), "404 != 200")

    def test_enlist_machine__without_a_pdu(self):
        result = self.hartman.enlist_machines([self.machine_without_pdu])
        self.assertEqual(self.successResultOf(result), None)
        content = self.successResultOf(self.get(u"http://test.invalid/"))
        self.assertEqual(content, {})

    def test_enlist_machine__with_a_pdu(self):
        result = self.hartman.enlist_machines([self.machine_with_pdu])
        self.assertEqual(self.successResultOf(result), None)
        content = self.successResultOf(self.get(u"http://test.invalid/"))
        self.assertEqual(content, {'10:62:e5:0e:0a:54': 0})

    def test_pdu_added_to_machine(self):
        diff = {
            "type_changes": {
                "root.pdu_id": {
                    "old_type": "NoneType",
                    "new_type": "int",
                    "old_value": None,
                    "new_value": 1
                },
                "root.pdu_port_id": {
                    "old_type": "NoneType",
                    "new_type": "str",
                    "old_value": None,
                    "new_value": "1"
                }
            }
        }
        assert pdu_added_to_machine(diff)
        diff["type_changes"]["root.pdu_id"]["new_type"] = None
        assert not pdu_added_to_machine(diff)

    def test_ready_for_service_disabled(self):
        diff = {
            "values_changed": {
                "root.ready_for_service": {
                    "new_value": False,
                    "old_value": True
                }
            }
        }
        assert ready_for_service_disabled(diff)
        diff['values_changed']['root.ready_for_service']['new_value'] = True
        diff['values_changed']['root.ready_for_service']['old_value'] = False
        assert not ready_for_service_disabled(diff)

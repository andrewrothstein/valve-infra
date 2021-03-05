#!/usr/bin/env python3
# -*- mode: python -*-

import attr
from pprint import pformat
from datetime import datetime, timedelta
import os
import json
import logging
from twisted.internet import reactor
from twisted.internet.task import deferLater
from twisted.internet.defer import ensureDeferred
import treq
from klein import Klein

from twisted.web import client
client._HTTP11ClientFactory.noisy = False

logger = logging.getLogger(__name__)
logger.setLevel(logging.getLevelName('DEBUG'))
log_formatter = \
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: "
                      "%(message)s")
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)


def parse_iso8601_date(d):
    # For some reason the datetime parser doesn't like the lone Z, I
    # thought it was spec'd. It does happily accept +00:00 in lieu of
    # Z.
    return datetime.fromisoformat(d.removesuffix("Z"))


def machine_has_pdu_assigned(machine):
    return machine['pdu'] and machine['pdu_port_id']


@attr.s
class BootsAPI(object):
    _treq = attr.ib()
    _api = attr.ib(default='http://10.42.0.1:8087')

    async def set_boot_containers(self, machine, containers):
        logger.debug(f'resetting boots configuration for\n{pformat(machine)}')
        boots_payload = {
            'board_name': machine['full_name'],
            'boot_method': {
                'type': 'b2c',
                'containers': containers,
            },
            # FIXME: MaRS should be taught about specifying the current
            # default kernel, somehow.
            'kernel_path': 'v0.6-ci-kernel',
            # Ditto, if there are defaults we need to keep, should merge
            # here rather than overwrite.
            'kernel_cmdline_extras': None,
            # Ditto
            'initrd_path': 'v0.6-initramfs.linux_amd64.cpio.xz',
            'ip': machine['ip_address'],
            'hostname': machine['full_name'],
        }
        r = await treq.post(
            f'{self._api}/duts/{machine["mac_address"]}',
            json=boots_payload)
        if r.code != 200:
            logger.error(await r.text())
            return False
        return True


@attr.s
class MarsAPI(object):
    _treq = attr.ib()
    _api = attr.ib(default='http://10.42.0.1:80')

    async def fetch_machine(self, mac_address):
        r = await treq.get(f'{self._api}/api/v1/machine/{mac_address}')
        return await r.json()

    async def fetch_nonready_machines(self, callback):
        logger.info(f"Fetching machines from MaRS at {self._api}")
        r = await self._treq.get(
            f'{self._api}/api/v1/machine/?ready_for_service=false')
        nonready_machines = await r.json()
        return await callback(nonready_machines)

    async def set_ready_for_service(self, machine):
        machine['ready_for_service'] = True
        r = await treq.patch(
            f'{self._api}/api/v1/machine/{machine["mac_address"]}/',
            json=machine)
        if r.code != 200:
            logger.error(await r.text())
            return False
        return True

    async def poll_for_events(self, callback):
        last_checked = datetime.now()
        while True:
            try:
                r = await treq.get(
                    f'{self._api}/api/v1/events/?since={last_checked.isoformat()}')
                events = await r.json()
                if not events:
                    logger.debug('No events to process... Sleeping')
                    continue
                logger.debug(f'Events available:\n{pformat(events)}')
                for event in events:
                    last_checked = parse_iso8601_date(event['date']) + \
                        timedelta(microseconds=1)
                    await callback(event)
            except Exception as err:
                # just keep on truckin'
                logger.info('Exception while retrieving event list from MaRS: '
                            f'({self._api}) -- \n{err}\n'
                            'Ignored.')
                pass
            finally:
                await deferLater(reactor, 5, lambda: None)


@attr.s
class PDUGatewayAPI(object):
    _treq = attr.ib()
    _api = attr.ib(default='http://10.42.0.1:8089')

    async def poweron(self, machine):
        return await self._action(machine, "ON")

    async def shutdown(self, machine):
        return await self._action(machine, "OFF")

    async def reboot(self, machine):
        await self.shutdown(machine)
        # The SNMP reboot command doesn't, by default, offer enough
        # time for the caps to discharge in the thin clients, it
        # seems. Manually perform the reboot by delaying a
        # sufficiently long time. Should look into whether there's any
        # possibility for change the off->on delay via the SNMP
        # interface.
        fudge_delay_between_off_on_transition_sec = 15
        return await deferLater(reactor,
                                fudge_delay_between_off_on_transition_sec,
                                lambda: ensureDeferred(self.poweron(machine)))
        # return await self._action(machine, "REBOOT")

    async def _action(self, machine, action):
        logger.info(f'PDU state change: {machine["mac_address"]} -> {action}')

        # We should never pick up machines without PDU port assignments
        # for this service
        assert machine['pdu'] and machine['pdu_port_id']

        r = await self._treq.get(machine['pdu'])
        # FIXME: Modify the PDU gateway API to return these URIs pre-baked
        pdu_data = await r.json()
        pdu_port_id = machine['pdu_port_id']
        pdu_api = f'{pdu_data["url"]}/v1/pdus/{pdu_data["name"]}/ports/{pdu_port_id}/state'
        logger.info(f'resetting {pdu_port_id} via {pdu_api}...')
        r = await self._treq.post(pdu_api, json={"state": action})
        if r.code != 200:
            logger.error(await r.text())
            return False
        logger.debug("PDU gateway said everything is good!")
        return True


def pdu_added_to_machine(diff):
    if 'type_changes' not in diff:
        return False
    type_changes = diff['type_changes']
    if 'root.pdu_id' not in type_changes or \
       'root.pdu_port_id' not in type_changes:
        return False
    new_pdu_id = type_changes['root.pdu_id']['new_type']
    new_pdu_port_id = type_changes['root.pdu_port_id']['new_type']
    return new_pdu_id and new_pdu_port_id


def ready_for_service_disabled(diff):
    if 'values_changed' not in diff:
        return False
    values_changed = diff['values_changed']
    return 'root.ready_for_service' in values_changed and \
        not values_changed['root.ready_for_service']['new_value']


@attr.s
class SergantHartman(object):
    _treq = attr.ib()
    _mars_api = attr.ib()
    _boots_api = attr.ib()
    _pdu_gateway_api = attr.ib()

    _app = Klein()

    _num_reps = attr.ib()
    _boot_map = attr.ib(init=False, default=attr.Factory(dict))

    def resource(self):
        return self._app.resource()

    def run(self):
        ensureDeferred(
            self._mars_api.fetch_nonready_machines(self.enlist_machines))
        ensureDeferred(self._mars_api.poll_for_events(self.process_event))
        self._app.run("0.0.0.0", 80)

    async def enlist_machines(self, machines):
        logger.info(f"Enlisting {len(machines)} machine(s)")
        for machine in machines:
            if not machine_has_pdu_assigned(machine):
                logger.warn(f'{machine["mac_address"]} has no PDU assignment, does not '
                            'meet prerequisites')
                continue
            mac = machine['mac_address']
            if mac not in self._boot_map:
                self._boot_map[mac] = 0
                # FIXME: error handling
                await self._boots_api.set_boot_containers(
                    machine,
                    ['registry.freedesktop.org/chturne/radv-infra/machine_registration:latest sgt_hartman'])
                await self._pdu_gateway_api.reboot(machine)
                logger.info(f"Enlisted {mac}")

    async def process_event(self, event):
        async def fetch_machine():
            r = await self._treq.get(event['machine'])
            return await r.json()

        # FIXME: Create nice event abstraction, part of wider "MaRS client package" work.
        if event['category'] == 'machine-created':
            machine = await fetch_machine()
            if machine_has_pdu_assigned(machine):
                await self.enlist_machines([machine])
            else:
                logger.debug('Ignoring machine-created, this machine has no PDU')
        elif event['category'] == 'machine-updated':
            diff = json.loads(event['diff'])
            machine = await fetch_machine()
            logger.info(f'Processing update event:\n{pformat(diff)}')
            if pdu_added_to_machine(diff):
                await self.enlist_machines([machine])
            elif ready_for_service_disabled(diff):
                # Probably we don't want to watch for toggling off. Imagine
                # the operator wants to take this machine down for whatever
                # their reason. If Sgt. Hartman comes along and the machine
                # passes our idea of ready, we'll reenlist the machine, even
                # though the operator probably knows something we don't.
                # Might be best to add a separate field in Machine for
                # infrastructure testing, or only take machines through the
                # basic training on machine-created.
                await self.enlist_machines([machine])

    @_app.route("/")
    def root(self, request):
        request.setHeader('Content-Type', 'application/json')
        return json.dumps(self._boot_map).encode('utf-8')

    @_app.route('/rollcall/<string:mac_address>')
    async def rep_completed(self, request, mac_address):
        def reenroll(mac_address, failure_reason):
            # FIXME: the error handling here doesn't work
            # We need some method to pick up machines that haven't
            # progressed for some suitable amount of time. For now
            # just assume everything works perfectly.
            self._boot_map[mac_address] = 0
            request.setResponseCode(400)
            msg = f'Failed to finish testing for {mac_address}. {failure_reason}. Reenrolling...'
            logger.info(msg)
            return msg + '\r\n'

        if mac_address not in self._boot_map:
            request.setResponseCode(404)
            msg = f'{mac_address} is not being tested'
            logger.info(msg)
            return msg + '\r\n'

        self._boot_map[mac_address] += 1

        machine = await self._mars_api.fetch_machine(mac_address)
        if self._boot_map[mac_address] == self._num_reps:
            logger.info(f'{mac_address} has completed boot test')
            if not await self._mars_api.set_ready_for_service(machine):
                return reenroll(machine['mac_address'],
                                'failed to update MaRS')
            if not await self._pdu_gateway_api.shutdown(machine):
                return reenroll(machine['mac_address'],
                                'failed to turn off machine')
            del self._boot_map[mac_address]
            return f'{mac_address} has completed basic testing\r\n'
        else:
            reps = self._boot_map[mac_address]
            if not await self._pdu_gateway_api.reboot(machine):
                return reenroll(machine['mac_address'],
                                'failed to reboot machine')
            msg = f'{mac_address} has completed {reps}/{self._num_reps} boot checks'
            logger.info(msg)
            return msg + '\r\n'


def main():  # pragma: nocover
    mars_api = MarsAPI(
        treq=treq,
        api=os.getenv('MARS_HOST', 'http://10.42.0.1:80'))
    boots_api = BootsAPI(
        treq=treq,
        api=os.getenv('BOOTS_HOST', 'http://10.42.0.1:8087'))
    pdu_gateway_api = PDUGatewayAPI(
        treq=treq,
        api=os.getenv('PDU_GATEWAY_HOST', 'http://10.42.0.1:8089'))

    service = SergantHartman(
        treq=treq,
        mars_api=mars_api,
        boots_api=boots_api,
        pdu_gateway_api=pdu_gateway_api,
        num_reps=5)

    service.run()


if __name__ == '__main__':  # pragma: nocover
    main()

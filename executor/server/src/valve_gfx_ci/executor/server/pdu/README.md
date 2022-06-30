# Power Delivery Unit (PDU) Module

The goal of the project is to create a library that can speak with as many PDU
models as possible without the need for configuration files. The configuration
is meant to be stored externally, and merely passed to this helper library
during the instanciation of a PDU object.

The library:

 * Exposes the list of drivers supported / models
 * Instanciate PDUs
 * List the available ports of a PDU
 * Sets / Gets the state of of ports

## Supported PDUs

Any SNMP-enabled PDU is supported by this project, but the following models have
pre-baked configuration to make things easier:

 * APC's Masterswitch: `apc_masterswitch`
 * Cyberpower's PDU41004: `cyberpower_pdu41004`
 * Cyberpower's pdu15swhviec12atnet:`cyberpower_pdu15swhviec12atnet`
 * A generic SNMP driver: `snmp`
 * A virtual PDU: `vpdu`
 * A dummy PDU: `dummy`

See [Instanciating an SNMP-enabled PDU](#instanciating-an-snmp-enabled-pdu) for more
information on how to set up your PDU.

## Gotchas

Be warned that the current interface is *not* stable just yet.

## Instanciating an SNMP-enabled PDU

### Already-supported PDUs

If your PDU is in the supported list, then you are in luck and the only
information needed from you will be the model name, and the hostname of the
device:

    pdu = PDU.create(model="<<model>>", config={"hostname": "<<ip_address>>"})

or

    from pdu.drivers.apc import ApcMasterswitchPDU
    pdu = ApcMasterswitchPDU(config={"hostname": "<<ip_address>>"})

### Other SNMP-enabled PDUs

If your PDU model is currently-unknown, you will need to use the default SNMP
driver which will require a lot more information from you. Here is an example
for the `apc_masterswitch`:

    pdu = PDU.create(model="snmp", config={
            "hostname": "10.0.0.42",
            "oid_outlets_label_base": "iso.3.6.1.4.1.318.1.1.4.4.2.1.4",
            "oid_outlets_base": "iso.3.6.1.4.1.318.1.1.4.4.2.1.3",
            "community": "private",
            "action_to_snmp_value": { "ON": 1, "OFF": 2, "REBOOT": 3}
    })

or

    from pdu.drivers.snmp import SnmpPDU

    pdu = SnmpPDU(config={
            "hostname": "10.0.0.42",
            "oid_outlets_label_base": "iso.3.6.1.4.1.318.1.1.4.4.2.1.4",
            "oid_outlets_base": "iso.3.6.1.4.1.318.1.1.4.4.2.1.3",
            "community": "private",
            "action_to_snmp_value": { "ON": 1, "OFF": 2, "REBOOT": 3}
    })

To figure out which values you need to set, I suggest you use an MIB Browser to
find the relevant fields. I personally used qtmib (Qt4-based), as it was the
only one that is packaged on my distro and still managed to compile, but you
should feel free to use any browser that works for you. When you have your
browser open, connect to your PDU using its IP, and find the following fields:

 * `oid_outlets_label_base`: Directory that contains the list of labels.
   In the case of APC's masterswitch, the address is: `enterprises.apc.products.hardware.masterswitch.sPDUOutletControl.sPDUOutletControlTable.sPDUOutletControlEntry.sPDUOutletCtlName`
   which translate to `iso.3.6.1.4.1.318.1.1.4.4.2.1.4`.
 * `oid_outlets_base`: Directory that contains the methods to control the ports, with the index starting from 1.
   In the case of APC's masterswitch, the address is: `enterprises.apc.products.hardware.masterswitch.sPDUOutletControl.sPDUOutletControlTable.sPDUOutletControlEntry.sPDUOutletCtl`
   which translate to `iso.3.6.1.4.1.318.1.1.4.4.2.1.3`.

When you are done, you will need to instruct this driver the mapping between
the wanted state, and the integer value to write. So far, all of them have been
the following mapping:

 * `ON`: 1
 * `OFF`: 2
 * `REBOOT`: 3

Try these values, and change them accordingly!

Once you have collected all this information, feel free to
[open an issue](https://gitlab.freedesktop.org/mupuf/valve-infra/-/issues/new)
to ask us to add this information to the list of drivers. Make sure to include
the curl command line you used to register your PDU!

## Frequently Asked Questions

### Why not use pdudaemon?

We initially wanted to use [pdudaemon](https://github.com/pdudaemon/pdudaemon),
but since it does not allow reading back the state from the PDU, it isn't
possible to make sure that the communication with the PDU is working which
reduces the reliability and debuggability of the system.

Additionally, pdudaemon requires a configuration file, which is contrary to the
objective of the project to be as stateless as possible and leave configuration
outside of the project. The configuration could have been auto-generated
on-the-fly but since there is no way to check if the communication with the PDU
is working, it would make for a terrible interface for users.

Finally, most of the drivers in the project are using a telnet interface rather
than SNMP, which makes them brittle and stateful. See for
[yourself](https://github.com/pdudaemon/pdudaemon/blob/master/pdudaemon/drivers/apc7952.py#L65).

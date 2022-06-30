# Executor

TODO: Document the rest of the executor

## MarsDB

MarsDB is the database for all the runtime data of the CI instance:

 - List of PDUs connected
 - List of test machines
 - List of Gitlab instances where to expose the test machines

Its location is set using the `MARS_DB_FILE` environment variable, and is
live-editable. This means you can edit the file directly and changes will
be reflected instantly in the executor.

New machines will be added automatically when POSTing or PUTing to the
`/api/v1/machine/` REST endpoint, but they won't be useable until
they get associated to a PDU and a PDU port.

Here is an annotated sample file, where `AUTO` means you should not be
modifying this value (and all children of it) while `MANUAL` means that
you are expected to set these values. All the other values should be
machine-generated, for example using the `machine_registration` container:

```
pdus:                                        # List of all the power delivery units (MANUAL)
  APC:                                       # Name of the PDU
    driver: apc_masterswitch                 # The [driver of your PDU](pdu/README.md)
    config:                                  # The configuration of the driver (driver-dependent)
      hostname: 10.0.0.2
duts:                                        # List of all the test machines
  de:ad:be:ef:ca:fe:                         # MAC address of the machine
    base_name: gfx9                          # Most significant characteristic of the machine. Basis of the auto-generated name
    tags:                                    # List of tags representing the machine
    - amdgpu:architecture:GCN5.1
    - amdgpu:family:RV
    - amdgpu:codename:RENOIR
    - amdgpu:gfxversion:gfx9
    - amdgpu:APU
    - amdgpu:pciid:0x1002:0x1636
    ip_address: 192.168.0.42                 # IP address of the machine
    local_tty_device: ttyUSB0                # Test machine's serial port to talk to the gateway
    gitlab:                                  # List of GitLab instances to expose this runner on
      freedesktop:                           # Parameters for the `freedesktop` GitLab instance
        token: <token>                       # Token given by the registration process (AUTO)
        exposed: true                        # Should this machine be exposed on `freedesktop`? (MANUAL)
    pdu: APC                                 # Name of the PDU to contact to turn ON/OFF this machine (MANUAL)
    pdu_port_id: 1                           # ID of the port where the machine is connected (MANUAL)
    pdu_off_delay: 30                        # How long should the PDU port be off when rebooting the machine? (MANUAL)
    ready_for_service: true                  # The machine has been tested and can now be used by users (AUTO)
    is_retired: false                        # The user specified that the machine is no longer in use
    first_seen: 2021-12-22 16:57:08.146275   # When was the machine first seen in CI (AUTO)
gitlab:                                      # Configuration of anything related to exposing the machines on GitLab (MANUAL)
  freedesktop:                               # Name of the gitlab instance
    url: https://gitlab.freedesktop.org/     # URL of the instance
    registration_token: <token>              # Registration token, as found in your GitLab project/group/instance settings
    expose_runners: true                     # Expose the test machines on this instance? Handy for quickly disabling all machines
    maximum_timeout: 21600                   # Maximum timeout allowed for any job running on our test machines
    gateway_runner:                          # Expose a runner that will run locally, and not on test machines
      token: <token>                         # Token given by the registration process (AUTO)
      exposed: true                          # Should the gateway runner be exposed?
```

### Frequently asked questions

#### How do I move runners from one GitLab project to another?

First, we need to remove the runners from the current project:

 1. Open MarsDB's config file
 1. Find the gitlab instance in your configuration file
 1. Set `expose_runners` to false
 1. Save and exit your text editor

Don't forget to exit, as the config file *will* change. Now let's expose the
runners to the new project:

 1. Re-open MarsDB's config file
 1. Find the gitlab instance in your configuration file
 1. Set the new registration token
 1. Set `expose_runners` to true
 1. Save and exit your text editor

That's it!

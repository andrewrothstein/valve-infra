# Valve Traces

Access the Valve traces service through a simple command line interface. This
tool makes sure traces and frames are tagged with information coming from the
machine that captured/ran the trace to avoid any confusion and guesswork as to
what environment is needed to reproduce an issue.

## Installing the tool

This should be as simple as:

    $ pip install --user valvetraces
    $ export PATH=~/.local/bin:$PATH

    $ valvetraces
    usage: valvetraces [-h] [--username USERNAME] [-u URL] {login,list_apps,create_app,list,download,upload_trace} ...

    positional arguments:
      {login,list_apps,create_app,list,download,upload_trace}
        login               Log in the valve traces service
        list_apps           List the applications defined in the service
        create_app          Create a new application in the service
        list                List the traces available in the service
        download            Download a trace from the service
        upload_trace        Upload a trace

    optional arguments:
      -h, --help            show this help message and exit
      --username USERNAME   Username you want to use in the service
      -u URL, --url URL     URL to the service

## Authenticate to the service

First, you need to create an [account on the service](https://linux-perf.steamos.cloud/), then
set a username and password.

You can then check that everything is working by doing:

    $ VALVETRACESPASSWORD=$PASSWORD valvetraces --username $username login

## Interact with traces

Check out `valvetraces --help` for more information.

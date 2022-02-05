# IPXE Server

This README will guide you to install the Valve Infra iPXE server.

## Step 1: Get an nginx-based HTTPS server + Let's encrypt

To complete this step, you will need:

 - A DNS name that you can fully dedicate to the iPXE server. For example,
   ipxe.$domain_name.
 - A server (cheapest option at Linode / Digital Ocean / OVH / other will
   work nicely)

Follow tutorials on how to get nginx + let's encrypt running on the distro
of your choice, as this README would be outdated very quickly.

When done, you should see "It works!" when opening https://ipxe.$domain_name
in your browser, without SSL warnings.

WARNING: iPXE is quite picky about the SSL certificate size, and will reject
anything above 4K. It would seem that the only way to stay under that is to
use a 2048 bits key, and limit the certificate to one domain name.

## Step 2: Set up the iPXE boot server

First, download the latest version of valve-infra:

    $ pwd
    /home/ipxe
    $ git clone https://gitlab.freedesktop.org/mupuf/valve-infra.git
    $ cd valve-infra/ipxe-boot-server
    $ python3 -m venv .venv
    $ .venv/bin/pip install -r requirements.txt

Secondly, [sign up for free to backblaze](https://www.backblaze.com/b2/sign-up.html)
to get 10GB of storage that will be used to host the permanent data of the
different gateways that will be connecting to your iPXE server. You'll then
need to generate an application key with read/write permissions for all
buckets, and write them in /home/ipxe/config.env:

    BBZ_ACCESS_KEY_ID=$keyID
    BBZ_ACCESS_KEY=$applicationKey

Thirdly, let's configure nginx to forward connections to our service by
modifying the virtual host used by https://ipxe.$domain_name:

    location / {
                proxy_pass         http://localhost:8080;
                proxy_redirect     off;
                proxy_set_header   Host $host;
                proxy_set_header   X-Real-IP $remote_addr;
                proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
                proxy_set_header   X-Forwarded-Host $server_name;
                proxy_set_header   X-SSL-Client-Serial $ssl_client_serial;
                proxy_set_header   X-SSL-Client-Fingerprint     $ssl_client_fingerprint;
        }

Finally, set up the systemd unit that will run the service, making sure to
replace $domain_name with the FQDN of the service, and $gateway_name with a
short name that identifies your boot server (nicknames work):

    $ cat /etc/systemd/system/ipxe.service
    [Unit]
    Description=iPXE Boot Service

    [Service]
    User=ipxe
    WorkingDirectory=/home/ipxe/valve-infra/ipxe-boot-server
    ExecStart=/home/ipxe/valve-infra/ipxe-boot-server/.venv/bin/python3 app.py -u https://ipxe.$domain_name -n $gateway_name
    Environment=PYTHONUNBUFFERED=1
    EnvironmentFile=/home/ipxe/config.env
    Restart=on-failure

    [Install]
    WantedBy=default.target

    $ sudo systemctl enable ipxe
    $ sudo systemctl start ipxe

The service should now be ready for NGINX to connect to!

## Step 3: Generate the client certificate CA

The different gateways connecting to the iPXE server are identified using SSL
client certificates, signed by a self-signed certificate hosted on your server.

To generate this certificate, you will need to install `openssl` and run the
following commands:

    $ pwd
    /home/ipxe/valve-infra/ipxe-boot-server/
    $ make ca IPXE_SERVER_FQDN=ipxe.$domain_name
    [...]
    The CA certificates have been written to /home/ipxe/valve-infra/ipxe-boot-server/ca_cert

## Step 4: Configure NGINX to check the client certificates

First, we need to tell nginx to accept the ciphers used by iPXE. To do so, add
the following ciphers to the list of accepted ciphers specified by
ssl_ciphers (may be found in /etc/letsencrypt/options-ssl-nginx.conf):

 - AES-128-CBC:AES-256-CBC:AES256-SHA256
 - AES128-SHA256:AES256-SHA:AES128-SHA

TODO: find a better way to do this, so that we do not modify the file certbot created

Add the following lines to the virtual host used by
https://ipxe.$domain_name:

    ssl_trusted_certificate /home/mupuf/src/valve-infra/ipxe-iso-generator/ca_cert/ca.crt;
    ssl_client_certificate /home/mupuf/src/valve-infra/ipxe-iso-generator/ca_cert/ca.crt;
    ssl_verify_client optional;

Reload nginx (systemctl reload nginx), then try accessing
https://ipxe.$domain_name/boot/ipxe in your browser. It should return:

    Forbidden

    The server requires a client certificate

If so, you have successfully configured your server \o/

## Step 5: Generate ISOs for every gateway you want to have

To generate bootable ISOs for your gateways, you will need:

 - git
 - gcc
 - binutils
 - make (GNU make)
 - perl
 - liblzma-dev
 - mtools
 - xorrisofs
 - syslinux
 - syslinux-efi
 - syslinux-utils
 - mkisolinux

and then execute the following commands:

    $ pwd
    /home/ipxe/valve-infra/ipxe-boot-server/
    $ make CLIENT_NAME="mupuf" IPXE_SERVER_FQDN=ipxe.$domain_name
    [...]
    Generated the bootable image 'ci-gateway-mupuf.iso' (fingerprint baee054e2fea1a1f03bec4a58c863b381765f78a)

WARNING: Treat this ISO as being confidential, and make sure only one copy
exists outside of the server.

Now that the ISO is created, you need to configure the boot parameters for the
gateway:

    $ pwd
    /home/ipxe/valve-infra/ipxe-boot-server/
    $ mkdir -p files/$fingerprint/
    $ $EDITOR files/$fingerprint/boot.ipxe
    #!ipxe

    kernel /files/kernel <kernel cmdline> b2c.extra_args_url="${secrets_url}"
    initrd /files/initrd
    boot
    $ $EDITOR files/$fingerprint/secrets
    # Put here any b2c argument you want to keep secret (fscrypt key, S3 credentials, ...)
    $ cp bzImage files/$fingerprint/kernel
    $ cp my_initramfs.cpio files/$fingerprint/initrd

NOTE: The secrets you put in the `secrets` template file will be exposed at the
`${secrets_url}` for a default time of 60s (use `--secrets-expiration-period` to
change it)

If you don't know what kernel/initrd to use, you may want to look into using
[boot2container](https://gitlab.freedesktop.org/mupuf/boot2container) which
provides you with pre-built kernels and initramfs and let you control the boot
process via the kernel command line.

You may test the generated ISO by running the following command:

    $ make test CLIENT_NAME="mupuf" IPXE_SERVER_FQDN=ipxe.$domain_name SSH_LOCAL_PORT=2222

If you have SSH running on port 22 inside your infra, you will be able to connect
to it by typing the following command:

    $ make connect SSH_LOCAL_PORT=2222

Finally, when everything is working as expected, securely send the gateway ISO
to the administrator of the farm that needs a gateway, and ask them to use the
following `dd` command to copy the ISO to the USB pendrive of their choice and
boot on it.

    # dd if=ci-gateway-mupuf of=/dev/... conv=fsync bs=1M status=progress

That should be all!

## Advanced boot configuration

The template format of the `boot.ipxe` and `secrets` is python's
template strings, a very simple template engine. In a nutshell,
`${variable}` will be substituted with the content of `variable`, and use `$$`
if you want to display a dollar sign. Check out its
[documentation](https://docs.python.org/3/library/string.html#template-strings)
for more details.

The following variables are available in the templates:

 * All:
   * Scratch space for the machine:
     * `s3_endpoint`: endpoint of the S3-compatible Bucket
     * `s3_access_key_id`: login/key id of the S3-compatible bucket
     * `s3_access_key`: password/access key of the S3-compatible bucket
     * `s3_bucket_name`: name of the S3-compatible bucket
   * `client_cert_fingerprint`: Fingerprint of iPXE's client certificate
 * `boot.ipxe`:
   * `secrets_url`: Short-lived and one-time URL containing the rendered `secrets` template

## Keeping the boot configuration in GIT

The data root (`./files/` by default) contains a lot of sensitive files which
are probably best stored in a GIT repository on a private forge. This allows
developers to follow the typical development workflow, by submitting merge
requests when they want to alter the boot configuration of a machine. The
commit log will also make it clear which changes your colleagues have made
while you were on vacation, for example.

Once a change has been made to the GIT repository, it is possible to ask the
web service to update its local copy by calling `/update-cfg`). This feature
requires:

 - git to be installed
 - no credentials to be requested upon calling git fetch, which can be
   achieved using:
   - SSH keys
   - embedding the credentials in the remote URL
     (eg. `https://$login:$password@gitlab.freedesktop.org`)
 - the current branch to have an `upstream` remote/branch set
   (eg. `git branch --set-upstream-to origin/main`).

You can then call `https://${IPXE_SERVER_FQDN}/update-cfg` as part of the
deployment pipeline of your git repository, to make sure that the server
remains in sync with your git repository \o/.

## TODO

 - Have a default target, for machines that do not have a configuration yet

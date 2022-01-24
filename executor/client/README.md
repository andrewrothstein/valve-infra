# Valve GFX CI's executor client

Once installed, this package will add executorctl in your PATH. Here is an
extract of the command line:

```
usage: Executor client run [-h] [-w] [-c CALLBACK] [-t MACHINE_TAGS] [-i MACHINE_ID] [-s SHARE_DIRECTORY] [-j JOB_ID] [-a MINIO_AUTH] [-g MINIO_GROUP] job

positional arguments:
  job                   Job that should be run

options:
  -h, --help            show this help message and exit
  -w, --wait            Wait for a machine to become available if all are busy
  -c CALLBACK, --callback CALLBACK
                        Hostname that the executor will use to connect back to this client, useful for non-trivial routing to the test device
  -t MACHINE_TAGS, --machine-tag MACHINE_TAGS
                        Tag of the machine that should be running the job. Overrides the job's target.
  -i MACHINE_ID, --machine-id MACHINE_ID
                        ID of the machine that should run the job. Overrides the job's target.
  -s SHARE_DIRECTORY, --share-directory SHARE_DIRECTORY
                        Directory that will be forwarded to the job, and whose changes will be forwarded back to
  -j JOB_ID, --job-id JOB_ID
                        Identifier for the job, if you have one already.
  -a MINIO_AUTH, --minio-auth MINIO_AUTH
                        MinIO credentials that has access to all the groups specified using '-g'
  -g MINIO_GROUP, --minio-group MINIO_GROUP
                        Add the MinIO job user to the specified group. Requires valid credentials specified using '--minio-auth' which already have access this group
```

TODO: Properly document the job description

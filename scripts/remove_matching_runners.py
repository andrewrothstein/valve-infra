#!/usr/bin/env python

import argparse
import gitlab
import os
import sys
import re


if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog='Gitlab runner admin tool')
    parser.add_argument("-u", "--url", default=os.environ.get('GITLAB_URL', 'https://gitlab.freedesktop.org'),
                        help='URL of Gitlab instance')
    parser.add_argument("-t", "--token", default=os.environ.get('GITLAB_ACCESS_TOKEN', None),
                        help='Access token to Gitlab')
    parser.add_argument("-r", "--regex", required=True,
                        help='Regex to match against runner names')
    args = parser.parse_args()

    gl = gitlab.Gitlab(url=args.url, private_token=args.token)
    prog = re.compile(args.regex)

    matching_runners = []
    for runner in gl.runners.list(all=True):
        if prog.match(runner.description):
            matching_runners.append(runner)

    if len(matching_runners) == 0:
        print("No matching runners")
        sys.exit(1)

    choice = input('WARNING: Going to delete %d runners:\n%s\nOK ?' % (
        len(matching_runners),
        '\n'.join([r.description for r in matching_runners])))
    if choice.strip().lower() in ["y", "yes", "ok"]:
        for r in matching_runners:
            r.delete()
    else:
        print('No action taken')

#!/usr/bin/env python3

import os
import re
import sys
import json
import getopt
import urllib.error
import urllib.request
import comanage_utils as utils


SCRIPT = os.path.basename(__file__)
ENDPOINT = "https://registry.cilogon.org/registry/"
USER = "co_7.group_fixup"
OSG_CO_ID = 7


_usage = f"""\
usage: [PASS=...] {SCRIPT} [OPTIONS] COGroupNameOrId ProjectName

OPTIONS:
  -u USER[:PASS]      specify USER and optionally PASS on command line
  -c OSG_CO_ID        specify OSG CO ID (default = {OSG_CO_ID})
  -d passfd           specify open fd to read PASS
  -f passfile         specify path to file to open and read PASS
  -e ENDPOINT         specify REST endpoint
                        (default = {ENDPOINT})
  -h                  display this help text

Adds an identifier of type ospoolproject named Yes-ProjectName to
a COGroup based on its Name or CO Group Id.

PASS for USER is taken from the first of:
  1. -u USER:PASS
  2. -d passfd (read from fd)
  3. -f passfile (read from file)
  4. read from $PASS env var
"""

def usage(msg=None):
    if msg:
        print(msg + "\n", file=sys.stderr)

    print(_usage, file=sys.stderr)
    sys.exit()


class Options:
    endpoint  = ENDPOINT
    osg_co_id = OSG_CO_ID
    user      = USER
    authstr   = None
    gid       = None
    gname     = None
    project   = None


options = Options()


# script-specific functions

def add_project_identifier_to_group(gid, project_name):
    identifier_name = "Yes-%s" % project_name
    type_ = "ospoolproject"
    return utils.add_identifier_to_group(gid, type_, identifier_name, options.endpoint, options.authstr)


def gname_to_gid(gname):
    resp_data = utils.get_osg_co_groups(options.osg_co_id, options.endpoint, options.authstr)
    groups = utils.get_datalist(resp_data, "CoGroups")
    matching = [ g for g in groups if g["Name"] == gname ]

    if len(matching) > 1:
        raise RuntimeError("Multiple groups found with Name '%s'" % gname)
    elif not matching:
        raise RuntimeError("No group found with Name '%s'" % gname)

    group = matching[0]
    return group["Id"]


# CLI


def parse_options(args):
    try:
        ops, args = getopt.getopt(args, 'u:c:d:f:e:h')
    except getopt.GetoptError:
        usage()

    if len(args) != 2:
        usage()

    cogroup, project = args
    if re.fullmatch(r'\d+', cogroup):
        options.gid = int(cogroup)
    else:
        options.gname = cogroup
    options.project = project

    passfd = None
    passfile = None

    for op, arg in ops:
        if op == '-h': usage()
        if op == '-u': options.user      = arg
        if op == '-c': options.osg_co_id = int(arg)
        if op == '-d': passfd            = int(arg)
        if op == '-f': passfile          = arg
        if op == '-e': options.endpoint  = arg

    try:
        user, passwd = utils.getpw(options.user, passfd, passfile)
        options.authstr = utils.mkauthstr(user, passwd)
    except PermissionError:
        usage("PASS required")


def main(args):
    parse_options(args)

    if options.gname:
        options.gid = gname_to_gid(options.gname)
    else:
        options.gname = utils.get_co_group(options.gid, options.endpoint, options.authstr)["Name"]

    print('Creating new Identifier for project "%s"\n'
          'for CO Group "%s" (%s)'
          % (options.project, options.gname, options.gid))
    print("")

    resp = add_project_identifier_to_group(options.gid, options.project)

    print("Server Response:")
    print(json.dumps(resp, indent=2, sort_keys=True))

    new_identifier = utils.get_identifier(resp["Id"], options.endpoint, options.authstr)
    print("")
    print("New Identifier Object:")
    print(json.dumps(new_identifier, indent=2, sort_keys=True))

    # no exceptions, must have worked
    print("")
    print(":thumbsup:")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (RuntimeError, urllib.error.HTTPError) as e:
        print(e, file=sys.stderr)
        sys.exit(1)


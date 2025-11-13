#!/usr/bin/env python3

import os
import re
import sys
import getopt
import collections
import urllib.error
import urllib.request
import comanage_utils as utils


SCRIPT = os.path.basename(__file__)
ENDPOINT = "https://registry.cilogon.org/registry/"
USER = "co_7.group_fixup"
OSG_CO_ID = 7
LDAP_PROV_ID = 6


_usage = f"""\
usage: [PASS=...] {SCRIPT} [OPTIONS]

OPTIONS:
  -u USER[:PASS]      specify USER and optionally PASS on command line
  -c OSG_CO_ID        specify OSG CO ID (default = {OSG_CO_ID})
  -d passfd           specify open fd to read PASS
  -f passfile         specify path to file to open and read PASS
  -e ENDPOINT         specify REST endpoint
                        (default = {ENDPOINT})
  -p LDAP_PROV_ID     LDAP Provisioning Target ID (default = {LDAP_PROV_ID})
  -a                  show all UnixCluster autogroups, not just misnamed ones
  -i COGroupId        show fixup info for a specific CO Group
  -x COGroupId        run UnixCluster Group fixups for given CO Group Id
  --fix-all           run UnixCluster Group fixups for all misnamed groups
  -h                  display this help text

Run without options to display misnamed UnixCluster autogroups.
Run with -a to include UnixCluster autogroups with fixed names, too.
Run with -i to display only a given CO Group.
Run with -x to fixup a given CO Group.

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
    prov_id   = LDAP_PROV_ID
    user      = USER
    authstr   = None
    fix_gid   = None
    info_gid  = None
    showall   = False
    fix_all   = False


options = Options()


# api call results massagers


def get_unixcluster_autogroups():
    groups = utils.get_osg_co_groups(options.osg_co_id, options.endpoint, options.authstr)
    return [ g for g in groups["CoGroups"]
             if "automatically by UnixCluster" in g["Description"] ]


def get_misnamed_unixcluster_groups():
    groups = utils.get_osg_co_groups(options.osg_co_id, options.endpoint, options.authstr)
    return [ g for g in groups["CoGroups"]
             if "UnixCluster Group" in g["Name"] ]


def _osgid_sortkey(i):
    return int(i["Identifier"])

def get_identifiers_to_delete(identifiers):
    by_type = collections.defaultdict(list)
    ids_to_delete = []

    for i in identifiers:
        by_type[i["Type"]].append(i)

    if len(by_type["osggid"]) == 2:
        min_identifier = min(by_type["osggid"], key=_osgid_sortkey)
        ids_to_delete.append(min_identifier["Id"])

    for i in by_type["osggroup"]:
        if i["Identifier"].endswith("unixclustergroup"):
            ids_to_delete.append(i["Id"])

    return ids_to_delete


def get_fixed_unixcluster_group_name(name):
    m = re.search(r'^(.*) UnixCluster Group', name)
    return m.group(1) if m else name


# display functions


def show_misnamed_unixcluster_group(group):
    print('CO {CoId} Group {Id}: "{Name}"'.format(**group))
    oldname = group["Name"]
    newname = get_fixed_unixcluster_group_name(oldname)
    if oldname != newname:
        print('  ** Rename group to: "%s"' % newname)
    show_group_identifiers(group["Id"])
    print("")


def show_all_unixcluster_groups():
    groups = get_unixcluster_autogroups()
    for group in groups:
        show_misnamed_unixcluster_group(group)


def show_one_unixcluster_group(gid):
    group = utils.get_co_group(gid, options.endpoint, options.authstr)
    show_misnamed_unixcluster_group(group)


def show_misnamed_unixcluster_groups():
    groups = get_misnamed_unixcluster_groups()
    for group in groups:
        show_misnamed_unixcluster_group(group)


def show_group_identifiers(gid):
    resp_data = utils.get_co_group_identifiers(gid, options.endpoint, options.authstr)
    identifiers = utils.get_datalist(resp_data, "Identifiers")
    for i in identifiers:
        print('   - Identifier {Id}: ({Type}) "{Identifier}"'.format(**i))

    ids_to_delete = get_identifiers_to_delete(identifiers)
    if ids_to_delete:
        print('  ** Identifier Ids to delete: %s' % ', '.join(ids_to_delete))


# fixup functions


def fixup_unixcluster_group(gid):
    group = utils.get_co_group(gid, options.endpoint, options.authstr)
    oldname = group["Name"]
    newname = get_fixed_unixcluster_group_name(oldname)
    resp_data = utils.get_co_group_identifiers(gid, options.endpoint, options.authstr)
    identifiers = utils.get_datalist(resp_data, "Identifiers")
    ids_to_delete = get_identifiers_to_delete(identifiers)

    show_misnamed_unixcluster_group(group)
    if oldname != newname:
        utils.rename_co_group(gid, group, newname, options.endpoint, options.authstr)
    for id_ in ids_to_delete:
        utils.delete_identifier(id_, options.endpoint, options.authstr)

    utils.provision_group(gid, options.prov_id, options.endpoint, options.authstr)
    utils.provision_group_members(gid, options.prov_id, options.endpoint, options.authstr)

    # http errors raise exceptions, so at this point we apparently succeeded
    print(":thumbsup:")
    return 0


def fixup_all_unixcluster_groups():
    groups = get_misnamed_unixcluster_groups()
    for group in groups:
        fixup_unixcluster_group(group["Id"])


# CLI


def parse_options(args):
    try:
        ops, args = getopt.getopt(args, 'u:c:d:f:e:x:i:p:ah', ["fix-all"])
    except getopt.GetoptError:
        usage()

    if args:
        usage("Extra arguments: %s" % repr(args))

    passfd = None
    passfile = None

    for op, arg in ops:
        if op == '-h': usage()
        if op == '-u': options.user      = arg
        if op == '-c': options.osg_co_id = int(arg)
        if op == '-d': passfd            = int(arg)
        if op == '-f': passfile          = arg
        if op == '-e': options.endpoint  = arg
        if op == '-x': options.fix_gid   = int(arg)
        if op == '-i': options.info_gid  = int(arg)
        if op == '-p': options.prov_id   = int(arg)
        if op == '-a': options.showall   = True

        if op == '--fix-all': options.fix_all = True

    try:
        user, passwd = utils.getpw(options.user, passfd, passfile)
        options.authstr = utils.mkauthstr(user, passwd)
    except PermissionError:
        usage("PASS required")


def main(args):
    parse_options(args)

    if options.fix_gid:
        return fixup_unixcluster_group(options.fix_gid)
    elif options.fix_all:
        return fixup_all_unixcluster_groups()
    elif options.showall:
        show_all_unixcluster_groups()
    elif options.info_gid:
        show_one_unixcluster_group(options.info_gid)
    else:
        show_misnamed_unixcluster_groups()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (RuntimeError, urllib.error.HTTPError) as e:
        print(e, file=sys.stderr)
        sys.exit(1)

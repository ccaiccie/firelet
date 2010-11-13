#!/usr/bin/env python

# Firelet - Distributed firewall management.
# Copyright (C) 2010 Federico Ceratto
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# Firelet Command Line Interface

from getpass import getpass
import logging as log
from sys import argv, exit

from confreader import ConfReader
from flcore import GitFireSet, DemoGitFireSet, Users,  __version__
from flutils import cli_args

#   commands
#
#   save <desc>
#   reset
#   version
#       list
#       rollback <version>
#   check
#   deploy
#   user
#       add <....>
#       del <num>
#       list
#   rule
#       add <....>
#       del <num>
#       list
#   hostgroup
#       add <...>
#       del <num>
#       list
#   network
#       add <...>
#       del <num>
#       list
#

def give_help():
    #TODO
    say("""
    Commands:

    user    - web interface user management
        list
        add  <login> <role>
        del <num>
    save    - save the current configuration
    reset   - revert the configuration to the last saved state
    version
    save_needed
    check
    deploy
    rule
        list
        add
        del
        enable <id>
        disable <id>
    host
        list
        add
        del
    hostgroup
        ...
    user
        list
        add <name> <group> <email>
        del
    """)

def help(s=None):
    if s:
        say(s)
    give_help()
    exit(1)


def deletion(table):
    if not a3:
        help()
    try:
        rid = int(a3)
        rd.delete(table, rid)
    except:
        pass
        #TODO

def prettyprint(li):
    """Pretty-print as a table"""
    keys = sorted(li[0].keys())
    t = [keys]
    for d in li:
        m =[d[k] for k in keys]
        m = map(str, m)
        t.append(m)

    cols = zip(*t)
    cols_sizes = [(max(map(len, i))) for i in cols] # get the widest entry in each column

    for m in t:
        s = " | ".join((item.ljust(pad) for item, pad in zip(m, cols_sizes)))
        say(s)

#        def j((n, li)):
#            return "%d  " % n + "  ".join((item.ljust(pad) for item, pad in zip(li, cols_sizes) ))
#        return '\n'.join(map(j, enumerate(self)))

def say(s):
    print s

def open_fs(fn):
    """Read configuration and instance the required FireSet"""
    # read configuration,
    try:
        conf = ConfReader(fn=fn)
    except Exception, e:
        log.error("Exception %s while reading configuration file '%s'" % (e, fn))
        exit(1)

    fs = GitFireSet(repodir=conf.data_dir)
    return (conf.data_dir, fs)


def main(mockargs=None):

    if mockargs:
        opts, args = cli_args(args=mockargs)
    else:
        opts, args = cli_args(args=mockargs)

    whisper = say
    if opts.quiet:
        whisper = lambda x: None

    whisper( "Firelet %s CLI." % __version__)

    a1, a2, a3, a4, a5, a6 = args+ [None] * (6 - len(args))

    if not a1:
        help()

    repodir, fs = open_fs(opts.conffile.strip())

    if a1 == 'save':
        if a3 or not a2:
            help()
        fs.save(str(a2))
        say('Configuration saved. Message: "%s"' % str(a2))

    elif a1 == 'reset':
        if a2:
            help()
        fs.reset()
        say('Reset complete.')

    elif a1 == 'version':
        if a2 == 'list' or None:
            for user, date, msg, commit_id in fs.version_list():
                s = '%s | %s | %s | %s |' % (commit_id, date, user, msg[0])
                say(s)
        elif a2 == 'rollback':
            if not a3:
                help()
            try:
                n = int(a3)
                fs.rollback(n=n)
            except ValueError:
                fs.rollback(commit_id=a3)
        else:
            help()

    elif a1 == 'save_needed':
        if fs.save_needed():
            say('Yes')
            if __name__ == '__main__':
                exit(0)
        else:
            say('No')
            if __name__ == '__main__':
                exit(1)

    elif a1 == 'check':
        if a2: help()
        raise NotImplementedError

    elif a1 == 'compile':
        if a2: help()
        c = fs.compile()
        for li in c:
            say(li)

    elif a1 == 'deploy':
        if a2: help()
        fs.deploy()

    elif a1 == 'rule':
        if a2 == 'list' or None:
            prettyprint(fs.rules)
        elif a2 == 'add':
            raise NotImplementedError
        elif a2 == 'del':
            deletion('rules')
        elif a2 == 'enable':
            i = int(a3)
            fs.rules.enable(i)
            say('Rule %d enabled.' %i)
        elif a2 == 'disable':
            i = int(a3)
            fs.rules.disable(i)
            say('Rule %d disabled.' %i)

    elif a1 == 'hostgroup':
        if a2 == 'list' or None:
            prettyprint(fs.hostgroups)
        elif a2 == 'add':
            raise NotImplementedError
        elif a2 == 'del':
            deletion('hostgroups')

    elif a1 == 'host':
        if a2 == 'list' or None:
            prettyprint(fs.hosts)
        elif a2 == 'add':
            raise NotImplementedError
        elif a2 == 'del':
            deletion('hosts')

    elif a1 == 'network':
        if a2 == 'list' or None:
            prettyprint(fs.networks)
        elif a2 == 'add':
            raise NotImplementedError
        elif a2 == 'del':
            deletion('networks')

    elif a1 == 'service':
        if a2 == 'list' or None:
            prettyprint(fs.services)
        elif a2 == 'add':
            raise NotImplementedError
        elif a2 == 'del':
            deletion('services')

    elif a1 == 'user':
        users = Users(d=repodir)
        if a2 == 'list' or None:
            whisper("Name           Role            Email ")
            for name, (role, secret, email) in users._users.iteritems():
                say("%-14s %-15s %s" % (name, role, email))
        elif a2 == 'add':
            if not a3:
                help("Missing username.")
            if not a4:
                help("Missing role.")
            if not a5:
                help("Missing email.")
            pwd = getpass('Enter new password: ')
            users.create(a3, a4, pwd, email=a5)
        elif a2 == 'del':
            if not a3:
                help("Missing username.")
            users.delete(a3)
        elif a2 == 'validatepwd':
            if not a3:
                help("Missing username.")
            pwd = getpass('Enter password: ')
            users.validate(a3, pwd)
        else:
            give_help()
            exit(1)


    else:
        give_help()
        exit(0)

    exit(0)

if __name__ == '__main__':
    main()


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

from argparse import ArgumentParser
from beaker.middleware import SessionMiddleware
import bottle
from bottle import abort, route, static_file, run, view, request
from bottle import debug as bottle_debug
from collections import defaultdict
from datetime import datetime
from setproctitle import setproctitle
from sys import exit
from time import time, sleep, localtime

from confreader import ConfReader
import mailer
from flcore import Alert, GitFireSet, DemoGitFireSet, Users, clean
from flmap import draw_png_map, draw_svg_map
from flutils import flag, extract_all, get_rss_channels

from bottle import HTTPResponse, HTTPError

import logging
log = logging.getLogger(__name__)

#TODO: add API version number
#TODO: rewrite say() as a custom log target
#TODO: full rule checking upon Save
#TODO: move fireset editing in flcore
#TODO: setup three roles
#TODO: store a local copy of the deployed confs
#              - compare in with the fetched conf
#              - show it on the webapp

#TODO: new rule creation

#FIXME: first rule cannot be disabled
#TODO: insert  change description in save message
#FIXME: Reset not working

# Setup Python error logging

class LoggedHTTPError(bottle.HTTPResponse):
    """Log a full traceback"""
    def __init__(self, code=500, output='Unknown Error', exception=None,
            traceback=None, header=None):
        super(bottle.HTTPError, self).__init__(output, code, header)
        log.error("""Internal error '%s':\n  Output: %s\n  Header: %s\n  %s \
--- End of traceback ---""" % (exception, output, header, traceback))

    def __repr__(self):
        ts = datetime.now()
        return "%s: An error occourred and has been logged." % ts

bottle.HTTPError = LoggedHTTPError


# Global variables

msg_list = []

# Miscellaneous functions

def say(s, level='info'):
    """Generate a message. level can be: info, warning, alert"""
    if level == 'error':
        level = 'alert'
    log.debug(s)
    ts = datetime.now()
    msg_list.append((level, ts, s))
    if len(msg_list) > 10:
        msg_list.pop(0)

def ack(s=None):
    """Acknowledge successful processing and returns ajax confirmation."""
    if s:
        say(s, level="success")
    return {'ok': True}

def ret_warn(s=None):
    """Generate warn message and returns ajax 'ok: False'."""
    if s:
        say(s, level="warning")
    return {'ok': False}

def ret_alert(s=None):
    """Generate alert message and returns ajax 'ok: False'."""
    if s:
        say(s, level="alert")
    return {'ok': False}

def pg(name, default=''):
    """Retrieve an element from a POST request"""
    s = request.POST.get(name, default)[:64]
    return clean(s).strip()

def pg_list(name, default=''):
    """Retrieve a serialized (comma-separated) list from a POST request.
    Duplicated elements are removed"""
    # FIXME: a hostgroup containing hundreds of hosts may exceed POST size
    s = request.POST.get(name, default)
    li = clean(s).strip().split(',')
    return list(set(li))

def int_pg(name, default=None):
    """Retrieve an element from a POST request and returns it as an integer"""
    v = request.POST.get(name, default)
    if v == '':
        return None
    try:
        return int(v)
    except:
        raise Exception, "Expected int as POST parameter, got string: '%s'." % v

def pcheckbox(name):
    """Retrieve a checkbox status from a POST request generated by serializeArray() and returns '0' or '1' """
    if name in request.POST:
        return '1'
    return '0'


# # #  web services  # # #


# #  authentication  # #

def _require(role='readonly'):
    """Ensure the user has the required role (or higher).
    Order is: admin > editor > readonly
    """
    m = {'admin': 15, 'editor': 10, 'readonly': 5}
    s = bottle.request.environ.get('beaker.session')
    if not s:
        say("User needs to be authenticated.", level="warning")
        #TODO: not really explanatory in a multiuser session.
        raise Alert, "User needs to be authenticated."
    myrole = s.get('role', None)
    if not myrole:
        raise Alert, "User needs to be authenticated."
    if m[myrole] >= m[role]:
        return
    say("An account with '%s' level or higher is required." % repr(role))
    raise Exception


@bottle.route('/login', method='POST')
def login():
    """Log user in if authorized"""
    s = bottle.request.environ.get('beaker.session')
    if 'username' in s:  # user is authenticated <--> username is set
        say("Already logged in as \"%s\"." % s['username'])
        return {'logged_in': True}
    user = pg('user', '')
    pwd = pg('pwd', '')
    try:
        users.validate(user, pwd)
        role = users._users[user][0]
        say("User %s with role %s logged in." % (user, role), level="success")
        s['username'] = user
        s['role'] = role
        s = bottle.request.environ.get('beaker.session')
        s.save()
        bottle.redirect('')
    except (Alert, AssertionError), e:
        say("Login denied for \"%s\": %s" % (user, e), level="warning")
        log.debug("Login denied for \"%s\": %s" % (user, e))
        bottle.redirect('')

@bottle.route('/logout')
def logout():
    """Log user out"""
    _require()
    s = bottle.request.environ.get('beaker.session')
    u = s.get('username', None)
    if u:
        say('User %s logged out.' % u)
    s.delete()
    bottle.redirect('')

#
#class WebApp(object):
#
#def __init__(self, conf):
#    self.conf = conf
#    self.messages = []

@bottle.route('/messages')
@view('messages')
def messages():
    """Populate log message pane"""
    _require()
    messages = [ (lvl, ts.strftime("%H:%M:%S"), msg) for lvl, ts, msg in msg_list]
    return dict(messages=messages)

@bottle.route('/')
@view('index')
def index():
    """Serve main page"""
    _require()
    s = bottle.request.environ.get('beaker.session')
    logged_in = True if s and 'username' in s else False

    try:
        title = conf.title
    except:
        title = 'test'
    return dict(msg=None, title=title, logged_in=logged_in)

# #  tables interaction  # #
#
# GETs are used to list all table contents
# POSTs are used to make changes or to populate editing forms
# POST "verbs" are sent using the "action" key, and the "rid" key
# specifies the target:
#   - delete
#   - moveup/movedown/enable/disable   see ruleset()
#   - edit: updates an element if rid is not null, otherwise creates
#             a new one

@bottle.route('/ruleset')
@view('ruleset')
def ruleset():
    """Serve ruleset tab"""
    _require()
    return dict(rules=enumerate(fs.rules))

@bottle.route('/ruleset', method='POST')
def ruleset():
    """Make changes on a rule."""
    _require('editor')
    action = pg('action', '')
    rid = int_pg('rid')
    assert rid, "Item number not provided"
    try:
        if action == 'delete':
            item = fs.fetch('rules', rid)
            name = item.name
            fs.delete('rules', rid)
            return ack("Rule %s deleted." % name)
        elif action == 'moveup':
            fs.rules.moveup(rid)
            return ack("Rule moved up.")
        elif action == 'movedown':
            fs.rules.movedown(rid)
            return ack("Rule moved down.")
        elif action == 'enable':
            fs.rules.enable(rid)
            return ack("Rule %d enabled." % rid)
        elif action == 'disable':
            fs.rules.disable(rid)
            return ack("Rule %d disabled." % rid)
        elif action == "save":
            fields = ('name', 'src', 'src_serv', 'dst', 'dst_serv', 'desc')
            d = dict((f, pg(f)) for f in fields)
            d['enabled'] = flag(pg('enabled'))
            d['action'] = pg('rule_action')
            d['log_level'] = pg('log')
            fs.rules.update(d, rid=pg('rid'), token=pg('token'))
        else:
            log.error('Unknown action requested: "%s"' % action)
    except Exception, e:
        say("Unable to %s rule n. %s - %s" % (action, rid, e), level="alert")
        abort(500)

@bottle.route('/ruleset_form', method='POST')
@view('ruleset_form')
def ruleset_form():
    """Generate an inline editing form for a rule"""
    _require()
    rid = int_pg('rid')
    rule = fs.rules[rid]
    services = ['*'] + [s.name for s in fs.services]
    objs = ["%s:%s" % (h.hostname, h.iface) for h in fs.hosts] + \
        [hg.name for hg in fs.hostgroups] + \
        [n.name for n in fs.networks]
    return dict(rule=rule, rid=rid, services=services, objs=objs)

@bottle.route('/sib_names', method='POST')
def sib_names():
    """Return a list of all the available siblings for a hostgroup being created or edited.
    Used in the ajax form."""
    _require()
    sib_names = fs.list_sibling_names()
    return dict(sib_names=sib_names)

@bottle.route('/hostgroups')
@view('hostgroups')
def hostgroups():
    """Generate the HTML hostgroups table"""
    _require()
    return dict(hostgroups=enumerate(fs.hostgroups))

@bottle.route('/hostgroups', method='POST')
def hostgroups():
    """Add/edit/delete a hostgroup"""
    _require('editor')
    action = pg('action', '')
    rid = int_pg('rid')
    try:
        if action == 'delete':
            item = fs.fetch('hostgroups', rid)
            name = item.name
            fs.delete('hostgroups', rid)
            return ack("Hostgroup %s deleted." % name)
        elif action == 'save':
            childs = pg_list('siblings')
            d = {'name': pg('name'),
                    'childs': childs}
            if rid == None:     # new item
                fs.hostgroups.add(d)
                return ack('Hostgroup %s added.' % d['name'])
            else:                     # update item
                fs.hostgroups.update(d, rid=rid, token=pg('token'))
                return ack('Hostgroup %s updated.' % d['name'])
        elif action == 'fetch':
            item = fs.fetch('hostgroups', rid)
            return item.attr_dict()
        else:
            log.error('Unknown action requested: "%s"' % action)
    except Exception, e:
        say("Unable to %s hostgroup n. %s - %s" % (action, rid, e), level="alert")
        abort(500)

@bottle.route('/hosts')
@view('hosts')
def hosts():
    """Serve hosts tab"""
    _require()
    return dict(hosts=enumerate(fs.hosts))

@bottle.route('/hosts', method='POST')
def hosts():
    """Add/edit/delete a host"""
    _require('editor')
    action = pg('action', '')
    rid = int_pg('rid')
    try:
        if action == 'delete':
            h = fs.fetch('hosts', rid)
            name = h.hostname
            fs.delete('hosts', rid)
            say("Host %s deleted." % name, level="success")
        elif action == 'save':
            d = {}
            for f in ('hostname', 'iface', 'ip_addr', 'masklen'):
                d[f] = pg(f)
            for f in ('local_fw', 'network_fw', 'mng'):
                d[f] = pcheckbox(f)
            d['routed'] = pg_list('routed')
            if rid == None:     # new host
                fs.hosts.add(d)
                return ack('Host %s added.' % d['hostname'])
            else:   # update host
                fs.hosts.update(d, rid=rid, token=pg('token'))
                return ack('Host %s updated.' % d['hostname'])
        elif action == 'fetch':
            h = fs.fetch('hosts', rid)
            d = h.attr_dict()
            for x in ('local_fw', 'network_fw', 'mng'):
                d[x] = int(d[x])
            return d
        else:
            raise Exception, 'Unknown action requested: "%s"' % action
    except Exception, e:
        say("Unable to %s host n. %s - %s" % (action, rid, e), level="alert")
        abort(500)



@bottle.route('/net_names', method='POST')
def net_names():
    """Serve networks names"""
    _require()
    nn = [n.name for n in fs.networks]
    return dict(net_names=nn)

@bottle.route('/networks')
@view('networks')
def networks():
    """Generate the HTML networks table"""
    _require()
    return dict(networks=enumerate(fs.networks))

@bottle.route('/networks', method='POST')
def networks():
    """Add/edit/delete a network"""
    _require('editor')
    action = pg('action', '')
    rid = int_pg('rid')
    try:
        if action == 'delete':
            item = fs.fetch('networks', rid)
            name = item.name
            fs.delete('networks', rid)
            say("Network %s deleted." % name, level="success")
        elif action == 'save':
            d = {}
            for f in ('name', 'ip_addr', 'masklen'):
                d[f] = pg(f)
            if rid == None:     # new item
                fs.networks.add(d)
                return ack('Network %s added.' % d['name'])
            else:                     # update item
                fs.networks.update(d, rid=rid, token=pg('token'))
                return ack('Network %s updated.' % d['name'])
        elif action == 'fetch':
            item = fs.fetch('networks', rid)
            return item.attr_dict()
        else:
            log.error('Unknown action requested: "%s"' % action)
    except Exception, e:
        say("Unable to %s network n. %s - %s" % (action, rid, e), level="alert")
        abort(500)



@bottle.route('/services')
@view('services')
def services():
    """Generate the HTML services table"""
    _require()
    return dict(services=enumerate(fs.services))

@bottle.route('/services', method='POST')
def services():
    """Add/edit/delete a service"""
    _require('editor')
    action = pg('action', '')
    rid = int_pg('rid')
    try:
        if action == 'delete':
            item = fs.fetch('services', rid)
            name = item.name
            fs.delete('services', rid)
            say("service %s deleted." % name, level="success")
        elif action == 'save':
            d = {'name': pg('name'),
                    'protocol': pg('protocol')}
            if d['protocol'] in ('TCP', 'UDP'):
                d['ports'] = pg('ports')
            elif d['protocol'] == 'ICMP':
                d['ports'] = pg('icmp_type')
            else:
                d['ports'] = ''
            if rid == None:     # new item
                fs.services.add(d)
                return ack('Service %s added.' % d['name'])
            else:                     # update item
                fs.services.update(d, rid=rid, token=pg('token'))
                return ack('Service %s updated.' % d['name'])
        elif action == 'fetch':
            item = fs.fetch('services', rid)
            return item.attr_dict()
        else:
            log.error('Unknown action requested: "%s"' % action)
    except Exception, e:
        say("Unable to %s service n. %s - %s" % (action, rid, e), level="alert")
        abort(500)


# management commands

@bottle.route('/manage')
@view('manage')
def manage():
    """Serve manage tab"""
    _require()
    s = bottle.request.environ.get('beaker.session')
    myrole = s.get('role', '')
    cd = True if myrole == 'admin' else False
    return dict(can_deploy=cd)

@bottle.route('/save_needed')
def save_needed():
    """Serve fs.save_needed() output"""
    _require()
    return {'sn': fs.save_needed()}

@bottle.route('/save', method='POST')
def savebtn():
    """Save configuration"""
    _require()
    msg = pg('msg', '')
    if not fs.save_needed():
        ret_warn('Save not needed.')
    say("Commit msg: \"%s\". Saving configuration..." % msg)
    saved = fs.save(msg)
    ack("Configuration saved: \"%s\"" % msg)

@bottle.route('/reset', method='POST')
def resetbtn():
    """Reset configuration"""
    _require()
    if not fs.save_needed():
        ret_warn('Reset not needed.')
    say("Resetting configuration changes...")
    fs.reset()
    ack('Configuration reset.')

@bottle.route('/check', method='POST')
@view('rules_diff_table')
def checkbtn():
    """Check configuration"""
    _require()
    say('Configuration check started...')
    try:
        diff_dict = fs.check()
    except Alert, e:
        say("Check failed: %s" % e,  level="alert")
        return dict(diff_dict="Check failed: %s" % e)
    except Exception, e:
        import traceback # TODO: remove traceback
        log.debug(traceback.format_exc())
        return
    say('Configuration check successful.', level="success")
    return dict(diff_dict=diff_dict)


@bottle.route('/deploy', method='POST')
def deploybtn():
    """Deploy configuration"""
    _require('admin')
    say('Configuration deployment started...')
    say('Compiling firewall rules...')
    try:
        fs.deploy()
    except Alert, e:
        ret_alert("Compilation failed: %s" % e)
    ack('Configuration deployed.')

@bottle.route('/version_list')
@view('version_list')
def version_list():
    """Serve version list"""
    _require()
    li = fs.version_list()
    return dict(version_list=li)

@bottle.route('/version_diff', method='POST')
@view('version_diff')
def version_diff():
    """Serve version diff"""
    _require()
    cid = pg('commit_id') #TODO validate cid?
    li = fs.version_diff(cid)
    if li:
        return dict(li=li)
    return dict(li=(('(No changes.)', 'title')))

@bottle.route('/rollback', method='POST')
def rollback():
    """Rollback configuration"""
    _require('admin')
    cid = pg('commit_id') #TODO validate cid?
    fs.rollback(cid)
    ack("Configuration rolled back.")

# serving static files

@bottle.route('/static/:filename#[a-zA-Z0-9_\.?\/?]+#')
def static(filename):
    """Serve static content"""
    _require()
    bottle.response.headers['Cache-Control'] = 'max-age=3600, public'
    if filename == '/jquery-ui.js':
        return static_file('jquery-ui/jquery-ui.js',
            '/usr/share/javascript/') #TODO: support other distros
    elif filename == 'jquery.min.js':
        return static_file('jquery/jquery.min.js', '/usr/share/javascript/')
    elif filename == 'jquery-ui.custom.css': #TODO: support version change
        return static_file('jquery-ui/css/smoothness/jquery-ui-1.7.2.custom.css',
            '/usr/share/javascript/')
    else:
        return static_file(filename, 'static')


@bottle.route('/favicon.ico')
def favicon():
    static_file('favicon.ico', 'static')

@bottle.route('/map') #FIXME: the SVG map is not shown inside the jQuery tab.
def flmap():
    return """<img src="map.png" width="700px" style="margin: 10px">"""

@bottle.route('/map.png')
def flmap_png():
    bottle.response.content_type = 'image/png'
    return draw_png_map(fs)

@bottle.route('/svgmap')
def flmap_svg():
    bottle.response.content_type = 'image/svg+xml'
    return draw_svg_map(fs)

#TODO: provide PNG fallback for browser without SVG support?
#TODO: html links in the SVG map

# RSS feeds

@bottle.route('/rss')
@view('rss_index')
def rss_index():
    """Return RSS index page"""
    # FIXME: available to non-authenticated users - also, trying to fetch the
    # rss.png icon generates an auth Alert.
    return dict()


@bottle.route('/rss/:channel')
@view('rss')
def rss_channels(channel=None):
    """Generate RSS feeds for different channels"""
    # FIXME: available to non-authenticated users
    bottle.response.content_type = 'application/rss+xml'
    if channel.endswith('.xml') or channel.endswith('.rss'):
        channel = channel[:-4]
    if conf.public_url:
        url = conf.public_url.rstrip('/') + '/rss'
    else:
        url = "https://%s:%s/rss" % (conf.listen_address, conf.listen_port)

    return get_rss_channels(channel, url, msg_list=msg_list)




def main():
    global conf
    setproctitle('firelet')

    parser = ArgumentParser(description='Firelet daemon')
    parser.add_argument('-d', '--debug', action='store_true', help='debug mode')
    parser.add_argument('-c', '--cf',  nargs='?',
        default = 'firelet.ini', help='configuration file')
    parser.add_argument('-r', '--repodir',  nargs='?',
        help='repository directory')
    args = parser.parse_args()

    try:
        conf = ConfReader(fn=args.cf)
    except Exception, e:
        log.error("Exception %s while reading configuration file '%s'" % (e, args.cf))
        exit(1)

    if args.repodir:
        conf.data_dir = args.repodir


    # logging

    if args.debug:
#        log.basicConfig(level=log.DEBUG,
#                        format='%(asctime)s %(levelname)-8s %(message)s',
#                        datefmt='%a, %d %b %Y %H:%M:%S')
        logging.basicConfig(
            level=logging.DEBUG,
#            format='%(asctime)s [%(process)d] %(levelname)s %(name)s %(message)s',
            format='%(asctime)s [%(process)d] %(levelname)s %(name)s (%(funcName)s) %(message)s',
            datefmt = '%Y-%m-%d %H:%M:%S' # %z for timezone
        )
        log.debug("Debug mode")
        log.debug("Configuration file: '%s'" % args.cf)
        say("Firelet started in debug mode.", level="success")
        bottle_debug(True)
        reload = True
    else:
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s [%(process)d] %(levelname)s %(name)s %(message)s',
            datefmt = '%Y-%m-%d %H:%M:%S' # %z for timezone
            #TODO: add filename=conf.logfile
        )
        reload = False
        say("Firelet started.", level="success")

    globals()['users'] = Users(d=conf.data_dir)

    if conf.demo_mode == 'False':
        globals()['fs'] = GitFireSet(conf.data_dir)
        say("Configuration loaded.")
        say("%d hosts, %d rules, %d networks loaded." % (len(fs.hosts), len(fs.rules),
            len(fs.networks)))
    elif conf.demo_mode == 'True':
        globals()['fs'] = DemoGitFireSet(conf.data_dir)
        say("Demo mode.")
        say("%d hosts, %d rules, %d networks loaded." % (len(fs.hosts), len(fs.rules),
            len(fs.networks)))
#        reload = True

    session_opts = {
        'session.type': 'cookie',
        'session.validate_key': True,
    }
    app = bottle.default_app()
    app = SessionMiddleware(app, session_opts)

    run(
        app=app,
        quiet=True,
        host=conf.listen_address,
        port=conf.listen_port,
        reloader=reload
    )


if __name__ == "__main__":
    main()














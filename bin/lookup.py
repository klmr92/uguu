#!/usr/bin/python
#
# lookup.py - network shares lookup (discovery)
#
# Copyright (c) 2010, Radist <radist.nt@gmail.com>
# Read the COPYING file in the root of the source tree.
#

import psycopg2
import sys
import subprocess
import socket
import re
import collections
from subprocess import PIPE
from common import connectdb, default_ports, scanners_path, wait_until_next_lookup, wait_until_delete_share, nmap_cmd
from network import nscache, ns_domain, scan_all_hosts

class Share(object):
    def __init__(self, host, proto, port=0, scantype=None):
        self.id = None
        self.host = host
        self.proto = proto
        self.port = port
        self.scantype = scantype
    def ConnectInfo(self):
        port = self.port
        if port == 0:
            port = default_ports[self.proto]
        return (nscache(self.host), port)
    def ProtoOrPort(self):
        if self.port == 0:
            return self.proto
        else:
            return self.port
    def CheckScantype(self, scantype = None):
        if scantype is not None:
            self.scantype = scantype
        if self.scantype is None:
            for scantype in scantypes[self.proto].discovery:
                if self.CheckScantype(scantype) is not None:
                    return self.scantype
            sys.stderr.write("Cann't discover scantype for %s:%s\n" % (self.host, self.ProtoOrPort()))
        else:
            if self.port == 0:
                cmdline = "%s%s -l %s" % (scanners_path, scantypes[self.proto][self.scantype],
                                       nscache(self.host))
            else:
                cmdline = "%s%s -l -P%s %s" % (scanners_path, scantypes[self.proto][self.scantype],
                                               str(self.port), nscache(self.host))
            data = subprocess.Popen(cmdline, shell=True, stdin=PIPE, stdout=PIPE)
            data.stdin.close()
            if data.wait() == 0:
                return self.scantype
        self.scantype = None
        return None

class Lookup(object):
    """
Basic class for lookup engines.
Descedants should not overlap __init__ method and
must define __call__ method with self argument only.
"""
    def __init__(self, db, network, params, known_hosts):
        """
db is database connection
network is network name
params is lookup_data for initializing lookup engine
known_hosts is dictionary of "host" : "lookup engine name"
"""
        self.__cursor = db.cursor()
        self.__commit = lambda: db.commit()
        self.__network = network
        self.__params = params
        self.__hosts = known_hosts
        self.default = '^.*$'
        self.__include = self['Include']
        self.default = '^$'
        self.__exclude = self['Exclude']
        self.default = None
        self.__checkshares = collections.defaultdict(dict)
        self.__newshares = collections.defaultdict(dict)
    def __len__(self):
        return len(self.__params)
    def __getitem__(self, key):
        try: return self.__params[key]
        except KeyError: return self.default
    def __del__(self):
        def ListProto(_dict):
            for proto in default_ports.iterkeys():
                yield (proto, _dict[proto])
        def ListPorts(_dict):
            for port in _dict.iterkeys():
                if port not in default_ports:
                    yield (port, _dict[port])
        def RemoveOfflines(_sharedict):
            hosts = frozenset(_sharedict.keys())
            online = set()
            for item in scan_all_hosts([_sharedict[host].ConnectInfo() for host in hosts]):
                online |= nscache(None, item[0])
            for host in (hosts - online):
                del _sharedict[host]
            for host in _sharedict.keys():
                if _sharedict[host].CheckScantype() is None:
                    del _sharedict[host]
        def InsertHosts(_sharedict):
            for (host, share) in _sharedict:
                self.__cursor.execute("""
                    INSERT INTO shares (scantype_id, network, protocol,
                        hostname, port, state)
                    VALUES (%(st)s, %(net)s, %(proto)s, %(host)s, %(port)s, 'online')
                    """, {'st': share.scantype, 'net': self.__network,
                          'proto': share.proto, 'host': share.host, 'port': share.port})
        def UpdateHosts(_sharedict):
            sts = collections.defaultdict(list)
            for (host, share) in _sharedict:
                sts[share.scantype].append(share)
            for (st, shares) in sts.iteritems():
                self.__cursor.execute("""
                    UPDATE shares
                    SET scantype_id=%(st)s, last_lookup=now()
                    WHERE share_id IN %(ids)s
                    """, {'st': st, 'ids': tuple(share.id for share in shares)})
        def WalkDict(_dict, routine):
            for (proto, hosts) in ListProto(_dict):
                routine(hosts)
            for (port, hosts) in ListPorts(_dict):
                routine(hosts)
        WalkDict(self.__newshares, RemoveOfflines)
        WalkDict(self.__newshares, InsertHosts)
        self.__commit()
        WalkDict(self.__checkshares, RemoveOfflines)
        WalkDict(self.__checkshares, UpdateHosts)
        self.__commit()
    def AddShare(self, share):
        """
add share with optional scantype detection,
scantype == Ellipsis means "read it from database if possible"
"""
        self.__cursor.execute("""
            SELECT share_id, scantype_id, last_lookup + interval '%(interval)s' > now()
            FROM shares
            WHERE hostname = '%(host)s' AND
                protocol = '%(proto)s' AND port = '%(port)s'
            """, {'interval': wait_until_next_lookup, 'host': share.host,
                  'proto': share.proto, 'port': share.port})
        data = self.__cursor.fetchone()
        if data is not None:
            share.id = data[0]
            if share.scantype is Ellipsis:
                share.scantype = data[1]
            if data[2] and share.scantype == data[1]:
                return
            self.__checkshares[share.ProtoOrPort()][share.host] = share
        else:
            if share.scantype is Ellipsis:
                share.scantype = None
            self.__newshares[share.ProtoOrPort()][share.host] = share
    def AddServer(self, host, default_shares = True):
        """
add/check server to checklist, try to add default shares if default_shares,
returns permissions to add shares
"""
        if host in self.__hosts and \
           self.__hosts[host] != self.__class__.__name__:
            return False
        if self.__include.match(host) is None:
            return False
        if self.__exclude.match(host) is not None:
            return False
        self.__hosts[host] = self.__class__.__name__
        if default_shares:
            for proto in default_ports.iterkeys():
                self.AddShare(Share(host, proto))
        return True

class ParseConfig(object):
    """ networks.lookup_config parser abstraction """
    def __init__(self, netw, text):
        """ initializes callable Lookup-child generator object """
        self.__sections = []
        self.__network = netw
        errors = set()
        LN = 0
        parse = True
        section = ''
        secdata = {}
        resec = re.compile('^\[(\w+)\]$')
        repar = re.compile('^(?P<name>\w+)\s*=(?P<type>[isl])\s*(?P<q>")?(?P<value>.*)(?(q)")$')        
        for line in text.split("\n"):
            LN = LN + 1
            line = string.strip(line)
            if line == "" or line[0] in ';#':
                continue
            if not parse:
                parse = line == ".END"
                continue
            match = repar.match(line)
            if match is not None:
                if (match.group('q') is None and match.group['value'][0] == '"') or \
                   section == "" or not self.__addparam(secdata, match):
                    errors.add(LN)
                continue
            match = resec.match(line)
            if match is not None:
                if len(secdata) == 0 or section == "":
                    if len(secdata) == 0 and section == "":
                        section = match.group(1)
                    else:
                        errors.add(LN)
                else:
                    self.__sections.append((section, secdata))
                    section = match.group(1)
                    secdata = {}
                if section not in lookup_engines:
                    errors.add(LN)
                continue
            if line == ".COMMENT":
                parse = False
            else:
                errors.add(LN)
        else:
            if len(secdata) == 0 or section == "":
                errors.add(LN)
            else:
                self.__sections.append((section, secdata))
        if len(errors) > 0:
            del self.__sections
            sys.stderr.write("Errors in network %s configuration\nat lines: %s\n" %
                             (self.__network, tuple(errors)))
            raise UserWarning()
    def __addparam(self, data, match):
        name = match.group('name')
        if name in data:
            return False
        vtype = match.group('type')
        value = match.group('value')
        try:
            if vtype == 's':
                data[name] = str(value)
                return True
            elif vtype == 'i':
                data[name] = int(value)
                return True
            elif vtype == 'l':
                data[name] = tuple(s.strip() for s in value.split(','))
                return True
        except:
            pass
        return False
    def __call__(self, db, known_hosts = dict()):
        for (section, params) in self.__sections:
            yield lookup_engines[section](db, self.__network, params, known_hosts)


def get_scantypes(db):
    cursor = db.cursor()
    res = dict()
    class ScantypeDict(dict):
        def __init__(self):
            dict.__init__(self)
            self.discovery = list()
    for proto in known_protocols:
        cursor.execute("""
            SELECT scantype_id, scan_command, priority>0
            FROM scantypes
            WHERE protocol='%s'
            ORDER BY priority DESC
            """ % proto)
        res[proto] = ScantypeDict()
        for scantype in cursor.fetchall():
            res[proto][scantype[0]] = scantype[1]
            if scantype[2]:
                res[proto].discovery.append(scantype[0])
    return res

def get_networks(db):
    cursor = db.cursor()
    cursor.execute("SELECT network, lookup_config FROM networks")
    for net in cursor.fetchall():
        yield (net[0], net[1])

#####################################
### Here are comes Lookup  engines

#TODO: write Lookup engines

#####################################
        
if __name__ == "__main__":
    try:
        db = connectdb()
    except:
        print "I am unable to connect to the database, exiting."
        sys.exit()

    scantypes = get_scantypes(db)

    lookup_engines = dict([(cl.__name__, cl) for cl in Lookup.__subclasses__()])

    for (net, config) in get_networks(db):
        try:
            netconfig = ParseConfig(net, config)
            for lookuper in netconfig(db):
                engine_name = lookuper.__class__.__name__;
                try:
                    lookuper()
                    del lookuper
                except:
                    sys.stderr.write("Exception in lookup engine %s for network %s\n" % \
                                     (engine_name, net))
            del netconfig
        except:
            sys.stderr.write("Exception during lookup network %s\n" % net)

    db.cursor().execute("DELETE FROM shares WHERE last_lookup + interval %s < now()",
                        (wait_until_delete_share,))
    db.commit()

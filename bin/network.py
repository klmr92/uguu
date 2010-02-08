#
# network.py - python portable port scanner and nameserver-related routines
#
# Copyright 2010, savrus
# Copyright (c) 2010, Radist <radist.nt@gmail.com>
# Read the COPYING file in the root of the source tree.
#

import socket
import select
import subprocess
import re
import collections
import string
import errno
import sys
import os
from subprocess import PIPE

# online checking parameters
#connection timeout in seconds
scan_timeout = 5
#maximum simultanius connections
max_connections = 30

# DNS listing command and parse regexp
if os.name == 'nt':
    #for WinNT using nslookup
    nsls_cmd = "echo ls -t %(t)s %(d)s|nslookup - %(s)s"
    nsls_entry = "^\s(\S+)+\s+%s\s+(\S+)"
else:
    #for Unix using host
    nsls_cmd = "host -v -t %(t)s -l %(d)s %(s)s"
    nsls_entry = "^(\S+)\.\S+\s+\d+\s+IN\s+%s\s+(\S+)"

if os.name == 'nt': nbconnect_ok = errno.WSAEWOULDBLOCK
else:               nbconnect_ok = errno.EINPROGRESS

name2ip = dict()
ip2name = collections.defaultdict(set)

def scan_all_hosts(hosts):
    """hosts must be list of tuples (host, ip),
returns list of tuples of up hosts"""
    res = []
    while hosts:
        res.extend(scan_hosts(hosts[0:max_connections]))
        del hosts[0:max_connections]
    return res

def scan_hosts(hosts):
    socks = []
    up = []
    for h in hosts:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setblocking(0)
        try:
            err = s.connect_ex(h)
            if err == nbconnect_ok:
                socks.append(s)
        except:
            # catch some rare exceptions like "no such host"
            pass
    while socks:
        r_read, r_write, r_err = select.select([], socks, [], scan_timeout)
        if len(r_write) == 0:
            break
        for s in r_write:
            if s.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0:
                host = s.getpeername()
                up.append(host)
        socks = list(set(socks) - set(r_write))
    return up

def nscache(host, ip = None):
    """usually returns ip (and caches it),
but if host is None, returns set of hostnames"""
    if ip is None:
        if host in name2ip:
            return name2ip[host]
        ip = socket.gethostbyname(host)
    elif host is None:
        return ip2name[ip]
    name2ip[host] = ip
    ip2name[ip].add(host)
    return ip

def ns_domain(domain, rtype = "A", dns = "", cache = False):
    """list rtype NS records from domain using provided or default dns,
optionally caching records, returns dict with hostnames as keys"""
    hosts = subprocess.Popen(nsls_cmd % {'d': domain, 't': rtype, 's': dns},
                             stdout=PIPE, shell=True)
    re_host = re.compile(nsls_entry % rtype)
    res = dict()
    for nsentry in hosts.stdout:
        entry = re_host.search(nsentry)
        if entry is not None:
            res[entry.group(1)] = entry.group(2)
    if cache and rtype == "A":
        for (host, ip) in res.iteritems():
            nscache(host + '.' + domain, ip)
    return res

def ipv4_to_int(ip):
    l = map(int,string.split(ip, '.'))
    return l[3] + l[2] * 2**8 + l[1] * 2**16 + l[0] * 2**24

def int_to_ipv4(i):
    d = i & 0xff
    c = (i & 0xff00) >> 8
    b = (i & 0xff0000) >> 16
    a = (i & 0xff000000) >> 24
    return "%s.%s.%s.%s" % (a, b, c, d)


def scan_by_range(ip_range, port):
    if string.find(ip_range, '-') == -1:
        return scan_hosts([(ip_range, port)])
    ip_range = string.split(ip_range, '-')
    [low, high] = map(ipv4_to_int, ip_range)
    hosts = [(int_to_ipv4(x), port) for x in range(low, high + 1)]
    return scan_all_hosts(hosts)

def scan_by_mask(ip_range, port):
    if string.find(ip_range, '/') == -1:
        return scan_hosts([(ip_range, port)])
    ip_range = string.split(ip_range, '/')
    low = ipv4_to_int(ip_range[0])
    mask = int(ip_range[1])
    if mask > 32:
        return []
    ipmask = (0xffffffff << (32 - mask)) & 0xffffffff
    low = low & ipmask
    high = low + (1 << (32 - mask))
    hosts = [(int_to_ipv4(x), port) for x in range(low, high)]
    return scan_all_hosts(hosts)

def scan_host(ip, port):
    return scan_hosts([(ip, port)])

if __name__ == "__main__":
    if sys.argv[0] == "-h" or len(sys.argv) < 4:
        print "Usage:"
        print "\t%s scan {ip1-ip2 | ip/mask} port" % sys.argv[0]
        print "\t%s list domain type [nserver]" % sys.argv[0]
        sys.exit(2)
    if sys.argv[1] == "scan":
        [net, port] = sys.argv[2:4]
        port = int(port)
        if string.find(net, '-') != -1:
            uph = scan_by_range(net, port)
        elif string.find(net, '/') != -1:
            uph = scan_by_mask(net, port)
        else:
            uph = scan_host(net, port)
        for (host, port) in uph:
            print "Host %s:%s appers to be up" % (host, port)
    elif sys.argv[1] == "list":
        [dom, nstype] = sys.argv[2:4]
        ns = ""
        if len(sys.argv) > 4:
            ns = sys.argv[4]
        for (host, addr) in ns_domain(dom, nstype, ns).iteritems():
            print "Host %s is %s" % (host, addr)
    else:
        print "params error"
#!/usr/bin/env python
"""
OpenStack exporter for the prometheus monitoring system

Copyright (C) 2016-2019 Canonical, Ltd.
Authors:
  Jacek Nykis <jacek.nykis@canonical.com>
  Laurent Sesques <laurent.sesques@canonical.com>
  Paul Collins <paul.collins@canonical.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License version 3,
as published by the Free Software Foundation.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranties of
MERCHANTABILITY, SATISFACTORY QUALITY, or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import argparse
import yaml
import json
import ast
from os import environ as env
from os import rename, path
import traceback
import urlparse
from threading import Thread
import pickle
import requests
from time import sleep, time
from neutronclient.v2_0 import client as neutron_client
# from novaclient.v1_1 import client as nova_client
# http://docs.openstack.org/developer/python-novaclient/api.html
from cinderclient.v2 import client as cinder_client
from novaclient import client as nova_client
from BaseHTTPServer import BaseHTTPRequestHandler
from BaseHTTPServer import HTTPServer
from SocketServer import ForkingMixIn
from prometheus_client import CollectorRegistry, generate_latest, Gauge, CONTENT_TYPE_LATEST
from netaddr import IPRange

import random

import logging
import logging.handlers

config = None
log = logging.getLogger('poe-logger')


class DataGatherer(Thread):
    """Periodically retrieve data from openstack in a separate thread,
    save as pickle to cache_file
    """

    def __init__(self):
        Thread.__init__(self)
        self.daemon = True
        self.duration = 0
        self.refresh_interval = config.get('cache_refresh_interval', 900)
        self.cache_file = config['cache_file']

    def run(self):
        log.debug("Starting data gather thread")
        prodstack = {}
        while True:
            start_time = time()
            try:
                start_time = start_time
                # prodstack.update(self._get_zvm_info())
                # Ignore failures, we will try again after refresh_interval.
                # Most of them are termporary ie. connectivity problmes
                # To alert on stale cache use openstack_exporter_cache_age_seconds metric
            except Exception:
                log.critical("Error getting stats: {}".format(traceback.format_exc()))
            else:
                with open(self.cache_file + '.new', "wb+") as f:
                    pickle.dump((prodstack, ), f, pickle.HIGHEST_PROTOCOL)
                rename(self.cache_file + '.new', self.cache_file)
                log.debug("Done dumping stats to {}".format(self.cache_file))
            self.duration = time() - start_time
            sleep(self.refresh_interval)

    def get_stats(self):
        registry = CollectorRegistry()
        labels = ['cloud']
        age = Gauge('openstack_exporter_cache_age_seconds',
                    'Cache age in seconds. It can reset more frequently '
                    'than scraping interval so we use Gauge',
                    labels, registry=registry)
        label_values = ['cloud']
        age.labels(*label_values).set(time() - path.getmtime(self.cache_file))
        duration = Gauge('openstack_exporter_cache_refresh_duration_seconds',
                         'Cache refresh duration in seconds.',
                         labels, registry=registry)
        duration.labels(*label_values).set(self.duration)
        return generate_latest(registry)


class Neutron():
    def __init__(self):
        self.registry = CollectorRegistry()
        self.prodstack = {}
        with open(config['cache_file'], 'rb') as f:
            self.prodstack = pickle.load(f)[0]

    def _get_disk(self):
        import zvmutils
        c = zvmutils.ConnectorClient("http://9.152.85.153:8080")
        s = c.call("host_get_info")
   	return s 

    def get_stats(self):
        labels = ['host']
        metrics = Gauge('disk_used',
                        'disk used',
                        labels, registry=self.registry)
        s = self._get_disk()
      
        metrics.labels('host').set(s['disk_used'])

        metrics1 = Gauge('disk_total',
                        'disk total',
                        labels, registry=self.registry)

        metrics1.labels('host').set(s['disk_total'])
        return generate_latest(self.registry)


class ForkingHTTPServer(ForkingMixIn, HTTPServer):
    pass


# This could perhaps be cleverer, but surely not simpler.
COLLECTORS = {
    'neutron': Neutron,
    }

DATA_GATHERER_USERS = [
    'neutron',
    ]


def get_collectors(collectors):
    # For backwards compatibility and when enabled_collectors isn't defined,
    # specify default set of collectors before commit 662b70f and f27cda8.
    # https://github.com/CanonicalLtd/prometheus-openstack-exporter/issues/80
    if not collectors:
        return ['neutron']
    return collectors


def data_gatherer_needed(config):
    return set(get_collectors(config.get('enabled_collectors'))).intersection(DATA_GATHERER_USERS)


class OpenstackExporterHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        BaseHTTPRequestHandler.__init__(self, *args, **kwargs)

    def do_GET(self):
        url = urlparse.urlparse(self.path)
        if url.path == '/metrics':
            try:
                collectors = [COLLECTORS[collector]() for collector in get_collectors(config.get('enabled_collectors'))]
                log.debug("Collecting stats..")
                output = ''
                for collector in collectors:
                    output += collector.get_stats()
                if data_gatherer:
                    output += data_gatherer.get_stats()

                self.send_response(200)
                self.send_header('Content-Type', CONTENT_TYPE_LATEST)
                self.end_headers()
                self.wfile.write(output)
            except Exception:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(traceback.format_exc())
        elif url.path == '/':
            self.send_response(200)
            self.end_headers()
            self.wfile.write("""<html>
            <head><title>OpenStack Exporter</title></head>
            <body>
            <h1>OpenStack Exporter</h1>
            <p>Visit <code>/metrics</code> to use.</p>
            </body>
            </html>""")
        else:
            self.send_response(404)
            self.end_headers()


def handler(*args, **kwargs):
    OpenstackExporterHandler(*args, **kwargs)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(usage=__doc__,
                                     description='Prometheus OpenStack exporter',
                                     formatter_class=argparse.RawTextHelpFormatter)
    args = parser.parse_args()
    config = {}
    config['enabled_collectors'] = ['neutron']
    config['listen_port'] = 9183
    config['cache_file'] = "/var/cache/prometheus-openstack-exporter/mycloud"
    log.setLevel(logging.DEBUG)
    for logsock in ('/dev/log', '/var/run/syslog'):
        if path.exists(logsock):
            log.addHandler(logging.handlers.SysLogHandler(address=logsock))
    else:
        log.addHandler(logging.StreamHandler())
    data_gatherer = None
    if data_gatherer_needed(config):
        data_gatherer = DataGatherer()
        data_gatherer.start()
    server = ForkingHTTPServer(('', config.get('listen_port')), handler)
    server.serve_forever()

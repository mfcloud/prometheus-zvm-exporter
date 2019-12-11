
import six.moves.urllib.parse as urlparse
from zvmconnector import connector

config = None


class ConnectorClient(object):
    """Request handler to zVM cloud connector"""

    def __init__(self, zcc_url, ca_file=None):
        _url = urlparse.urlparse(zcc_url)

        _ssl_enabled = False

        if _url.scheme == 'https':
            _ssl_enabled = True
        elif ca_file:
            pass

        if _ssl_enabled and ca_file:
            self._conn = connector.ZVMConnector(_url.hostname, _url.port,
                                                ssl_enabled=_ssl_enabled,
                                                verify=ca_file, token_path="/etc/zvmsdk/token.dat")
        else:
            self._conn = connector.ZVMConnector(_url.hostname, _url.port,
                                                ssl_enabled=_ssl_enabled,
                                                verify=False, token_path="/etc/zvmsdk/token.dat")

    def call(self, func_name, *args, **kwargs):

        results = self._conn.send_request(func_name, *args, **kwargs)
        if results['overallRC'] != 0:
            pass
            #log.error("zVM Cloud Connector request %(api)s failed with "
            #   "parameters: %(args)s %(kwargs)s .  Results: %(results)s",
            #   {'api': func_name, 'args': six.text_type(args),
            #    'kwargs': six.text_type(kwargs),
            #    'results': six.text_type(results)})

        return results['output']

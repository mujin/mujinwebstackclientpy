# -*- coding: utf-8 -*-
# Copyright (C) MUJIN Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import functools
import socket

from requests.adapters import HTTPAdapter
from urllib3 import HTTPConnectionPool
from urllib3.connection import HTTPConnection


class UnixSocketHTTPConnection(HTTPConnection):

    _unixEndpoint = None # unix socket endpoint

    def __init__(self, unixEndpoint, **kwargs):
        super(UnixSocketHTTPConnection, self).__init__(**kwargs)
        self._unixEndpoint = unixEndpoint

    def _new_conn(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if self.timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
            sock.settimeout(self.timeout)
        sock.connect(self._unixEndpoint)
        return sock


class UnixSocketConnectionPool(HTTPConnectionPool):

    _unixEndpoint = None # unix socket endpoint

    def __init__(self, unixEndpoint, maxSize=10):
        super(UnixSocketConnectionPool, self).__init__('127.0.0.1', maxsize=maxSize)
        UnixSocketConnectionPool.ConnectionCls = functools.partial(UnixSocketHTTPConnection, unixEndpoint=unixEndpoint)
        self._unixEndpoint = unixEndpoint

    def __str__(self):
        return '%s(unixEndpoint=%s)' % (type(self).__name__, self._unixEndpoint)


class UnixSocketAdapter(HTTPAdapter):

    _connectionPool = None # an instance of UnixSocketConnectionPool

    def __init__(self, unixEndpoint, **kwargs):
        super(UnixSocketAdapter, self).__init__(**kwargs)
        self._connectionPool = UnixSocketConnectionPool(unixEndpoint)

    def close(self):
        self._connectionPool.close()
        super(UnixSocketAdapter, self).close()

    def get_connection(self, url, proxies=None):
        assert not proxies, 'proxies not supported for unix socket'
        return self._connectionPool

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        '''
        To support requests>=2.32.2 (Note that 2.32.0 and 2.32.1 are not supported)

        https://github.com/psf/requests/pull/6710
        '''
        return self.get_connection(request.url, proxies=proxies)
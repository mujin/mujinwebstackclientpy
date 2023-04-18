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
    def __init__(self, socketPath, *args, **kwargs):
        super(UnixSocketHTTPConnection, self).__init__(*args, **kwargs)
        self._socketPath = socketPath

    def _new_conn(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if self.timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
            sock.settimeout(self.timeout)
        sock.connect(self._socketPath)
        return sock


class UnixSocketConnectionPool(HTTPConnectionPool):
    def __init__(self, socketPath):
        super(UnixSocketConnectionPool, self).__init__('127.0.0.1')
        UnixSocketConnectionPool.ConnectionCls = functools.partial(UnixSocketHTTPConnection, socketPath)
        self._socketPath = socketPath

    def __str__(self):
        return '%s(path=%s)' % (type(self).__name__, self._socketPath)


class UnixSocketAdapter(HTTPAdapter):
    def __init__(self, socketPath, *args, **kwargs):
        super(UnixSocketAdapter, self).__init__(*args, **kwargs)
        self._pool = UnixSocketConnectionPool(socketPath)

    def close(self):
        self._pool.close()
        super(UnixSocketAdapter, self).close()

    def get_connection(self, url, proxies=None):
        assert not proxies, 'proxies not supported for socket'
        return self._pool

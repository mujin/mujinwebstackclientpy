# -*- coding: utf-8 -*-
# Copyright (C) 2013-2015 MUJIN Inc.
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

import asyncio
import base64
import msgspec
import os
import ssl
import requests
import threading
import traceback
import ujson
import uuid
import copy
import websockets
from requests import auth as requests_auth
from requests import adapters as requests_adapters
from typing import Optional, Callable, Dict, Any, Union, List, Tuple
from urllib.parse import urlparse
from urllib3.fields import RequestField
from urllib3.filepost import choose_boundary

import websockets.asyncio
import websockets.asyncio.client
import websockets.protocol

# numpy is not a dependency of this client, but callers routinely pass numpy values in request bodies
try:
    import numpy
except ImportError:
    numpy = None

from . import _
from . import APIServerError, WebstackClientError, ControllerGraphClientException
from .unixsocketadapter import UnixSocketAdapter

import logging

logging.getLogger('websockets').setLevel(logging.WARNING)
log = logging.getLogger(__name__)

# Field data types that the requests library treats as already being in-memory.
# Anything else needs to fall back to the slow path
_IN_MEMORY_FIELD_DATA_TYPES = (bytes, bytearray, str)


class JSONWebTokenAuth(requests_auth.AuthBase):
    """Attaches JWT Bearer Authentication to a given Request object. Use basic authentication if token is not available."""

    _username = None  # controller username
    _password = None  # controller password
    _jsonWebToken = None  # json web token
    _encodedUsernamePassword: str  # Encoded Mujin controller's username and password

    def __init__(self, username, password):
        self._username = username
        self._password = password
        usernamePassword = '%s:%s' % (username, password)
        self._encodedUsernamePassword = base64.b64encode(usernamePassword.encode('utf-8')).decode('ascii')

    def __eq__(self, other):
        return all(
            [
                self._username == getattr(other, '_username', None),
                self._password == getattr(other, '_password', None),
                self._jsonWebToken == getattr(other, '_jsonWebToken', None),
            ],
        )

    def __ne__(self, other):
        return not self == other

    def _SetJSONWebToken(self, response, *args, **kwargs):
        # switch to JWT authentication
        self._jsonWebToken = response.cookies.get('jwttoken')

    def GetAuthorizationHeader(self) -> str:
        if self._jsonWebToken is None:
            return 'Basic %s' % self._encodedUsernamePassword
        else:
            return 'Bearer %s' % self._jsonWebToken

    def __call__(self, request):
        if self._jsonWebToken is not None:
            request.headers['Authorization'] = 'Bearer %s' % self._jsonWebToken
        else:
            requests_auth.HTTPBasicAuth(self._username, self._password)(request)
            request.register_hook('response', self._SetJSONWebToken)
        return request


class Subscription(object):
    """Subscription that contains the unique subscription id for every subscription."""

    _subscriptionId: str  # subscription id
    _subscriptionCallbackFunction: Callable[[Optional[ControllerGraphClientException], Optional[dict]], None]  # subscription callback function
    _webSocket: Optional[websockets.asyncio.client.ClientConnection] = None  # connection this subscription was started on, the only one that may fail it

    def __init__(self, subscriptionId: str, callbackFunction: Callable[[Optional[ControllerGraphClientException], Optional[dict]], None]):
        self._subscriptionId = subscriptionId
        self._subscriptionCallbackFunction = callbackFunction

    def GetSubscriptionID(self) -> str:
        return self._subscriptionId

    def GetWebSocket(self) -> Optional[websockets.asyncio.client.ClientConnection]:
        return self._webSocket

    def SetWebSocket(self, webSocket: Optional[websockets.asyncio.client.ClientConnection]):
        self._webSocket = webSocket

    def GetSubscriptionCallbackFunction(self) -> Callable[[Optional[ControllerGraphClientException], Optional[dict]], None]:
        return self._subscriptionCallbackFunction

    def __repr__(self):
        return '<Subscription(%r, %r)>' % (self._subscriptionId, self._subscriptionCallbackFunction)


class BackgroundThread(object):
    _thread: threading.Thread  # A thread to run the event loop
    _eventLoop: asyncio.AbstractEventLoop  # Event loop that is running so that client can add coroutine
    _eventLoopReadyEvent: threading.Event  # An event that signals the event loop is ready

    def __init__(self):
        self._eventLoopReadyEvent = threading.Event()
        # Run the event loop as a daemon thread so it can't block interpreter shutdown
        self._thread = threading.Thread(target=self._RunEventLoop, daemon=True)
        self._thread.start()
        # block and wait for the signal to make sure the event loop is created and set in the _thread
        self._eventLoopReadyEvent.wait()

    def _RunEventLoop(self):
        # create a new event loop in a background thread
        self._eventLoop = asyncio.new_event_loop()
        # set the created loop as the current event loop for this thread
        asyncio.set_event_loop(self._eventLoop)
        # signals that the event loop is now ready
        self._eventLoopReadyEvent.set()
        self._eventLoop.run_forever()

    def RunCoroutine(self, coroutine: Callable):
        """Schedule a coroutine to run on the event loop from another thread"""
        return asyncio.run_coroutine_threadsafe(coroutine, self._eventLoop)

    def IsCurrentThread(self) -> bool:
        """Whether the calling thread is the event loop thread"""
        return threading.current_thread() is self._thread

    def __del__(self):
        self.Destroy()

    def Destroy(self):
        if self._eventLoop.is_closed():
            return
        # cancel all tasks in the event loop
        for task in asyncio.all_tasks(loop=self._eventLoop):
            task.cancel()
        # run the loop briefly to let cancellations propagate
        self._eventLoop.call_soon_threadsafe(self._eventLoop.stop)
        self._thread.join()
        self._eventLoop.close()


class WebSocketHandoff(object):
    """
    Settles which side owns a WebSocket, the thread that asked for the connect or the event loop that ran it.
    The requester waits with a timeout while the connect runs on the event loop, so both can finish at the same moment.
    Exactly one of them takes ownership, and is then responsible for closing it.
    """

    # Guards the fields below, only ever held across non-blocking assignments
    _lock: threading.Lock

    # Socket that the connect produced, if it got that far
    _webSocket: Optional[websockets.asyncio.client.ClientConnection] = None

    # Whether the requester stopped waiting for the connect
    _isAbandoned: bool = False

    def __init__(self):
        self._lock = threading.Lock()

    def Publish(self, webSocket: websockets.asyncio.client.ClientConnection) -> bool:
        """
        Offers a newly connected socket to the requester, returning whether it took it.
        A false return means the requester already gave up, leaving the connect to close the socket.
        """
        with self._lock:
            if self._isAbandoned:
                return False
            self._webSocket = webSocket
            return True

    def Abandon(self) -> Optional[websockets.asyncio.client.ClientConnection]:
        """
        Stops waiting for the connect, returning a socket that arrived too late to be used, if any.
        Any returned socket is now the caller's to close.
        """
        with self._lock:
            self._isAbandoned = True
            return self._webSocket


class ControllerWebClientRaw(object):
    _baseurl = None  # Base URL of the controller
    _username = None  # Username to login with
    _password = None  # Password to login with
    _headers = None  # Prepared headers for all requests
    _isok = False  # Flag to stop
    _session = None  # Requests session object
    _webSocket: websockets.asyncio.client.ClientConnection = None  # WebSocket used to connect to WebStack for subscriptions
    _subscriptions: dict[str, Subscription]  # Dictionary that stores the subscriptionId(key) and the corresponding subscription(value)
    _subscriptionLock: threading.Lock  # Lock protecting _subscriptions and the _webSocket pointer, only ever held across non-blocking operations
    _connectionLock: threading.Lock  # Lock serializing websocket connection setup and publication of _webSocket, only acquired off the event loop
    _backgroundThread: BackgroundThread = None  # The background thread to handle async operations

    _threadName: Optional[str] = None  # The last thread this client was used in if we're warning on calls from different threads.

    # Cached JSON decode/encode contexts
    _jsonEncoder: msgspec.json.Encoder
    _jsonDecoder: msgspec.json.Decoder

    def __init__(
        self,
        baseurl: str,
        username: str,
        password: str,
        locale: Optional[str] = None,
        author: Optional[str] = None,
        userAgent: Optional[str] = None,
        additionalHeaders: Optional[Dict[str, str]] = None,
        unixEndpoint: Optional[str] = None,
        tlsSkipVerify: bool = False,
        warnOnUseFromDifferentThreads: bool = False,
    ) -> None:
        self._baseurl = baseurl
        self._username = username
        self._password = password
        self._headers = {}
        self._isok = True

        self._subscriptions = {}
        self._subscriptionLock = threading.Lock()
        self._connectionLock = threading.Lock()

        self._jsonEncoder = msgspec.json.Encoder(enc_hook=self._JSONEncodeHook)
        self._jsonDecoder = msgspec.json.Decoder()

        # Create session
        self._session = requests.Session()
        self._session.verify = not tlsSkipVerify

        # Use basic auth by default, use JWT if available
        self._session.auth = JSONWebTokenAuth(self._username, self._password)

        # Add additional headers
        self._headers.update(additionalHeaders or {})

        # Set referer
        self._headers['Referer'] = baseurl

        # Set csrftoken
        # Any string can be the csrftoken
        self._headers['X-CSRFToken'] = 'csrftoken'
        self._session.cookies.set('csrftoken', self._headers['X-CSRFToken'], path='/')

        if unixEndpoint is None:
            # Add retry to deal with closed keep alive connections
            self._session.mount('https://', requests_adapters.HTTPAdapter(max_retries=3))
            self._session.mount('http://', requests_adapters.HTTPAdapter(max_retries=3))
        else:
            self._session.adapters.pop('https://', None)  # we don't use https with unix sockets
            self._session.mount('http://', UnixSocketAdapter(unixEndpoint, max_retries=3))

        # Set locale headers
        self.SetLocale(locale)

        # Set author header
        self.SetAuthor(author)

        # Set user agent header
        self.SetUserAgent(userAgent)

        if warnOnUseFromDifferentThreads:
            self._threadName = threading.current_thread().name
            log.info('initialized client with warning on calls from different threads enabled and this may degrade performance')
            log.info('set "warnOnUseFromDifferentThreads" to "False" to disable this if performance is poor')

    def __del__(self):
        self.Destroy()

    def Destroy(self):
        self.SetDestroy()
        if self._backgroundThread is not None:
            # make sure to stop subscriptions and close the websocket first, without holding _subscriptionLock.
            # _StopAllSubscriptions takes this lock itself on the event loop.
            future = self._backgroundThread.RunCoroutine(self._StopAllSubscriptions(ControllerGraphClientException(_('Shutting down'))))
            try:
                # Bounded so that a wedged event loop can't hold up shutdown.
                # The tasks are cancelled when the thread is destroyed below.
                future.result(timeout=5.0)
            except Exception as error:
                log.warning('failed to stop all subscriptions cleanly while shutting down: %s', error)
            # next destroy the thread
            self._backgroundThread.Destroy()
            self._backgroundThread = None

    def SetDestroy(self):
        self._isok = False

    @staticmethod
    def _EncodeMultipartFormData(files: Any) -> Optional[Tuple[bytes, str]]:
        """Encodes in-memory multipart/form-data fields into a request body in a single allocation.

        The requests library hands multipart fields to urllib3, which appends each part to a BytesIO.
        This reallocates and copies on each resize, and the final getvalue() copies again.
        Joining a list of binary parts instead computes the final size up front, and copies only once.

        This optimization only works for fields that are actually in-memory types.
        Anything with more custom handling inside of requests (file descriptors, etc) needs to fall back.

        :param files: multipart fields as a sequence of (fieldName, (filename, data[, contentType[, headers]])) pairs
        :return: the (body, contentType) pair, or None if the fields are not all in-memory.
        """
        if not files or not isinstance(files, (list, tuple)):
            return None

        fields: List[RequestField] = []
        for entry in files:
            # Only the (fieldName, valueTuple) form is handled.
            # requests applies extra filename guessing to the bare-value form, which would change the body.
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                return None
            fieldName, value = entry
            if not isinstance(value, (list, tuple)) or not 2 <= len(value) <= 4:
                return None
            data = value[1]
            if not isinstance(data, _IN_MEMORY_FIELD_DATA_TYPES):
                return None
            field = RequestField(
                name=fieldName,
                data=data,
                filename=value[0],
                headers=value[3] if len(value) == 4 else None,
            )

            # A two-element value carries no content type, and requests leaves it unset rather than guessing.
            # Replicate this behaviour for consistency.
            field.make_multipart(content_type=value[2] if len(value) >= 3 else None)
            fields.append(field)

        # Accumulate our list of encoded fields
        boundary = choose_boundary()
        parts: List[bytes] = []
        for field in fields:
            parts.append(('--%s\r\n' % boundary).encode('latin-1'))
            parts.append(field.render_headers().encode('utf-8'))
            parts.append(field.data.encode('utf-8') if isinstance(field.data, str) else field.data)
            parts.append(b'\r\n')
        parts.append(('--%s--\r\n' % boundary).encode('latin-1'))

        # A binary join performs a single allocation + copy of all the input data
        return b''.join(parts), 'multipart/form-data; boundary=%s' % boundary

    @staticmethod
    def _JSONEncodeHook(obj: Any) -> Any:
        # Convert numpy values to the native python objects that msgspec then re-encodes directly.
        # ujson only handles the numpy types that subclass a python builtin (float64, str_), and raises
        # OverflowError on the integer, boolean and narrow float types, so they cannot reach the fallback below.
        if numpy is not None:
            if isinstance(obj, numpy.ndarray):
                return obj.tolist()
            if isinstance(obj, numpy.generic):
                return obj.item()

        # For other types, fall back to the ujson behaviour (inferring serialization based on members).
        # Splice the encoded output via msgspec.Raw to avoid reprocessing the serialized result.
        return msgspec.Raw(ujson.dumps(obj).encode('utf-8'))

    def EncodeJSON(self, obj: Any) -> bytes:
        """Encodes an object into a JSON request body, tolerating types msgspec cannot serialize natively."""
        return self._jsonEncoder.encode(obj)

    def DecodeJSON(self, data: Union[str, bytes]) -> Any:
        """Decodes a JSON response body, raising APIServerError rather than leaking msgspec.DecodeError."""
        try:
            return self._jsonDecoder.decode(data)
        except msgspec.DecodeError as error:
            raw = data.decode('utf-8', 'replace') if isinstance(data, bytes) else data
            log.exception('caught exception parsing json response: %s: %s', error, raw)
            raise APIServerError(_('Unable to parse server response: %s') % raw[:1000]) from error

    def SetLocale(self, locale=None):
        locale = locale or os.environ.get('LANG', None)

        # Convert locale to language code for http requests
        # en_US.UTF-8 => en-us
        # en_US => en-us
        # en => en
        language = 'en'  # default to en
        if locale is not None and len(locale) > 0:
            language = locale.split('.', 1)[0].replace('_', '-').lower()
        self._headers['Accept-Language'] = language

    def SetAuthor(self, author=None):
        if author is not None and len(author) > 0:
            self._headers['X-Author'] = author
        else:
            self._headers.pop('X-Author', None)

    def SetUserAgent(self, userAgent=None):
        if userAgent is not None and len(userAgent) > 0:
            self._headers['User-Agent'] = userAgent
        else:
            self._headers.pop('User-Agent', None)

    def Request(
        self,
        method: str,
        path: str,
        timeout: float = 5,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> requests.Response:
        if timeout < 1e-6:
            raise WebstackClientError(_('Timeout value (%s sec) is too small') % timeout)

        url = self._baseurl + path

        # Set all the headers prepared for this client
        headers = dict(headers or {})
        headers.update(self._headers)

        if 'allow_redirects' not in kwargs:
            # by default, disallow redirect since DELETE with redirection is too dangerous
            kwargs['allow_redirects'] = method in ('HEAD', 'GET', 'POST')

        if self._threadName is not None:
            currentName = threading.current_thread().name
            if currentName != self._threadName:
                log.warning('client has been called across multiple threads, was "%s", now "%s"', self._threadName, currentName)
                self._threadName = currentName

        response = self._session.request(method=method, url=url, timeout=timeout, headers=headers, **kwargs)

        # if the response is 401 and JSON web token was used, it is possible that the token has expired
        if response.status_code == 401 and isinstance(self._session.auth, JSONWebTokenAuth):
            if self._session.auth._jsonWebToken is not None:
                log.debug('request %s %s received unauthorized error, clearing cached json web token and retrying', method, url)
                # clear the token and retry the request to fetch a new token via basic auth
                self._session.auth._jsonWebToken = None
                response = self._session.request(method=method, url=url, timeout=timeout, headers=headers, **kwargs)

        # in verbose logging, log the caller
        if log.isEnabledFor(5):  # logging.VERBOSE might not be available in the system
            log.verbose('request %s %s response %s took %.03f seconds:\n%s', method, url, response.status_code, response.elapsed.total_seconds(), '\n'.join([line.strip() for line in traceback.format_stack()[:-1]]))
        return response

    # Python port of the javascript API Call function
    def APICall(
        self,
        method: str,
        path: str = '',
        params: Optional[Dict[str, Any]] = None,
        fields: Optional[Union[List[str], Dict[str, Any]]] = None,
        data: Optional[Union[str, Dict[str, Any]]] = None,
        headers: Optional[Dict[str, str]] = None,
        expectedStatusCode: Optional[int] = None,
        files: Optional[Dict[str, Any]] = None,
        timeout: float = 5,
        apiVersion: str = 'v1',
    ) -> Any:
        path = '/api/%s/%s' % (apiVersion, path.lstrip('/'))
        if apiVersion == 'v1' and not path.endswith('/'):
            path += '/'
        elif apiVersion == 'v2' and path.endswith('/'):
            path = path[:-1]

        if params is None:
            params = {}

        params['format'] = 'json'

        if fields is not None:
            params['fields'] = fields

        # TODO(ziyan): implicit order by pk, is this necessary?
        # if 'order_by' not in params:
        #     params['order_by'] = 'pk'

        method = method.upper()

        if headers is None:
            headers = {}

        # Sanitize header keys as lower case so that further presence checks can use hash lookups
        headers = {key.lower(): value for key, value in headers.items()}

        # If the files consist of only in-memory data, encode the body ourselves.
        # Requests uses BytesIO, which performs unnecessary copies/doubling operations that we can avoid.
        if files is not None and data is None and 'content-type' not in headers:
            encodedMultipart = self._EncodeMultipartFormData(files)
            if encodedMultipart is not None:
                data, headers['content-type'] = encodedMultipart
                files = None

        # GET/HEAD must not carry a request body
        # Some forwarding proxies (e.g. privoxy) hang when a GET arrives with a body,
        # since python sends the body in a separate TCP segment that the proxy does not expect on GET
        if data is None and files is None and method not in ('GET', 'HEAD'):
            data = {}

        # Default to json content type if not using multipart/form-data
        if 'content-type' not in headers and files is None and data is not None:
            headers['content-type'] = 'application/json'
            data = self.EncodeJSON(data)

        if 'accept' not in headers:
            headers['accept'] = 'application/json'

        response = self.Request(method, path, params=params, data=data, files=files, headers=headers, timeout=timeout)

        # Try to parse response
        raw = response.content.decode('utf-8', 'replace').strip()
        content: Optional[Dict[str, Any]] = None
        if len(raw) > 0:
            content = self.DecodeJSON(raw)

        # First check error
        if content is not None and 'error_message' in content:
            raise APIServerError(content['error_message'], errorcode=content.get('error_code', None), inputcommand=path, detailInfoType=content.get('detailInfoType', None), detailInfo=content.get('detailInfo', None))

        if content is not None and 'error' in content:
            raise APIServerError(content['error'].get('message', raw), inputcommand=path)

        if response.status_code >= 400:
            raise APIServerError(_('Unexpected server response %d: %s') % (response.status_code, raw))

        # TODO(ziyan): Figure out the expected status code from method
        #              Some APIs were miss-implemented to not return standard status code.
        if not expectedStatusCode:
            expectedStatusCode = {
                'GET': 200,
                'POST': 201,
                'DELETE': 204,
                'PUT': 202,
                'PATCH': 201,
            }.get(method, 200)

        # Check expected status code
        if response.status_code != expectedStatusCode:
            log.error('response status code is %d, expecting %d for %s %s: %s', response.status_code, expectedStatusCode, method, path, raw)
            raise APIServerError(_('Unexpected server response %d: %s') % (response.status_code, raw))

        return content

    def CallGraphAPI(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 5.0,
    ) -> Dict[str, Any]:
        # prepare the headers
        if headers is None:
            headers = {}
        headers['Content-Type'] = 'application/json'
        headers['Accept'] = 'application/json'

        # make the request
        response = self.Request(
            'POST',
            '/api/v2/graphql',
            headers=headers,
            data=self.EncodeJSON(
                {
                    'query': query,
                    'variables': variables or {},
                },
            ),
            timeout=timeout,
        )

        # try to parse response
        raw = response.content.decode('utf-8', 'replace').strip()

        # response must be 200 OK
        statusCode = response.status_code
        if statusCode != 200:
            raise ControllerGraphClientException(_('Unexpected server response %d: %s') % (statusCode, raw), statusCode=statusCode, response=response)

        # decode the response content
        content: Optional[Dict[str, Any]] = None
        if len(raw) > 0:
            try:
                content = self.DecodeJSON(raw)
            except APIServerError:
                # DecodeJSON already logged the failure, leave content as None so that the checks
                # below report it as ControllerGraphClientException carrying the status code and response
                pass

        # raise any error returned
        if content is not None and 'errors' in content and len(content['errors']) > 0:
            message: str = content['errors'][0].get('message', raw)
            errorCode: Optional[str] = None
            if 'extensions' in content['errors'][0]:
                errorCode = content['errors'][0]['extensions'].get('errorCode', None)
            raise ControllerGraphClientException(message, statusCode=statusCode, content=content, response=response, errorCode=errorCode)

        if content is None or 'data' not in content:
            raise ControllerGraphClientException(_('Unexpected server response %d: %s') % (statusCode, raw), statusCode=statusCode, response=response)

        return content['data']

    def _EnsureWebSocketConnection(self, timeout: float = 5.0):
        """
        Opens the WebSocket connection if it is not up yet.

        Must not be called while holding _subscriptionLock.
        Opening runs on the background event loop, which also takes _subscriptionLock if a subscription drops.
        Waiting for the open under the lock deadlocks the two threads against each other.
        """
        with self._connectionLock:
            if self._backgroundThread is None:
                # Create the background thread for async operations
                self._backgroundThread = BackgroundThread()
            if not self._IsWebSocketConnectionOpen():
                # Resolve the endpoint here instead of on the event loop, since it issues a blocking HTTP request.
                # If run on the loop, it would stall for the entire call duration, interfering with the connect's timeout.
                parsedUrl = self._ResolveGraphQLEndpointURL()

                # Wrap the socket handoff so that we can know for sure who owns it
                handoff = WebSocketHandoff()
                openWebSocketFuture = self._backgroundThread.RunCoroutine(self._OpenWebSocketConnection(parsedUrl, handoff))
                try:
                    # Wait for connect with a timeout so that if something gets stuck we throw instead of hang
                    webSocket = openWebSocketFuture.result(timeout=timeout)
                except BaseException:
                    # Cancel so that a slow connect can't finish later and hand back a socket nobody owns
                    openWebSocketFuture.cancel()

                    # The connect can still complete in the window between the timeout firing and the cancel landing.
                    # If this happens, the socket it produced is ours to close.
                    abandonedWebSocket = handoff.Abandon()
                    if abandonedWebSocket is not None:
                        try:
                            self._backgroundThread.RunCoroutine(abandonedWebSocket.close())
                        except Exception as error:
                            # Never mask the failure that is already on its way to the caller
                            log.warning('failed to close the WebSocket left by a timed out connect: %s', error)
                    raise

                # Need to take both _connectionLock _and_ _subscriptionLock here.
                # We don't want to publish a socket if the caller has given up on the connect and won't listen on it,
                # or for a connection that is shutting down to see inconsistent state.
                with self._subscriptionLock:
                    self._webSocket = webSocket

                # Start listening without blocking
                self._backgroundThread.RunCoroutine(self._ListenToWebSocket(webSocket))

    def _IsWebSocketConnectionOpen(self):
        # Sockets stay referenced until teardown, so check if it's actually still open.
        webSocket = self._webSocket
        return webSocket is not None and webSocket.state is websockets.protocol.State.OPEN

    async def _CloseIdleWebSocket(self, webSocket: websockets.asyncio.client.ClientConnection):
        """
        Closes a connection that was left without subscribers.

        The subscriber set is checked again here because the close is scheduled without waiting for it.
        A subscribe may have attached to the connection in the meantime, in which  case it is still in use.
        Deciding and retracting the connection under a single lock hold is what makes that safe,
        since a subscribe either registers first and keeps the connection, or finds it already retracted and fails.
        """
        with self._subscriptionLock:
            if self._webSocket is not webSocket or len(self._subscriptions) > 0:
                return
            self._webSocket = None
        await webSocket.close()

    def _ResolveGraphQLEndpointURL(self):
        """
        Resolves the GraphQL endpoint URL, following an http to https upgrade if there is one.
        Issues a blocking HTTP request, so it must run on the calling thread rather than on the event loop.
        """
        # URL to http GraphQL endpoint on Mujin controller
        path = '/api/v2/graphql'
        try:
            # make a test call to check for http to https upgrades, if there is any
            response = self.Request('HEAD', path)
            return urlparse(response.url)
        except Exception as e:
            log.exception('failed to query graphql endpoint: %s', e)
            # fall back to original URL
            return urlparse(self._baseurl + path)

    async def _OpenWebSocketConnection(self, parsedUrl, handoff: WebSocketHandoff) -> websockets.asyncio.client.ClientConnection:
        """
        Connects a WebSocket and initializes the graphql-ws session on it.
        Offers the socket through the handoff object rather than publishing it directly.
        This way, a connect the requester has already timed out on can clean up after itself properly.
        """
        authorization = self._session.auth.GetAuthorizationHeader()

        # handle different scheme
        sslContext = None
        webSocketScheme = ''
        if parsedUrl.scheme == 'https':
            webSocketScheme = 'wss'
            # re-use the current requests session settings for validating TLS certificates
            if self._session.verify:
                sslContext = ssl.create_default_context()
            else:
                sslContext = ssl._create_unverified_context()
        elif parsedUrl.scheme == 'http':
            webSocketScheme = 'ws'
        uri = '%s://%s%s' % (webSocketScheme, parsedUrl.netloc, parsedUrl.path)

        # prepare the headers
        headers = copy.deepcopy(self._headers)
        headers['Content-Type'] = 'application/json'
        headers['Accept'] = 'application/json'
        subprotocols = ['graphql-ws']

        # decide on using unix socket or not
        adapter = self._session.adapters.get('http://')
        if isinstance(adapter, UnixSocketAdapter):
            webSocket = await websockets.unix_connect(
                path=adapter.get_unix_endpoint(),
                uri=uri,
                subprotocols=subprotocols,
                additional_headers=headers,
                ssl=sslContext,
                # accept all frames sent by the controller
                max_size=None,
            )
        else:
            webSocket = await websockets.connect(
                uri=uri,
                subprotocols=subprotocols,
                additional_headers=headers,
                ssl=sslContext,
                # accept all frames sent by the controller
                max_size=None,
            )

        try:
            # text=True keeps this a text frame, as required by the graphql-ws subprotocol,
            # since websockets would otherwise send the encoded bytes as a binary frame
            await webSocket.send(
                self.EncodeJSON(
                    {
                        'type': 'connection_init',
                        'payload': {
                            'Authorization': authorization,
                        },
                    },
                ),
                text=True,
            )
        except BaseException:
            # Includes cancellation from a caller that timed out waiting on this coroutine
            await webSocket.close()
            raise

        # Only hand off the socket once the connection is actually initialized.
        # Half-initialized sockets should never be visible to other callers.
        if not handoff.Publish(webSocket):
            # The requester timed out while we were connecting, so this socket is ours to clean up
            await webSocket.close()
            raise asyncio.CancelledError()

        return webSocket

    async def _ListenToWebSocket(self, webSocket: websockets.asyncio.client.ClientConnection):
        error = None
        try:
            async for response in webSocket:
                # stop if stop is requested
                if not self._isok:
                    break

                # parse the result
                content = None
                if len(response) > 0:
                    try:
                        content = self.DecodeJSON(response)
                    except APIServerError:
                        # DecodeJSON already logged the failure, leave content as None so that the sanity
                        # check below raises and the outer handler stops all subscriptions with the error
                        pass

                # sanity checks
                if content is None or 'type' not in content:
                    # raise an error, this should never happen
                    raise ControllerGraphClientException(_('Unexpected server response: %s') % (response))

                # handle control messages
                contentType = content['type']
                if contentType == 'connection_ack':
                    log.debug('received connection_ack')
                    continue
                if contentType == 'ka':
                    # received keep-alive "ka" message
                    continue

                # sanity checks
                if 'id' not in content:
                    # raise an error, this should never happen
                    raise ControllerGraphClientException(_('Unexpected server response, missing id: %s') % (response))

                # reply back to subscribers
                subscriptionId = content['id']
                with self._subscriptionLock:
                    # select the right subscription
                    subscription = self._subscriptions.get(subscriptionId)
                if subscription is None:
                    # subscriber is gone
                    continue

                # Dispatch without the lock held, so that callbacks that re-enter the client can't deadlock
                callbackFunction = subscription.GetSubscriptionCallbackFunction()

                # Return if there is an error
                if 'payload' in content and 'errors' in content['payload'] and len(content['payload']['errors']) > 0:
                    message = content['payload']['errors'][0].get('message', response)
                    errorCode = None
                    if 'extensions' in content['payload']['errors'][0]:
                        errorCode = content['payload']['errors'][0]['extensions'].get('errorCode', None)
                    callbackFunction(error=ControllerGraphClientException(message, content=content, errorCode=errorCode), response=None)
                    continue

                # Return the payload
                callbackFunction(error=None, response=content.get('payload') or {})

        except Exception as e:
            log.exception('caught WebSocket exception: %s', e)
            error = ControllerGraphClientException(_('Failed to listen to WebSocket: %s') % (e))
        finally:
            if error is None:
                # Iteration ended by itself, so the server closed the connection or we are shutting down
                error = ControllerGraphClientException(_('WebSocket connection closed'))

            # Naming the socket keeps this to our own subscribers, so a newer connection that has
            # already taken over keeps its own. The socket is closed on the way out either way.
            await self._StopAllSubscriptions(error, webSocket=webSocket)

    async def _StopAllSubscriptions(self, error: Optional[ControllerGraphClientException], webSocket: Optional[websockets.asyncio.client.ClientConnection] = None):
        """
        Fails subscriptions with the given error, drops them, and closes the connection they ran on.

        A caller that passes webSocket speaks only for that connection, so only the subscriptions that were started on it are failed.
        Ownership is tracked per subscription rather than by comparing against the currently established connection.
        Connections on their way out must still fail their own subscribers even once the client has moved on to a newer connection,
        or those subscribers would be left waiting on a connection that is gone and never hear that it went away.

        Passing no webSocket speaks for the whole client and takes down whatever is currently established.
        """
        # Decide and take everything in one step.
        # A subscribe racing this either registers before the decision and is honoured, or fails against a retracted connection.
        with self._subscriptionLock:
            if webSocket is None:
                webSocketToClose, self._webSocket = self._webSocket, None
                subscriptions = list(self._subscriptions.values())
                self._subscriptions.clear()
            else:
                subscriptions = [subscription for subscription in self._subscriptions.values() if subscription.GetWebSocket() is webSocket]
                for subscription in subscriptions:
                    del self._subscriptions[subscription.GetSubscriptionID()]
                # This connection is going away either way, but retract the pointer only while it still names this connection
                webSocketToClose = webSocket
                if self._webSocket is webSocket:
                    self._webSocket = None

        # Close and notify outside the lock, since both block and a callback may re-enter the client
        if webSocketToClose is not None:
            await webSocketToClose.close()

        # Send a message back to the callers using the callback function
        for subscription in subscriptions:
            subscription.GetSubscriptionCallbackFunction()(error=error, response=None)

    def _RejectCallFromEventLoop(self, operationName: str):
        """
        Rejects a blocking client call that is being made from the event loop thread.
        Subscription callbacks run on the event loop, and these calls wait on work scheduled onto that same loop,
        so calling them from a callback would block the loop against itself.
        """
        if self._backgroundThread is not None and self._backgroundThread.IsCurrentThread():
            raise ControllerGraphClientException(_('%s cannot be called from a subscription callback') % (operationName,))

    def SubscribeGraphAPI(self, query: str, callbackFunction: Callable[[Optional[ControllerGraphClientException], Optional[dict]], None], variables: Optional[dict] = None, timeout: float = 5.0) -> Subscription:
        """Subscribes to changes on Mujin controller.

        Args:
            query (string): a query to subscribe to the service (e.g. "subscription {SubscribeWebStackState(interval:\"5s\"){synchronizer{messages}}}")
            variables (dict): variables that should be passed into the query if necessary
            callbackFunction (func): a callback function to process the response data that is received from the subscription
        """
        # create a new subscription
        subscriptionId = str(uuid.uuid4())
        subscription = Subscription(subscriptionId, callbackFunction)

        # Encode the start message up front so that unserializable data only fails this subscribe, rather than poisoning the shared connection.
        message: dict[str, Any] = {
            'id': subscriptionId,
            'type': 'start',
            'payload': {'query': query},
        }
        if variables:
            message['payload']['variables'] = variables
        try:
            encodedMessage = self.EncodeJSON(message)
        except Exception as error:
            raise ControllerGraphClientException(_('Failed to encode the subscribe request: %s') % (error,)) from error

        async def _Subscribe(webSocket: websockets.asyncio.client.ClientConnection):
            try:
                # start a new subscription on the WebSocket connection
                await webSocket.send(encodedMessage, text=True)
            except Exception as e:
                log.exception('caught WebSocket exception: %s', e)
                await self._StopAllSubscriptions(ControllerGraphClientException(_('Failed to subscribe: %s') % (e)), webSocket=webSocket)
                # Re-raise so that the caller waiting on this future learns the subscribe failed,
                # instead of being handed a subscription that no socket is backing.
                raise

        # This blocks on the event loop, so it cannot be reached from a subscription callback
        self._RejectCallFromEventLoop('SubscribeGraphAPI')

        # Make sure the websocket connection is running.
        # Done outside _subscriptionLock so the background event loop can take it on connect.
        try:
            self._EnsureWebSocketConnection(timeout=timeout)
        except Exception as error:
            raise ControllerGraphClientException(f'Failed to ensure websocket connection: {error}')

        with self._subscriptionLock:
            # Pin the connection that we run this subscribe operation on.
            # Otherwise, a connection replaced between here and the send fails the subscribe
            webSocket = self._webSocket
            if webSocket is None or webSocket.state is not websockets.protocol.State.OPEN:
                raise ControllerGraphClientException(_('WebSocket connection dropped before the subscribe could be sent'))
            # wait until the subscription is created
            future = self._backgroundThread.RunCoroutine(_Subscribe(webSocket))
        try:
            # wait for the subscribe outside _subscriptionLock to avoid deadlocking
            # with websocket callbacks that may acquire the same lock while resolving
            future.result(timeout=timeout)
        except Exception as e:
            raise ControllerGraphClientException(f'Failed to subscribe within timeout: {e}')
        with self._subscriptionLock:
            # The connection the start message went out on must still be the established one.
            # Had it been torn down while we waited, its teardown has already run and would never see this subscription,
            # which would leave it registered against a connection that is gone.
            if self._webSocket is not webSocket:
                raise ControllerGraphClientException(_('WebSocket connection dropped before the subscribe completed'))
            # Record the connection so that only its own teardown can fail this subscription
            subscription.SetWebSocket(webSocket)
            self._subscriptions[subscriptionId] = subscription
        return subscription

    def UnsubscribeGraphAPI(self, subscription: Subscription, timeout: float = 5.0):
        """Unsubscribes to Mujin controller.

        Args:
            subscription (Subscription): the subscription that the user wants to unsubscribe
        """
        subscriptionId = subscription.GetSubscriptionID()

        async def _Unsubscribe(webSocket: websockets.asyncio.client.ClientConnection):
            try:
                await webSocket.send(
                    self.EncodeJSON(
                        {
                            'id': subscriptionId,
                            'type': 'stop',
                        },
                    ),
                    text=True,
                )
            except Exception as e:
                log.exception('caught WebSocket exception: %s', e)
                await self._StopAllSubscriptions(ControllerGraphClientException(_('Failed to unsubscribe: %s') % (e)), webSocket=webSocket)

        # This blocks on the event loop, so it cannot be reached from a subscription callback
        self._RejectCallFromEventLoop('UnsubscribeGraphAPI')

        with self._subscriptionLock:
            # check if self._subscriptionIds has subscriptionId
            if subscriptionId not in self._subscriptions:
                return
            # nothing to send if the websocket is not established, but still drop the subscription
            # below so that it cannot linger and hold the connection open forever
            webSocket = self._webSocket
            if webSocket is None or webSocket.state is not websockets.protocol.State.OPEN:
                future = None
            else:
                # request unsubscribe under lock, pinned to the connection it is being sent on
                future = self._backgroundThread.RunCoroutine(_Unsubscribe(webSocket))
        if future is not None:
            try:
                # wait for the async result outside the lock
                future.result(timeout=timeout)
            except Exception as e:
                log.exception('timeout or error while unsubscribing: %s', e)

        # re-acquire lock to safely modify the dictionary and check for shutdown
        with self._subscriptionLock:
            self._subscriptions.pop(subscriptionId, None)

            # Close the websocket connection if no more subscribers are left.
            # Name the connection so that the close can tell whether a subscribe has claimed it by the time it runs
            if len(self._subscriptions) == 0 and self._IsWebSocketConnectionOpen():
                self._backgroundThread.RunCoroutine(self._CloseIdleWebSocket(self._webSocket))

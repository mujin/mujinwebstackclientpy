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
import os
import requests
import threading
import traceback
import uuid
import copy
import websockets
from requests import auth as requests_auth
from requests import adapters as requests_adapters
from typing import Optional, Callable, Dict, Any, Union, List
from urllib.parse import urlparse

import websockets.asyncio
import websockets.asyncio.client

from . import _
from . import json
from . import APIServerError, WebstackClientError, ControllerGraphClientException
from .unixsocketadapter import UnixSocketAdapter

import logging

logging.getLogger('websockets').setLevel(logging.WARNING)
log = logging.getLogger(__name__)


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

    def __init__(self, subscriptionId: str, callbackFunction: Callable[[Optional[ControllerGraphClientException], Optional[dict]], None]):
        self._subscriptionId = subscriptionId
        self._subscriptionCallbackFunction = callbackFunction

    def GetSubscriptionID(self) -> str:
        return self._subscriptionId

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
        self._thread = threading.Thread(target=self._RunEventLoop)
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


class ControllerWebClientRaw(object):
    _baseurl = None  # Base URL of the controller
    _username = None  # Username to login with
    _password = None  # Password to login with
    _headers = None  # Prepared headers for all requests
    _isok = False  # Flag to stop
    _session = None  # Requests session object
    _webSocket: websockets.asyncio.client.ClientConnection = None  # WebSocket used to connect to WebStack for subscriptions
    _subscriptions: dict[str, Subscription]  # Dictionary that stores the subscriptionId(key) and the corresponding subscription(value)
    _subscriptionLock: threading.Lock  # Lock protecting _webSocket and _subscriptions
    _backgroundThread: BackgroundThread = None  # The background thread to handle async operations

    _threadName: Optional[str] = None  # The last thread this client was used in if we're warning on calls from different threads.

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
            # make sure to stop subscriptions and close the websocket first
            with self._subscriptionLock:
                self._backgroundThread.RunCoroutine(self._StopAllSubscriptions(ControllerGraphClientException(_('Shutting down')))).result()
            # next destroy the thread
            self._backgroundThread.Destroy()
            self._backgroundThread = None

    def SetDestroy(self):
        self._isok = False

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

        # set the default body data only if no files are given
        if data is None and files is None:
            data = {}

        if headers is None:
            headers = {}

        # Default to json content type if not using multipart/form-data
        if 'Content-Type' not in headers and files is None:
            headers['Content-Type'] = 'application/json'
            data = json.dumps(data)

        if 'Accept' not in headers:
            headers['Accept'] = 'application/json'

        method = method.upper()
        response = self.Request(method, path, params=params, data=data, files=files, headers=headers, timeout=timeout)

        # Try to parse response
        raw = response.content.decode('utf-8', 'replace').strip()
        content: Optional[Dict[str, Any]] = None
        if len(raw) > 0:
            try:
                content = json.loads(raw)
            except ValueError as e:
                log.exception('caught exception parsing json response: %s: %s', e, raw)
                raise APIServerError(_('Unable to parse server response %d: %s') % (response.status_code, raw))

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
            data=json.dumps(
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
                content = json.loads(raw)
            except ValueError as e:
                log.exception('caught exception parsing json response: %s: %s', e, raw)

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

    def _EnsureWebSocketConnection(self):
        if self._backgroundThread is None:
            # create the background thread for async operations
            self._backgroundThread = BackgroundThread()
        if self._webSocket is None:
            # wait until the connection is established
            self._backgroundThread.RunCoroutine(self._OpenWebSocketConnection()).result()
            # start listening without blocking
            self._backgroundThread.RunCoroutine(self._ListenToWebSocket())

    def _IsWebSocketConnectionOpen(self):
        return self._webSocket is not None

    async def _CloseWebSocket(self):
        if self._webSocket is not None:
            await self._webSocket.close()
            self._webSocket = None

    async def _OpenWebSocketConnection(self):
        authorization = self._session.auth.GetAuthorizationHeader()

        # URL to http GraphQL endpoint on Mujin controller
        graphEndpoint = '%s/api/v2/graphql' % self._baseurl
        parsedUrl = urlparse(graphEndpoint)
        # parse url and handle different scheme
        webSocketScheme = ''
        if parsedUrl.scheme == 'https':
            webSocketScheme = 'wss'
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
            self._webSocket = await websockets.unix_connect(
                path=adapter.get_unix_endpoint(),
                uri=uri,
                subprotocols=subprotocols,
                additional_headers=headers,
            )
        else:
            self._webSocket = await websockets.connect(
                uri=uri,
                subprotocols=subprotocols,
                additional_headers=headers,
            )

        await self._webSocket.send(
            json.dumps(
                {
                    'type': 'connection_init',
                    'payload': {
                        'Authorization': authorization,
                    },
                },
            ),
        )

    async def _ListenToWebSocket(self):
        try:
            async for response in self._webSocket:
                # stop if stop is requested
                if not self._isok:
                    break

                # parse the result
                content = None
                if len(response) > 0:
                    try:
                        content = json.loads(response)
                    except ValueError as e:
                        log.exception('caught exception parsing json response: %s: %s', e, response)

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
                with self._subscriptionLock:
                    # select the right subscription
                    subscriptionId = content['id']
                    subscription = self._subscriptions.get(subscriptionId)
                    if subscription is None:
                        # subscriber is gone
                        continue

                    # return if there is an error
                    if 'payload' in content and 'errors' in content['payload'] and len(content['payload']['errors']) > 0:
                        message = content['payload']['errors'][0].get('message', response)
                        errorCode = None
                        if 'extensions' in content['payload']['errors'][0]:
                            errorCode = content['payload']['errors'][0]['extensions'].get('errorCode', None)
                        subscription.GetSubscriptionCallbackFunction()(error=ControllerGraphClientException(message, content=content, errorCode=errorCode), response=None)
                        continue

                    # return the payload
                    subscription.GetSubscriptionCallbackFunction()(error=None, response=content.get('payload') or {})

        except Exception as e:
            log.exception('caught WebSocket exception: %s', e)
            with self._subscriptionLock:
                await self._StopAllSubscriptions(ControllerGraphClientException(_('Failed to listen to WebSocket: %s') % (e)))

    async def _StopAllSubscriptions(self, error: Optional[ControllerGraphClientException]):
        """Needs to run under self._subscriptionLock"""
        # close the websocket
        await self._CloseWebSocket()
        # send a message back to the callers using the callback function and drop all subscriptions
        for subscriptionId, subscription in self._subscriptions.items():
            subscription.GetSubscriptionCallbackFunction()(error=error, response=None)
        self._subscriptions.clear()

    def SubscribeGraphAPI(self, query: str, callbackFunction: Callable[[Optional[ControllerGraphClientException], Optional[dict]], None], variables: Optional[dict] = None) -> Subscription:
        """Subscribes to changes on Mujin controller.

        Args:
            query (string): a query to subscribe to the service (e.g. "subscription {SubscribeWebStackState(interval:\"5s\"){synchronizer{messages}}}")
            variables (dict): variables that should be passed into the query if necessary
            callbackFunction (func): a callback function to process the response data that is received from the subscription
        """
        # create a new subscription
        subscriptionId = str(uuid.uuid4())
        subscription = Subscription(subscriptionId, callbackFunction)

        async def _Subscribe():
            try:
                # start a new subscription on the WebSocket connection
                message = {
                    'id': subscription.GetSubscriptionID(),
                    'type': 'start',
                    'payload': {'query': query},
                }
                if variables:
                    message['payload']['variables'] = variables
                await self._webSocket.send(json.dumps(message))
            except Exception as e:
                log.exception('caught WebSocket exception: %s', e)
                await self._StopAllSubscriptions(ControllerGraphClientException(_('Failed to subscribe: %s') % (e)))

        with self._subscriptionLock:
            # make sure the websocket connection is running
            self._EnsureWebSocketConnection()

            # wait until the subscription is created
            self._backgroundThread.RunCoroutine(_Subscribe()).result()
            self._subscriptions[subscriptionId] = subscription

            return subscription

    def UnsubscribeGraphAPI(self, subscription: Subscription):
        """Unsubscribes to Mujin controller.

        Args:
            subscription (Subscription): the subscription that the user wants to unsubscribe
        """
        subscriptionId = subscription.GetSubscriptionID()

        async def _Unsubscribe():
            try:
                # check if self._subscriptionIds has subscriptionId
                if subscriptionId in self._subscriptions:
                    await self._webSocket.send(
                        json.dumps(
                            {
                                'id': subscriptionId,
                                'type': 'stop',
                            },
                        ),
                    )
                    # remove subscription
                    self._subscriptions.pop(subscriptionId, None)

                # close the websocket connection if no more subscribers are left
                if len(self._subscriptions) == 0:
                    await self._CloseWebSocket()
            except Exception as e:
                log.exception('caught WebSocket exception: %s', e)
                await self._StopAllSubscriptions(ControllerGraphClientException(_('Failed to unsubscribe: %s') % (e)))

        with self._subscriptionLock:
            # nothing to do if websocket is not established
            if not self._IsWebSocketConnectionOpen():
                return

            # check if the subscription exists at all
            if subscription.GetSubscriptionID() not in self._subscriptions:
                return

            # actually unsubscribe and wait until there is a result
            self._backgroundThread.RunCoroutine(_Unsubscribe()).result()

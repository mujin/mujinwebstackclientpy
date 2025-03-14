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
import websockets
from requests import auth as requests_auth
from requests import adapters as requests_adapters
from typing import Optional, Callable
from urllib.parse import urlparse

import websockets.asyncio
import websockets.asyncio.client

from . import _
from . import json
from . import APIServerError, WebstackClientError, ControllerGraphClientException
from .unixsocketadapter import UnixSocketAdapter

import logging
log = logging.getLogger(__name__)

class JSONWebTokenAuth(requests_auth.AuthBase):
    """Attaches JWT Bearer Authentication to a given Request object. Use basic authentication if token is not available.
    """
    _username = None # controller username
    _password = None # controller password
    _jsonWebToken = None # json web token
    _encodedUsernamePassword: str # Encoded Mujin controller's username and password

    def __init__(self, username, password):
        self._username = username
        self._password = password
        usernamePassword = '%s:%s' % (username, password)
        self._encodedUsernamePassword = base64.b64encode(usernamePassword.encode('utf-8')).decode('ascii')

    def __eq__(self, other):
        return all([
            self._username == getattr(other, '_username', None),
            self._password == getattr(other, '_password', None),
            self._jsonWebToken == getattr(other, '_jsonWebToken', None),
        ])

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
    
class Subscription:
    """Subscription that contains the unique subscription id for every subscription.
    """
    _subscriptionId: str # subscription id
    _subscriptionCallbackFunction: Callable # subscription callback function

    def __init__(
        self,
        subscriptionId: str,
        callbackFunction: Callable,
    ):
        self._subscriptionId = subscriptionId
        self._subscriptionCallbackFunction = callbackFunction

    def GetSubscriptionID(self) -> str:
        return self._subscriptionId

    def GetSubscriptionCallbackFunction(self) -> Callable:
        return self._subscriptionCallbackFunction

class ControllerWebClientRaw(object):

    _baseurl = None  # Base URL of the controller
    _username = None  # Username to login with
    _password = None  # Password to login with
    _headers = None  # Prepared headers for all requests
    _isok = False  # Flag to stop
    _session = None  # Requests session object
    _websocket: websockets.asyncio.client.ClientConnection # Websocket used to connect to webstack for subscriptions
    _subscriptions: dict[str, Subscription] # Dictionary that stores the subscriptionId(key) and the corresponding subscription(value)
    _eventLoopThread: threading.Thread # A thread to run the event loop
    _eventLoop: asyncio.AbstractEventLoop # Event loop that is running so that client can add coroutine(a subscription in this case)

    def __init__(self, baseurl, username, password, locale=None, author=None, userAgent=None, additionalHeaders=None, unixEndpoint=None):
        self._baseurl = baseurl
        self._username = username
        self._password = password
        self._headers = {}
        self._isok = True

        self._eventLoop = None
        self._eventLoopThread = None
        self._websocket = None
        self._subscriptions = {}

        # Create session
        self._session = requests.Session()

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

    def __del__(self):
        self.Destroy()
        self._CloseEventLoop()

    def Destroy(self):
        self.SetDestroy()

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

    def _InitializeEventLoopThread(self):
        # Create new event loop if _eventLoop is None, otherwise, reuse the existed one
        if self._eventLoop is None:
            self._eventLoop = asyncio.new_event_loop()
        if self._eventLoopThread is not None and self._eventLoopThread.is_alive():
            self._eventLoopThread.join()
        self._eventLoopThread = threading.Thread(target=self._RunEventLoop)
        self._eventLoopThread.start()

    def _RunEventLoop(self):
        asyncio.set_event_loop(self._eventLoop)
        while self._eventLoop is not None:
            self._eventLoop.run_forever()

    def _StopEventLoop(self):
        if self._eventLoop is None:
            return

        self._eventLoop.stop()

    def _CloseEventLoop(self):
        if self._eventLoop is None:
            return

        if self._eventLoop.is_running():
            self._eventLoop.call_soon_threadsafe(self._StopEventLoop)
            self._eventLoopThread.join()
        
        self._eventLoop.close()

    def Request(self, method, path, timeout=5, headers=None, **kwargs):
        if timeout < 1e-6:
            raise WebstackClientError(_('Timeout value (%s sec) is too small') % timeout)

        url = self._baseurl + path

        # Set all the headers prepared for this client
        headers = dict(headers or {})
        headers.update(self._headers)

        if 'allow_redirects' not in kwargs:
            # by default, disallow redirect since DELETE with redirection is too dangerous
            kwargs['allow_redirects'] = method in ('GET',)

        response = self._session.request(method=method, url=url, timeout=timeout, headers=headers, **kwargs)

        # in verbose logging, log the caller
        if log.isEnabledFor(5): # logging.VERBOSE might not be available in the system
            log.verbose('request %s %s response %s took %.03f seconds:\n%s', method, url, response.status_code, response.elapsed.total_seconds(), '\n'.join([line.strip() for line in traceback.format_stack()[:-1]]))
        return response

    # Python port of the javascript API Call function
    def APICall(self, method, path='', params=None, fields=None, data=None, headers=None, expectedStatusCode=None, files=None, timeout=5, apiVersion='v1'):
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
        content = None
        if len(raw) > 0:
            try:
                content = json.loads(raw)
            except ValueError as e:
                log.exception('caught exception parsing json response: %s: %s', e, raw)
                raise APIServerError(_('Unable to parse server response %d: %s') % (response.status_code, raw))

        # First check error
        if content is not None and 'error_message' in content:
            raise APIServerError(content['error_message'], errorcode=content.get('error_code', None), inputcommand=path, detailInfoType=content.get('detailInfoType',None), detailInfo=content.get('detailInfo',None))

        if content is not None and 'error' in content:
            raise APIServerError(content['error'].get('message', raw), inputcommand=path)

        if response.status_code >= 400:
            raise APIServerError(_('Unexpected server response %d: %s') % (response.status_code, raw))

        # TODO(ziyan): Figure out the expected status code from method
        #              Some APIs were mis-implemented to not return standard status code.
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

    def CallGraphAPI(self, query, variables=None, headers=None, timeout=5.0):
        # prepare the headers
        if headers is None:
            headers = {}
        headers['Content-Type'] = 'application/json'
        headers['Accept'] = 'application/json'

        # make the request
        response = self.Request('POST', '/api/v2/graphql', headers=headers, data=json.dumps({
            'query': query,
            'variables': variables or {},
        }), timeout=timeout)

        # try to parse response
        raw = response.content.decode('utf-8', 'replace').strip()

        # repsonse must be 200 OK
        statusCode = response.status_code
        if statusCode != 200:
            raise ControllerGraphClientException(_('Unexpected server response %d: %s') % (statusCode, raw), statusCode=statusCode, response=response)

        # decode the response content
        content = None
        if len(raw) > 0:
            try:
                content = json.loads(raw)
            except ValueError as e:
                log.exception('caught exception parsing json response: %s: %s', e, raw)

        # raise any error returned
        if content is not None and 'errors' in content and len(content['errors']) > 0:
            message = content['errors'][0].get('message', raw)
            errorCode = None
            if 'extensions' in content['errors'][0]:
                errorCode = content['errors'][0]['extensions'].get('errorCode', None)
            raise ControllerGraphClientException(message, statusCode=statusCode, content=content, response=response, errorCode=errorCode)

        if content is None or 'data' not in content:
            raise ControllerGraphClientException(_('Unexpected server response %d: %s') % (statusCode, raw), statusCode=statusCode, response=response)

        return content['data']

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
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-CSRFToken': 'token',
        }
        subprotocols = ['graphql-ws']

        # decide on using unix socket or not
        adapter = self._session.adapters.get('http://')
        if isinstance(adapter, UnixSocketAdapter):
            self._websocket = await websockets.unix_connect(
                path=adapter.get_unix_endpoint(),
                uri=uri,
                subprotocols=subprotocols,
                additional_headers=headers,
            )
        else:
            self._websocket = await websockets.connect(
                uri=uri,
                subprotocols=subprotocols,
                additional_headers=headers,
            )

        await self._websocket.send(json.dumps({
            'type': 'connection_init',
            'payload': {
                'Authorization': authorization,
            }
        }))
        # create a coroutine that is specially used for listening to the websocket
        asyncio.run_coroutine_threadsafe(self._ListenToWebSocket(), self._eventLoop)
    
    async def _ListenToWebSocket(self):
        try:
            async for response in self._websocket:
                data = json.loads(response)
                if data['type'] == 'connection_ack':
                    log.debug('received connection_ack')
                elif data['type'] == 'ka':
                    # received keep-alive "ka" message
                    pass
                else:
                    # parse to get the subscriptionId so that we can call the correct callback function
                    subscriptionId = data.get('id')
                    if subscriptionId in self._subscriptions:
                        subscription = self._subscriptions[subscriptionId]
                        subscription.GetSubscriptionCallbackFunction()(data.get('payload') or {})
        except websockets.exceptions.ConnectionClosed:
            log.error('webSocket connection closed')
            self._websocket = None
            # send a message back to the caller using the callback function and drop all subscriptions
            for subscriptionId, subscription in self._subscriptions.items():
                subscription.GetSubscriptionCallbackFunction()({'errorMessage': 'webSocketConnectionClosed'})
            self._subscriptions.clear()

    def SubscribeGraphAPI(self, query: str, callbackFunction: Callable, variables: Optional[dict] = None) -> Subscription:
        """ Subscribes to changes on Mujin controller.

        Args:
            query (string): a query to subscribe to the service (e.g. "subscription {SubscribeWebStackState(interval:\"5s\"){synchronizer{messages}}}")
            variables (dict): variables that should be passed into the query if necessary
            callbackFunction (func): a callback function to process the response data that is received from the subscription
        """
        # generate subscriptionId, an unique id to sent to the server so that we can have multiple subscriptions using the same websocket
        subscriptionId = str(uuid.uuid4())
        subscription = Subscription(subscriptionId, callbackFunction)
        self._subscriptions[subscriptionId] = subscription
        if self._eventLoop is None or not self._eventLoop.is_running:
            self._InitializeEventLoopThread()

        async def _Subscribe():
            # check if _websocket exists
            if self._websocket is None:
                await self._OpenWebSocketConnection()

            # start a new subscription on the WebSocket connection
            await self._websocket.send(json.dumps({
                'id': subscriptionId,
                'type': 'start',
                'payload': {'query': query, 'variables': variables or {}}
            }))

        asyncio.run_coroutine_threadsafe(_Subscribe(), self._eventLoop)
        return subscription

    def UnsubscribeGraphAPI(self, subscription: Subscription):
        """ Unsubscribes to Mujin controller.

        Args:
            subscription (Subscription): the subscription that the user wants to unsubscribe
        """
        async def _StopSubscription():
            subscriptionId = subscription.GetSubscriptionID()
            # check if self._subscriptionIds has subscriptionId
            if subscriptionId in self._subscriptions:
                await self._websocket.send(json.dumps({
                    'id': subscriptionId,
                    'type': 'stop'
                }))
                # remove subscription
                self._subscriptions.pop(subscription.GetSubscriptionID(), None)

        asyncio.run_coroutine_threadsafe(_StopSubscription(), self._eventLoop)

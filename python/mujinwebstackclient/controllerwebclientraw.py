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
from typing import Optional, Callable, Dict, Any

from . import _
from . import json
from . import APIServerError, WebstackClientError, ControllerGraphClientException
from .unixsocketadapter import UnixSocketAdapter

import logging
log = logging.getLogger(__name__)
logging.getLogger('websockets').setLevel(logging.CRITICAL)

class JSONWebTokenAuth(requests_auth.AuthBase):
    """Attaches JWT Bearer Authentication to a given Request object. Use basic authentication if token is not available.
    """
    _username = None # controller username
    _password = None # controller password
    _jsonWebToken = None # json web token

    def __init__(self, username, password):
        self._username = username
        self._password = password

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

    def __call__(self, request):
        if self._jsonWebToken is not None:
            request.headers['Authorization'] = 'Bearer %s' % self._jsonWebToken
        else:
            requests_auth.HTTPBasicAuth(self._username, self._password)(request)
            request.register_hook('response', self._SetJSONWebToken)
        return request

class ControllerWebClientRaw(object):

    _baseurl = None  # Base URL of the controller
    _username = None  # Username to login with
    _password = None  # Password to login with
    _headers = None  # Prepared headers for all requests
    _isok = False  # Flag to stop
    _session = None  # Requests session object
    _graphEndpoint = None # URL to http GraphQL endpoint on Mujin controller
    _encodedUsernamePassword = None # Encoded Mujin controller's username and password
    _websocket = None # Websocket used to connect to webstack for subscriptions
    _subscriptionIds = [] # List that stores the subscriptionId
    _subscriptionCallbacks = {} # Dictionary that stores the subscriptionId(key) and its callback function(value)

    def __init__(self, baseurl, username, password, locale=None, author=None, userAgent=None, additionalHeaders=None, unixEndpoint=None):
        self._baseurl = baseurl
        self._username = username
        self._password = password
        self._headers = {}
        self._isok = True

        self._graphEndpoint = '%s/api/v2/graphql' % baseurl
        usernamePassword = '%s:%s' % (username, password)
        self._encodedUsernamePassword = base64.b64encode(usernamePassword.encode('utf-8')).decode('ascii')
        # Create new event loop that is running in the MainThread so that client can add coroutine(a subscription in this case)
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self.RunLoop, args=()).start()

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

    def RunLoop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

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

    def _Callback(self, response: Dict[str, Any]):
        # tmp: simply print the response
        print(response)

    async def _OpenWebSocketConnection(self):
        self._websocket = await websockets.connect(
            uri='ws%s' % self._graphEndpoint[len('http'):],
            subprotocols=['graphql-ws'],
            additional_headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-CSRFToken': 'token',
                'Authorization': 'Basic %s' % self._encodedUsernamePassword,
            },
        )
        await self._websocket.send(json.dumps({'type': 'connection_init', 'payload': {}}))
        # create a coroutine that is specially used for listening to the websocket
        asyncio.run_coroutine_threadsafe(self._ListenToWebsocket(), self._loop)
    
    async def _ListenToWebsocket(self):
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
                    if subscriptionId in self._subscriptionCallbacks:
                        self._subscriptionCallbacks[subscriptionId](data['payload'])
        except websockets.exceptions.ConnectionClosed:
            log.error("webSocket connection closed")
            self._websocket = None
        except asyncio.CancelledError:
            log.error("webSocket listener cancelled")

    def SubscribeGraphAPI(self, query: str, variables: Optional[dict] = None, callbackFunction: Callable = None):
        """ Subscribes to changes on Mujin controller.

        Args:
            query (string): a query to subscribe to the service (e.g. "subscription {SubscribeWebStackState(interval:\"5s\"){synchronizer{messages}}}")
            variables (dict): variables that should be passed into the query if necessary
            callbackFunction (func): a callback function to process the response data that is received from the subscription
        """
        if callbackFunction is None:
            callbackFunction = self._Callback

        # generate subscriptionId, an unique id to sent to the server so that we can have multiple subscriptions using the same websocket
        subscriptionId = str(uuid.uuid4())

        async def _Subscribe(callbackFunction):
            # try:
                # check if _websocket exists
                if self._websocket is None:
                    await self._OpenWebSocketConnection()

                # store the callback function
                self._subscriptionCallbacks[subscriptionId] = callbackFunction

                # start a new subscription on the WebSocket connection
                await self._websocket.send(json.dumps({
                    'id': subscriptionId,
                    'type': 'start',
                    'payload': {'query': query, 'variables': variables or {}}
                }))

        asyncio.run_coroutine_threadsafe(_Subscribe(callbackFunction), self._loop)
        self._subscriptionIds.append(subscriptionId)
        return subscriptionId

    def Unsubscribe(self, subscriptionId):
        async def _StopSubscription():
            # check if self._subscriptionIds has subscriptionId
            if subscriptionId in self._subscriptionIds:
                await self._websocket.send(json.dumps({
                    'id': subscriptionId,
                    'type': 'stop',
                    'payload': {}
                }))
                # remove subscription's subscriptionId and callback function
                self._subscriptionIds.remove(subscriptionId)
                self._subscriptionCallbacks.pop(subscriptionId, None)

        asyncio.run_coroutine_threadsafe(_StopSubscription(), self._loop)

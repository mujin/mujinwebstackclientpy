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

import traceback
import os
import requests
from requests import auth as requests_auth
from requests import adapters as requests_adapters

from . import _
from . import json
from . import APIServerError, WebstackClientError, ControllerGraphClientException
from .unixsocketadapter import UnixSocketAdapter

import logging
log = logging.getLogger(__name__)


class ControllerWebClientRaw(object):

    _baseurl = None  # Base URL of the controller
    _username = None  # Username to login with
    _password = None  # Password to login with
    _headers = None  # Prepared headers for all requests
    _isok = False  # Flag to stop
    _session = None  # Requests session object

    def __init__(self, baseurl, username, password, locale=None, author=None, userAgent=None, additionalHeaders=None, unixEndpoint=None):
        self._baseurl = baseurl
        self._username = username
        self._password = password
        self._headers = {}
        self._isok = True

        # Create session
        self._session = requests.Session()

        # Use basic auth
        self._session.auth = requests_auth.HTTPBasicAuth(self._username, self._password)

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

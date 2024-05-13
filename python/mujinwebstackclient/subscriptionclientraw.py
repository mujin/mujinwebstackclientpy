import base64
import time
import abc
import six
import socket
import threading
from six.moves.urllib_parse import urlparse
import json

import websocket

from . import ClientExceptionBase, webstackgraphclientutils

import logging
log = logging.getLogger(__name__)


class GraphSubscriber(object):
    def Connected(self):
        pass

    def ReceivedMessage(self, message):
        pass

    def Disconnected(self, error):
        pass

    def Closed(self, errors=None):
        pass


class SingleGraphSubscriber(GraphSubscriber):
    _subscriber = None
    _subscriptionName = None

    def __init__(self, subscriber, subscriptionName):
        self._subscriber = subscriber
        self._subscriptionName = subscriptionName

    def Connected(self):
        self._subscriber.Connected()

    def ReceivedMessage(self, message):
        message = message.get(self._subscriptionName)
        if message:
            self._subscriber.ReceivedMessage(message)

    def Disconnected(self, error):
        self._subscriber.Disconnected(error)

    def Closed(self, errors=None):
        self._subscriber.Closed(errors)


class GraphSubscriptionBase(object):
    _timeout = 5  # webstack side is 1 second heartbeat

    _lock = None  # type: threading.Lock
    _background = None  # type: threading.Thread
    _socket = None  # type: websocket.WebSocket
    _subscriptions = None  # dictionary of id to (subscriber, subscription, variables)
    _id = 0  # increment id for request
    _running = False  # if the thread should be running
    _websocketUrl = None  # url of websocket
    _unixEndpoint = None  # unix endpoint to connect to, if any
    _headers = None  # headers for the request

    def __init__(self, controllerUrl='http://127.0.0.1', controllerUsername=None, controllerPassword=None, unixEndpoint=None):
        self._lock = threading.Lock()
        self._subscriptions = {}

        parseResult = urlparse(controllerUrl)

        if parseResult.scheme == 'http':
            websocketUrl = 'ws://'
        elif parseResult.scheme == 'https':
            websocketUrl = 'wss://'
        else:
            raise ValueError('Invalid URL scheme')

        if parseResult.username:
            controllerUsername = parseResult.username
        if parseResult.password:
            controllerPassword = parseResult.password

        websocketUrl += parseResult.hostname
        if parseResult.port:
            websocketUrl += ':' + str(parseResult.port)

        websocketUrl += '/api/v2/graphql'

        self._websocketUrl = websocketUrl
        self._unixEndpoint = unixEndpoint
        self._headers = {}

        if controllerUsername and controllerPassword:
            self._headers['Authorization'] = 'Basic ' + base64.b64encode(controllerUsername + ':' + controllerPassword)

        self._CreateWebsocket()

        self._background = threading.Thread(target=self._RunBackgroundThread)
        self._running = True
        self._background.start()

    def __del__(self):
        self.Destroy()

    def Destroy(self):
        with self._lock:
            self._running = False
            if self._socket is not None:
                self._socket.close()
        if self._background is not None:
            self._background.join()
            self._background = None

    def _RunBackgroundThread(self):
        while True:
            try:
                with self._lock:
                    if not self._running:
                        break
                    if self._socket is None:
                        self._CreateWebsocket()
            except Exception:
                log.exception('error creating websocket connection')
                time.sleep(1)  # TODO

            try:
                frameType, data = self._socket.recv_data()
            except websocket.WebSocketException as exception:
                self._Disconnected(exception.message)
                continue

            if frameType == websocket.ABNF.OPCODE_CLOSE:
                log.warning('websocket closed: %r', data[2:])
                self._Disconnected(data[2:])
                continue
            if frameType != websocket.ABNF.OPCODE_TEXT:
                log.warning('received unexpected frame type: %r', frameType)
                continue

            message = json.loads(data)
            messageType = message.get('type')
            if messageType == 'ka':
                continue

            if messageType != 'data':
                log.warning('received unexpected message type: %r', messageType)
                continue

            messageId = message.get('id')
            with self._lock:
                handle = self._subscriptions.get(messageId)
            if not handle:
                log.warning('received unknown message id: %r', messageId)
                continue

            payload = message.get('payload') or {}
            errors = payload.get('errors')
            if errors:
                with self._lock:
                    handle = self._subscriptions.pop(messageId, None)
                if handle:
                    subscriber = handle[0]
                    subscriber.Closed(errors)
            else:
                data = payload.get('data')
                if data:
                    subscriber = handle[0]
                    subscriber.ReceivedMessage(data)
        with self._lock:
            for handle in six.itervalues(self._subscriptions):
                try:
                    handle[0].Closed()
                except Exception:
                    log.exception('error calling subscriber.Closed')

    def _Disconnected(self, error):
        with self._lock:
            self._socket.close()
            self._socket = None

            for handle in six.itervalues(self._subscriptions):
                handle[0].Disconnected(error)

    def _CreateWebsocket(self):
        assert self._socket is None
        self._socket = websocket.WebSocket(enable_multithread=True)

        if self._unixEndpoint:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self._unixEndpoint)
            self._socket.connect(self._websocketUrl, header=self._headers, socket=sock, timeout=self._timeout)
        else:
            self._socket.connect(self._websocketUrl, header=self._headers, timeout=self._timeout)

        self._socket.send(json.dumps({
            'type': 'connection_init'
        }))
        frameType, data = self._socket.recv_data()
        if frameType == websocket.ABNF.OPCODE_CLOSE:
            reason = data[2:]
            raise ClientExceptionBase(reason)
        elif frameType != websocket.ABNF.OPCODE_TEXT:
            raise ClientExceptionBase('unexpected frame type %s' % frameType)
        response = json.loads(data)
        assert response.get('type') == 'connection_ack'

        # resubscribe to all
        for id, handle in six.iteritems(self._subscriptions):
            self._SendSubscription(id, *handle)

    def _SubscribeGraphAPI(self, subscription, variables, subscriber):
        with self._lock:
            self._id += 1
            id = str(self._id)
            self._subscriptions[id] = (subscriber, subscription, variables)
            if self._socket is not None:
                self._SendSubscription(id, subscriber, subscription, variables)
        return id

    def _SubscribeSimpleGraphAPI(self, subscriber, subscriptionName, parameterNameTypeValues, returnType, fields=None):
        if webstackgraphclientutils._IsScalarType(returnType):
            queryFields = ''  # scalar types cannot have subfield queries
        elif not fields:
            queryFields = '{ __typename }'  # query the __typename field if caller didn't want anything back
        else:
            queryFields = webstackgraphclientutils._StringifyQueryFields(fields)
        queryParameters = ', '.join([
            '$%s: %s' % (parameterName, parameterType)
            for parameterName, parameterType, parameterValue in parameterNameTypeValues
        ])
        if queryParameters:
            queryParameters = '(%s)' % queryParameters
        queryArguments = ', '.join([
            '%s: $%s' % (parameterName, parameterName)
            for parameterName, parameterType, parameterValue in parameterNameTypeValues
        ])
        if queryArguments:
            if queryFields:
                queryFields = ' %s' % queryFields
            queryArguments = '(%s)' % queryArguments
        query = 'subscription%(queryParameters)s {%(operationName)s%(queryArguments)s%(queryFields)s}' % {
            'operationName': subscriptionName,
            'queryParameters': queryParameters,
            'queryArguments': queryArguments,
            'queryFields': queryFields,
        }
        variables = {}
        for parameterName, parameterType, parameterValue in parameterNameTypeValues:
            variables[parameterName] = parameterValue
        return self._SubscribeGraphAPI(query, variables, SingleGraphSubscriber(subscriber, subscriptionName))

    def UnsubscribeGraphAPI(self, id):
        with self._lock:
            self._socket.send(json.dumps({
                'type': 'stop',
                'id': id,
            }))
            handle = self._subscriptions.pop(id, None)
        if not handle:
            return
        subscriber = handle[0]
        try:
            subscriber.Closed()
        except Exception:
            log.exception('error calling subscriber.Closed')

    def _SendSubscription(self, id, subscriber, subscription, variables):
        # assume self._lock is held and self._socket is not None
        try:
            self._socket.send(json.dumps({
                'id': id,
                'type': 'start',
                'payload': {
                    'query': subscription,
                    'variables': variables,
                }
            }))
        except websocket.WebSocketException:
            self._socket.close()
        try:
            subscriber.Connected()
        except Exception:
            log.exception('error calling subscriber.Connected')

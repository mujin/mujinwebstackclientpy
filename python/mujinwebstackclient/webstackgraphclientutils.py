# -*- coding: utf-8 -*-

from functools import wraps
import logging
log = logging.getLogger(__name__)

def _IsScalarType(typeName):
    return typeName in (
        # the followings are part of graphql spec
        'Int',
        'Float',
        'String',
        'Boolean',
        'ID',
        # the followings are mujin customized
        'Data',
        'Any',
        'Void',
        'DateTime',
    )

def _StringifyQueryFields(fields):
    selectedFields = []
    if isinstance(fields, dict):
        for fieldName, subFields in fields.items():
            if subFields:
                subQuery = _StringifyQueryFields(subFields)
                selectedFields.append('%s %s' % (fieldName, subQuery))
            else:
                selectedFields.append(fieldName)
    else:
        for fieldName in fields:
            selectedFields.append(fieldName)
    return '{%s}' % ', '.join(selectedFields)

class GraphClientBase(object):

    _webclient = None # an instance of ControllerWebClientRaw

    def __init__(self, webclient):
        self._webclient = webclient

    def _CallSimpleGraphAPI(self, queryOrMutation, operationName, parameterNameTypeValues, returnType, fields=None, timeout=None):
        """

        Args:
            queryOrMutation (string): either "query" or "mutation"
            operationName (string): name of the operation
            parameterNameTypeValues (list): list of tuple (parameterName, parameterType, parameterValue)
            returnType (string): name of the return type, used to construct query fields
            fields (list[string]): list of fieldName to filter for
            timeout (float): timeout in seconds
        """
        if timeout is None:
            timeout = 5.0
        queryFields = ''
        if _IsScalarType(returnType):
            queryFields = '' # scalar types cannot have subfield queries
        elif not fields:
            queryFields = '{ __typename }' # query the __typename field if caller didn't want anything back
        else:
            queryFields = _StringifyQueryFields(fields)
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
        query = '%(queryOrMutation)s %(operationName)s%(queryParameters)s {\n    %(operationName)s%(queryArguments)s%(queryFields)s\n}' % {
            'queryOrMutation': queryOrMutation,
            'operationName': operationName,
            'queryParameters': queryParameters,
            'queryArguments': queryArguments,
            'queryFields': queryFields,
        }
        variables = {}
        for parameterName, parameterType, parameterValue in parameterNameTypeValues:
            variables[parameterName] = parameterValue
        if log.isEnabledFor(5): # logging.VERBOSE might not be available in the system
            log.verbose('executing graph query with variables %r:\n\n%s\n', variables, query)
        data = self._webclient.CallGraphAPI(query, variables, timeout=timeout)
        if log.isEnabledFor(5): # logging.VERBOSE might not be available in the system
            log.verbose('got response from graph query: %r', data)
        return data.get(operationName)

def BreakLargeGraphQuery(queryFunction):
    """This decorator break a large graph query into a few small queries to prevent webstack from consuming too much memory.
    """
    @wraps(queryFunction)
    def inner(self, *args, **kwargs):
        options = kwargs.get('options', {'offset': 0, 'first': 0})
        if options.get('first', 0) != 0:
            return queryFunction(self, *args, **kwargs)

        iterator = GraphQueryIterator(queryFunction, *((self,) + args), **kwargs)
        data = [item for item in iterator]
        response = {iterator.keyName: data}
        if iterator.totalCount is not None:
            response[u'meta'] = {u'totalCount': iterator.totalCount}
        return response

    return inner

class GraphQueryIterator:
    """Converts a large graph query to a iterator. The iterator will internally query webstack with a few small queries
    example:

      iterator = GraphQueryIterator(client.graphApi.ListEnvironments, fields={'environments': {'id': None}})
      iterator = GraphQueryIterator(client.graphApi.ListEnvironments, fields={'environments': {'id': None}}, options={'first': 10, 'offset': 5})
      for body in GraphQueryIterator(client.graphApi.ListBodies, "test1", fields={'bodies': {'id': None}}):
          do_something(body['id'])
      for environment in GraphQueryIterator(client.graphApi.ListEnvironments, fields={'environments': {'id': None}}):
          do_something(environment['id'])
    """

    _queryFunction = None # the actual webstack client query function (e.g. client.graphApi.ListEnvironments) 
    _args = None # positional arguments supplied to the query function (e.g. environmentId)
    _kwargs = None # keyword arguments supplied to the query function (e.g. options={'first': 10, 'offset': 5}, fields={'environments': {'id': None}})
    _items = None # internal buffer for items retrieved from webstack
    _shouldStop = None # boolean flag indicates whether need to query webstack again
    _totalLimit = None # the number of items user requests (0 means no limit)
    _count = None # the number of items already returned to user
    _totalCount = None # the number of available items in webstack
    _keyName = None # the name of actual data in the dictionary retrieved from webstack (e.g. 'bodies', 'environments', 'geometries')

    def __init__(self, queryFunction, *args, **kwargs):
        """Initialize all internal variables
        """
        self._queryFunction = queryFunction
        self._args = args
        self._kwargs = kwargs
        self._items = []
        self._shouldStop = False
        if self._kwargs.get('options', None) is None:
            self._kwargs['options'] = {'offset': 0, 'first': 0}
        self._kwargs['options'].setdefault('offset', 0)
        self._kwargs['options'].setdefault('first', 0)
        self._totalLimit = self._kwargs['options']['first']
        self._count = 0
        if self._kwargs['options']['first'] > 0:
            self._kwargs['options']['first'] = min(self._kwargs['options']['first'], 100)
        else:
            self._kwargs['options']['first'] = 100
        self._kwargs.setdefault('fields', {})

    def __iter__(self):
        return self

    def __next__(self):
        """Retrieve the next item from iterator
           Required by Python3
        """
        return self.next()

    def next(self):
        """Retrieve the next item from iterator
            Required by Python2
        """

        # return an item from internal buffer if buffer is not empty
        if len(self._items) != 0:
            item = self._items[0]
            self._items = self._items[1:]
            self._count += 1
            return item

        # stop iteration if internal buffer is empty and no need to query webstack again
        if self._shouldStop:
            raise StopIteration

        # query webstack if buffer is empty
        rawResponse = self._queryFunction(*self._args, **self._kwargs)
        if 'meta' in rawResponse:
            self._totalCount = rawResponse['meta']['totalCount']
            del rawResponse['meta']
        if '__typename' in rawResponse:
            self._keyName = u'__typename'
            self._items = [rawResponse['__typename']]
        else:
            self._keyName, self._items = list(rawResponse.items())[0]
        self._kwargs['options']['offset'] += len(self._items)

        if len(self._items) < self._kwargs['options']['first']:
            # webstack does not have more items
            self._shouldStop = True
        if self._totalLimit != 0 and self._count + len(self._items) >= self._totalLimit:
            # all remaining items user requests are in internal buffer, no need to query webstack again
            self._shouldStop = True
            self._items = self._items[:self._totalLimit - self._count]
        
        return self.next()

    @property
    def keyName(self):
        """the name of actual data in the dictionary retrieved from webstack
           e.g. 'bodies', 'environments', 'geometries'
        """
        return self._keyName
    
    @property
    def totalCount(self):
        """the number of available items in webstack
        """
        return self._totalCount

# -*- coding: utf-8 -*-

from functools import wraps
import logging
import copy
from . import webstackclientutils
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

class GraphQueryIterator:
    """Converts a large graph query to a iterator. The iterator will internally query webstack with a few small queries
    Examples:

      iterator = GraphQueryIterator(client.graphApi.ListEnvironments, fields={'environments': {'id': None}})
      iterator = GraphQueryIterator(client.graphApi.ListEnvironments, fields={'environments': {'id': None}}, options={'first': 10, 'offset': 5})
      for body in GraphQueryIterator(client.graphApi.ListBodies, "test1", fields={'bodies': {'id': None}}):
          do_something(body['id'])
      for environment in GraphQueryIterator(client.graphApi.ListEnvironments, fields={'environments': {'id': None}}):
          do_something(environment['id'])
    """

    _queryFunction = None # the actual webstack client query function (e.g. client.graphApi.ListEnvironments) 
    _queryArgs = None # positional arguments supplied to the query function (e.g. environmentId)
    _queryKwargs = None # keyword arguments supplied to the query function (e.g. options={'first': 10, 'offset': 5}, fields={'environments': {'id': None}})
    _items = [] # internal buffer for items retrieved from webstack
    _shouldStop = False # boolean flag indicates whether need to query webstack again
    _initialLimit = None # the number of items user requests (0 means no limit)
    _count = 0 # the number of items already returned to user

    def __init__(self, queryFunction, *args, **kwargs):
        """Initialize all internal variables
        """
        # retrieve the actual query function instead of the wrapper function generated by UseLazyGraphQuery decorator
        if hasattr(queryFunction, "inner"):
            args = (queryFunction.__self__,) + args
            queryFunction = queryFunction.inner
        
        # save the query function and all parameters
        self._queryFunction = queryFunction
        self._queryArgs = copy.deepcopy(args)
        self._queryKwargs = copy.deepcopy(kwargs)

        # initialize limit and offset
        if self._queryKwargs.get('options') is None:
            self._queryKwargs['options'] = {'offset': 0, 'first': 0}
        self._queryKwargs['options'].setdefault('offset', 0)
        self._queryKwargs['options'].setdefault('first', 0)
        self._initialLimit = self._queryKwargs['options']['first']

        # update the current limit
        self._queryKwargs['options']['first'] = webstackclientutils.GetMaximumQueryLimit(self._initialLimit)

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
        rawResponse = self._queryFunction(*self._queryArgs, **self._queryKwargs)

        # ignore meta and typename in top level
        if 'meta' in rawResponse:
            del rawResponse['meta']
        if '__typename' in rawResponse:
            del rawResponse['__typename']
        
        # process actual data
        if not rawResponse:
            # no actual items
            raise StopIteration
        self._items = list(rawResponse.values())[0]
        self._queryKwargs['options']['offset'] += len(self._items)

        if len(self._items) < self._queryKwargs['options']['first']:
            # webstack does not have more items
            self._shouldStop = True
        if self._initialLimit != 0 and self._count + len(self._items) >= self._initialLimit:
            # all remaining items user requests are in internal buffer, no need to query webstack again
            self._shouldStop = True
            self._items = self._items[:self._initialLimit - self._count]
        
        return self.next()

class LazyGraphQuery(webstackclientutils.LazyQuery):
    """Wraps graph query response. Break large query into small queries automatically to save memory.
    """
    _keyName = None # the name of actual data in the dictionary retrieved from webstack (e.g. 'bodies', 'environments', 'geometries')
    _typeName = None # the top level typename in the dictionary retrieved from webstack (e.g. 'ListEnvironmentsReturnValue', 'ListBodiesReturnValue', 'ListGeometryReturnValue')
    _currentFields = None # the current fields used for querying webstack

    def __init__(self, queryFunction, *args, **kwargs):
        """Initialize all internal variables
        """
        # save the query function and all parameters
        self._queryFunction = queryFunction
        self._queryArgs = args
        self._queryKwargs = copy.deepcopy(kwargs)

        # initialize limit and offset
        if self._queryKwargs.get('options') is None:
            self._queryKwargs['options'] = {'offset': 0, 'first': 0}
        self._queryKwargs['options'].setdefault('offset', 0)
        self._queryKwargs['options'].setdefault('first', 0)
        self._initialOffset = self._queryKwargs['options']['offset']
        self._initialLimit = self._queryKwargs['options']['first']

        # initialize the selected fields
        if not self._queryKwargs.get('fields'):
            # if the user didn't select any field
            self._currentFields = {'__typename': None}
        else:
            self._currentFields = self._queryKwargs['fields']

        # initialize meta and total count
        self._currentFields.setdefault('meta', {})
        if type(self._currentFields['meta']) is dict:
            # do not modify fields if caller provided incorrect meta fields
            # e.g. client.graphApi.ListEnvironments(fields={'meta': None})
            self._currentFields['meta'].setdefault('totalCount', None)

        # get the meta only with a minimal webstack call
        self._currentOffset = self._initialOffset
        self._currentLimit = 1
        self._APICall()

        # update the current limit
        self._currentLimit = webstackclientutils.GetMaximumQueryLimit(self._initialLimit)

    def __iter__(self):
        if self._fetchedAll:
            return list.__iter__(self)
        # return an iterator with the original offset and limit values
        self._queryKwargs['fields'] = self._currentFields
        self._queryKwargs['options']['offset'] = self._initialOffset
        self._queryKwargs['options']['first'] = self._initialLimit
        return GraphQueryIterator(self._queryFunction, *self._queryArgs, **self._queryKwargs)
    
    def _APICall(self):
        """Make one webstack query
        """
        # fetch data starting from the requested offset and limit
        self._queryKwargs['fields'] = self._currentFields
        self._queryKwargs['options']['offset'] = self._currentOffset
        self._queryKwargs['options']['first'] = self._currentLimit

        # get the latest results
        data = self._queryFunction(*self._queryArgs, **self._queryKwargs)

        # process meta and __typename in the top level
        if 'meta' in data:
            self._totalCount = data['meta']['totalCount']
            del data['meta']
        if '__typename' in data:
            self._typeName = data['__typename']
            del data['__typename']

        # process actual data
        if data:
            # for example `'environments': [...]`
            self._keyName, self._items = list(data.items())[0]

    @property
    def keyName(self):
        """the name of actual data in the dictionary retrieved from webstack
           e.g. 'bodies', 'environments', 'geometries'
        """
        return self._keyName
    
    @property
    def typeName(self):
        """the top level typename in the dictionary retrieved from webstack
           e.g. 'ListEnvironmentsReturnValue', 'ListBodiesReturnValue', 'ListGeometryReturnValue'
        """
        return self._typeName

    def FetchAll(self):
        """fetch the complete query result from webstack
        """
        if self._fetchedAll:
            return
        self._queryKwargs['fields'] = self._currentFields
        self._queryKwargs['options']['offset'] = self._initialOffset
        self._queryKwargs['options']['first'] = self._initialLimit
        items = list(GraphQueryIterator(self._queryFunction, *self._queryArgs, **self._queryKwargs))
        list.__init__(self, items)
        self._fetchedAll = True
    
def UseLazyGraphQuery(queryFunction):
    """This decorator break a large graph query into a few small queries with the help of LazyGraphQuery class to prevent webstack from consuming too much memory.
    """
    @wraps(queryFunction)
    def wrapper(self, *args, **kwargs):
        if 'fields' in kwargs and not isinstance(kwargs['fields'], dict):
            kwargs['fields'] = {key: None for key in kwargs['fields']}
        queryResult = LazyGraphQuery(queryFunction, *((self,) + args), **kwargs)
        response = {}
        if queryResult.typeName is not None:
            response['__typename'] = queryResult.typeName
        if queryResult.keyName is not None:
            response[queryResult.keyName] = queryResult
        if 'totalCount' in kwargs.get('fields', {}).get('meta', {}):
            response['meta'] = {'totalCount': queryResult.totalCount}
        return response

    wrapper.inner = queryFunction
    return wrapper

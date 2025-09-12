#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import graphql  # require graphql-core pip package when generating python code

import logging

log = logging.getLogger(__name__)


def _ConfigureLogging(level=None):
    try:
        import mujincommon

        mujincommon.ConfigureRootLogger(level=level)
    except ImportError:
        logging.basicConfig(format='%(levelname)s %(name)s: %(funcName)s, %(message)s', level=logging.DEBUG)


def _ParseArguments():
    import argparse

    parser = argparse.ArgumentParser(description='Open a shell to use webstackclient')
    parser.add_argument('--loglevel', type=str, default=None, help='The python log level, e.g. DEBUG, VERBOSE, ERROR, INFO, WARNING, CRITICAL (default: %(default)s)')
    parser.add_argument('--url', type=str, default='http://127.0.0.1', help='URL of the controller (default: %(default)s)')
    parser.add_argument('--username', type=str, default='mujin', help='Username to login with (default: %(default)s)')
    parser.add_argument('--password', type=str, default='mujin', help='Password to login with (default: %(default)s)')
    return parser.parse_args()


def _FetchServerVersionAndSchema(url, username, password):
    from mujinwebstackclient.controllerwebclientraw import ControllerWebClientRaw

    webClient = ControllerWebClientRaw(url, username, password)
    response = webClient.Request('HEAD', '/')
    serverVersion = response.headers['Server'].split()[0]
    log.info('server version determined to be: %s', serverVersion)
    schema = graphql.build_client_schema(webClient.CallGraphAPI(graphql.get_introspection_query(descriptions=True), {}))
    return serverVersion, schema


def _DereferenceType(graphType):
    while hasattr(graphType, 'of_type'):
        graphType = graphType.of_type
    return graphType


def _CleanDocstring(docstring):
    """Clean up docstring formatting to match ruff standards."""
    if not docstring:
        return docstring
    # split into lines and strip trailing whitespace
    lines = [line.rstrip() for line in docstring.split('\n')]
    # remove leading empty lines
    while lines and not lines[0]:
        lines.pop(0)
    # remove trailing empty lines
    while lines and not lines[-1]:
        lines.pop()
    # collapse multiple consecutive empty lines into single empty lines
    resultLines = []
    isPreviousEmpty = False
    for line in lines:
        if line:
            resultLines.append(line)
            isPreviousEmpty = False
        elif not isPreviousEmpty:
            resultLines.append('')
            isPreviousEmpty = True
    return '\n'.join(resultLines)


def _IndentNewlines(string, indent='    ' * 5):
    """Indent new lines in a string. Used for multi-line descriptions."""
    return _CleanDocstring(string).replace('\n', '\n' + indent)


def _FormatTypeForDocstring(typeName):
    """Removes the exclamation mark and converts basic Golang types to Python types."""
    _typeName = str(typeName).replace('!', '')
    if _typeName == 'String':
        return 'str'
    elif _typeName == 'Int':
        return 'int'
    elif _typeName == 'Boolean':
        return 'bool'
    else:
        return _typeName


def _FormatTypeForAnnotation(typeName, isNullable=False):
    """Converts GraphQL types to Python type annotations."""
    _typeName = str(typeName).replace('!', '')
    if _typeName == 'String':
        pythonType = 'str'
    elif _typeName == 'Int':
        pythonType = 'int'
    elif _typeName == 'Boolean':
        pythonType = 'bool'
    elif _typeName == 'Float':
        pythonType = 'float'
    elif _typeName == 'Void':
        # Void functions return None in Python
        return 'None'
    elif _typeName.startswith('[') and _typeName.endswith(']'):
        # handle list types like [String!] -> List[str]
        innerType = _typeName[1:-1].replace('!', '')
        innerPythonType = _FormatTypeForAnnotation(innerType, False)
        pythonType = 'List[%s]' % innerPythonType
    else:
        # For complex types, use Any
        pythonType = 'Any'
    # wrap in Optional if nullable
    if isNullable:
        pythonType = 'Optional[%s]' % pythonType
    return pythonType


def _DiscoverType(graphType):
    baseFieldType = _DereferenceType(graphType)
    baseFieldTypeName = '%s' % baseFieldType
    return {
        'typeName': '%s' % graphType,
        'baseTypeName': '%s' % baseFieldType,
        'description': baseFieldType.description.strip(),
        'isNullable': not isinstance(graphType, graphql.GraphQLNonNull),
    }


def _DiscoverMethods(queryOrMutationType):
    methods = []
    for operationName, field in queryOrMutationType.fields.items():
        methods.append(
            {
                'operationName': operationName,
                'parameters': sorted(
                    [
                        {
                            'parameterName': argumentName,
                            'parameterType': _DiscoverType(argument.type)['typeName'],
                            'parameterDescription': argument.description,
                            'parameterNullable': not isinstance(argument.type, graphql.GraphQLNonNull),
                            'parameterDefaultValue': argument.default_value if argument.default_value != graphql.Undefined else None,
                        }
                        for argumentName, argument in field.args.items()
                    ],
                    key=lambda x: (x['parameterNullable'], x['parameterName']),
                ),
                'description': field.description,
                'deprecationReason': field.deprecation_reason,
                'returnType': _DiscoverType(field.type),
            },
        )
    return methods


def _PrintMethod(queryOrMutationOrSubscription, operationName, parameters, description, deprecationReason, returnType):
    if queryOrMutationOrSubscription == 'query' and operationName.startswith('List'):
        print('    @UseLazyGraphQuery')

    builtinParameterNamesRequired = ()
    builtinParameterNamesOptional = ()
    if queryOrMutationOrSubscription in ('query', 'mutation'):
        builtinParameterNamesOptional = ('fields', 'timeout')
    elif queryOrMutationOrSubscription == 'subscription':
        builtinParameterNamesRequired = ('callbackFunction',)
        builtinParameterNamesOptional = ('fields',)
    builtinParameterNames = builtinParameterNamesRequired + builtinParameterNamesOptional

    # build parameter list with type annotations
    parameterList = []

    # add builtin required parameters
    for parameterName in builtinParameterNamesRequired:
        if parameterName == 'callbackFunction':
            parameterList.append('callbackFunction: Callable[[Optional[Any], Optional[Dict[str, Any]]], None]')
        else:
            parameterList.append(parameterName)

    # add operation parameters (required and optional)
    for parameter in parameters:
        if parameter['parameterName'] in builtinParameterNames:
            continue

        parameterType = _FormatTypeForAnnotation(parameter['parameterType'], parameter['parameterNullable'])

        if parameter['parameterDefaultValue'] is not None:
            # parameter has default value
            if parameter['parameterType'] == 'String':
                parameterList.append("%s: %s = '%s'" % (parameter['parameterName'], parameterType, str(parameter['parameterDefaultValue'])))
            else:
                parameterList.append('%s: %s = %s' % (parameter['parameterName'], parameterType, str(parameter['parameterDefaultValue'])))
        elif parameter['parameterNullable'] is True:
            # parameter is optional
            parameterList.append('%s: %s = None' % (parameter['parameterName'], parameterType))
        else:
            # parameter is required
            parameterList.append('%s: %s' % (parameter['parameterName'], parameterType))

    # add builtin optional parameters
    for parameterName in builtinParameterNamesOptional:
        if parameterName == 'fields':
            parameterList.append('fields: Optional[Union[List[str], Dict[str, Any]]] = None')
        elif parameterName == 'timeout':
            parameterList.append('timeout: Optional[float] = None')
        else:
            parameterList.append('%s: Optional[Any] = None' % parameterName)

    # determine return type
    if queryOrMutationOrSubscription == 'subscription':
        finalReturnType = 'Subscription'
    else:
        finalReturnType = _FormatTypeForAnnotation(returnType['typeName'], returnType['isNullable'])

    # print method signature with type annotations
    if parameterList:
        print('    def %s(' % operationName)
        print('        self,')
        for param in parameterList[:-1]:
            print('        %s,' % param)
        print('        %s,' % parameterList[-1])  # last parameter gets trailing comma
        print('    ) -> %s:' % finalReturnType)
    else:
        print('    def %s(self) -> %s:' % (operationName, finalReturnType))

    if description:
        print('        """%s' % _CleanDocstring(description))
    else:
        print('        """')
    print('')
    if deprecationReason:
        print('        Deprecated:')
        print('            %s' % (deprecationReason))
        print('')
    print('        Args:')
    if queryOrMutationOrSubscription == 'subscription':
        print('            callbackFunction (Callable[[Optional[ControllerGraphClientException], Optional[dict]], None]):')
        print('                A function with signature that will be called when the subscription is triggered:')
        print('                    def CallbackFunction(error: Optional[ControllerGraphClientException], response: Optional[dict]) -> None')
        print('                - error: Contains an error message (or `None` if no error occurred).')
        print('                - response: Contains the returned payload (or `None` if an error occurred).')
    for parameter in parameters:
        if parameter['parameterName'] in builtinParameterNames:
            continue
        isOptionalString = ', optional' if parameter['parameterNullable'] else ''
        print('            %s (%s%s):' % (parameter['parameterName'], _FormatTypeForDocstring(parameter['parameterType']), isOptionalString), end='')
        if parameter['parameterDescription']:
            print(' %s' % _IndentNewlines(_CleanDocstring(parameter['parameterDescription'])))
        else:
            print('')
    print('            fields (list or dict, optional): Specifies a subset of fields to return.')
    if queryOrMutationOrSubscription in ('query', 'mutation'):
        print('            timeout (float, optional): Number of seconds to wait for response.')
    print('')
    print('        Returns:')
    print('            %s:' % (_FormatTypeForDocstring(returnType['typeName'])), end='')
    if returnType['description']:
        print(' %s' % _IndentNewlines(_CleanDocstring(returnType['description'])))
    else:
        print('')
    print('        """')

    if deprecationReason:
        print('        warnings.warn(\'"%s" is deprecated. %s\', DeprecationWarning, stacklevel=2)' % (operationName, deprecationReason))

    # check if there are any parameters to add
    if any(param['parameterName'] not in builtinParameterNames for param in parameters):
        print('        parameterNameTypeValues: List[Tuple[str, str, Any]] = [')
        for parameter in parameters:
            if parameter['parameterName'] in builtinParameterNames:
                continue
            print("            ('%s', '%s', %s)," % (parameter['parameterName'], parameter['parameterType'], parameter['parameterName']))
        print('        ]')
    else:
        print('        parameterNameTypeValues: List[Tuple[str, str, Any]] = []')

    if queryOrMutationOrSubscription in ('query', 'mutation'):
        print(
            "        return self._CallSimpleGraphAPI('%s', operationName='%s', parameterNameTypeValues=parameterNameTypeValues, returnType='%s', fields=fields, timeout=timeout)" % (queryOrMutationOrSubscription, operationName, returnType['baseTypeName']),
        )
    elif queryOrMutationOrSubscription == 'subscription':
        print(
            "        return self._CallSubscribeGraphAPI(operationName='%s', parameterNameTypeValues=parameterNameTypeValues, returnType='%s', callbackFunction=callbackFunction, fields=fields)" % (operationName, returnType['baseTypeName']),
        )


def _PrintClient(serverVersion, queryMethods, mutationMethods, subscriptionMethods):
    print('# -*- coding: utf-8 -*-')
    print('#')
    print('# DO NOT EDIT, THIS FILE WAS AUTO-GENERATED')
    print('# GENERATED BY: %s' % os.path.basename(__file__))
    print('# GENERATED AGAINST: %s' % serverVersion)
    print('#')
    print('')
    print('import warnings')
    print('from typing import Any, Dict, List, Optional, Union, Callable, Tuple')
    print('')
    print('from .webstackgraphclientutils import GraphClientBase')
    print('from .webstackgraphclientutils import UseLazyGraphQuery')
    print('from .controllerwebclientraw import Subscription')
    print('')
    print('')
    print('class GraphQueries:')
    for queryMethod in queryMethods:
        _PrintMethod('query', **queryMethod)
        print('')
    print('')
    print('class GraphMutations:')
    for mutationMethod in mutationMethods:
        _PrintMethod('mutation', **mutationMethod)
        print('')
    print('')
    print('class GraphSubscriptions:')
    print('    def Unsubscribe(self, subscription: Subscription) -> None:')
    print('        """')
    print('        Cancel an actively running subscription instance.')
    print('')
    print('        Args:')
    print('            subscription (Subscription): The subscription instance to cancel.')
    print('        """')
    print('        self._webclient.UnsubscribeGraphAPI(subscription)')
    print('')
    for subscriptionMethod in subscriptionMethods:
        _PrintMethod('subscription', **subscriptionMethod)
        print('')
    print('')
    print('class GraphQueriesClient(GraphClientBase, GraphQueries):')
    print('    pass')
    print('')
    print('')
    print('class GraphMutationsClient(GraphClientBase, GraphMutations):')
    print('    pass')
    print('')
    print('')
    print('class GraphSubscriptionsClient(GraphClientBase, GraphSubscriptions):')
    print('    pass')
    print('')
    print('')
    print('class GraphClient(GraphClientBase, GraphQueries, GraphMutations, GraphSubscriptions):')
    print('    @property')
    print('    def queries(self) -> GraphQueriesClient:')
    print('        return GraphQueriesClient(self._webclient)')
    print('')
    print('    @property')
    print('    def mutations(self) -> GraphMutationsClient:')
    print('        return GraphMutationsClient(self._webclient)')
    print('')
    print('    @property')
    print('    def subscriptions(self) -> GraphSubscriptionsClient:')
    print('        return GraphSubscriptionsClient(self._webclient)')
    print('')
    print('')
    print('#')
    print('# DO NOT EDIT, THIS FILE WAS AUTO-GENERATED, SEE HEADER')
    print('#')


def _Main():
    options = _ParseArguments()
    _ConfigureLogging(options.loglevel)

    serverVersion, schema = _FetchServerVersionAndSchema(options.url, options.username, options.password)
    queryMethods = _DiscoverMethods(schema.query_type)
    mutationMethods = _DiscoverMethods(schema.mutation_type)
    subscriptionMethods = _DiscoverMethods(schema.subscription_type)

    _PrintClient(serverVersion, queryMethods, mutationMethods, subscriptionMethods)


if __name__ == '__main__':
    _Main()

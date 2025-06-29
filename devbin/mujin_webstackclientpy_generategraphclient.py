#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import graphql # require graphql-core pip package when generating python code

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

def _IndentNewlines(string, indent="    "*5):
    """Indent new lines in a string. Used for multi-line descriptions.
    """
    return string.replace("\n", "\n"+indent)

def _FormatTypeForDocstring(typeName):
    """Removes the exclamation mark and converts basic Golang types to Python types.
    """
    _typeName = str(typeName).replace("!", "")
    if _typeName == 'String':
        return 'str'
    elif _typeName == 'Int':
        return 'int'
    elif _typeName == 'Boolean':
        return 'bool'
    else:
        return _typeName

def _DiscoverType(graphType):
    baseFieldType = _DereferenceType(graphType)
    baseFieldTypeName = '%s' % baseFieldType
    return {
        'typeName': '%s' % graphType,
        'baseTypeName': '%s' % baseFieldType,
        'description': baseFieldType.description.strip(),
    }

def _DiscoverMethods(queryOrMutationType):
    methods = []
    for operationName, field in queryOrMutationType.fields.items():
        methods.append({
            'operationName': operationName,
            'parameters': sorted([
                {
                    'parameterName': argumentName,
                    'parameterType': _DiscoverType(argument.type)['typeName'],
                    'parameterDescription': argument.description,
                    'parameterNullable': not isinstance(argument.type, graphql.GraphQLNonNull),
                    'parameterDefaultValue': argument.default_value if argument.default_value != graphql.Undefined else None,
                }
                for argumentName, argument in field.args.items()
            ], key=lambda x: (x['parameterNullable'], x['parameterName'])),
            'description': field.description,
            'deprecationReason': field.deprecation_reason,
            'returnType': _DiscoverType(field.type),
        })
    return methods

def _PrintMethod(queryOrMutationOrSubscription, operationName, parameters, description, deprecationReason, returnType):
    if queryOrMutationOrSubscription == 'query' and operationName.startswith("List"):
        print('    @UseLazyGraphQuery')

    builtinParameterNamesRequired = ()
    builtinParameterNamesOptional = ()
    if queryOrMutationOrSubscription in ('query', 'mutation'):
        builtinParameterNamesOptional = ('fields', 'timeout')
    elif queryOrMutationOrSubscription == 'subscription':
        builtinParameterNamesRequired = ('callbackFunction',)
        builtinParameterNamesOptional = ('fields',)
    builtinParameterNames = builtinParameterNamesRequired + builtinParameterNamesOptional
    operationParametersRequired = []
    operationParametersOptional = []
    for parameter in parameters:
        if parameter['parameterName'] in builtinParameterNames:
            continue
        if parameter['parameterDefaultValue'] is not None:
            operationParametersOptional.append('%s=%s' % (parameter['parameterName'], str(parameter['parameterDefaultValue'])))
            continue
        if parameter['parameterNullable'] is True:
            operationParametersOptional.append('%s=None' % parameter['parameterName'])
            continue
        operationParametersRequired.append('%s' % parameter['parameterName'])

    fullParameterList = list(builtinParameterNamesRequired) + operationParametersRequired + operationParametersOptional + ['%s=None' % name for name in builtinParameterNamesOptional]
    print('    def %s(self, %s):' % (operationName, ', '.join(fullParameterList)))

    if description:
        print('        """%s' % description)
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
        isOptionalString = ", optional" if parameter['parameterNullable'] else ""
        print('            %s (%s%s): %s' % (parameter['parameterName'], _FormatTypeForDocstring(parameter['parameterType']), isOptionalString, _IndentNewlines(parameter['parameterDescription'])))
    print('            fields (list or dict, optional): Specifies a subset of fields to return.')
    if queryOrMutationOrSubscription in ('query', 'mutation'):
        print('            timeout (float, optional): Number of seconds to wait for response.')
    print('')
    print('        Returns:')
    print('            %s: %s' % (_FormatTypeForDocstring(returnType['typeName']), _IndentNewlines(returnType['description'])))
    print('        """')

    if deprecationReason:
        print('        warnings.warn(\'"%s" is deprecated. %s\', DeprecationWarning, stacklevel=2)' % (operationName, deprecationReason))

    print('        parameterNameTypeValues = [')
    for parameter in parameters:
        if parameter['parameterName'] in builtinParameterNames:
            continue
        print('            (\'%s\', \'%s\', %s),' % (parameter['parameterName'], parameter['parameterType'], parameter['parameterName']))
    print('        ]')

    if queryOrMutationOrSubscription in ('query', 'mutation'):
        print('        return self._CallSimpleGraphAPI(\'%s\', operationName=\'%s\', parameterNameTypeValues=parameterNameTypeValues, returnType=\'%s\', fields=fields, timeout=timeout)' % (queryOrMutationOrSubscription, operationName, returnType['baseTypeName']))
    elif queryOrMutationOrSubscription == 'subscription':
        print('        return self._CallSubscribeGraphAPI(operationName=\'%s\', parameterNameTypeValues=parameterNameTypeValues, returnType=\'%s\', callbackFunction=callbackFunction, fields=fields)' % (operationName, returnType['baseTypeName']))

def _PrintClient(serverVersion, queryMethods, mutationMethods, subscriptionMethods):
    print('# -*- coding: utf-8 -*-')
    print('#')
    print('# DO NOT EDIT, THIS FILE WAS AUTO-GENERATED')
    print('# GENERATED BY: %s' % os.path.basename(__file__))
    print('# GENERATED AGAINST: %s' % serverVersion)
    print('#')
    print('')
    print('import warnings')
    print('')
    print('from .webstackgraphclientutils import GraphClientBase')
    print('from .webstackgraphclientutils import UseLazyGraphQuery')
    print('from .controllerwebclientraw import Subscription')
    print('')
    print('class GraphQueries:')
    print('')
    for queryMethod in queryMethods:
        _PrintMethod('query', **queryMethod)
        print('')
    print('')
    print('class GraphMutations:')
    print('')
    for mutationMethod in mutationMethods:
        _PrintMethod('mutation', **mutationMethod)
        print('')
    print('')
    print('class GraphSubscriptions:')
    print('')
    print('    def Unsubscribe(self, subscription: Subscription):')
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
    print('class GraphMutationsClient(GraphClientBase, GraphMutations):')
    print('    pass')
    print('')
    print('class GraphSubscriptionsClient(GraphClientBase, GraphSubscriptions):')
    print('    pass')
    print('')
    print('class GraphClient(GraphClientBase, GraphQueries, GraphMutations, GraphSubscriptions):')
    print('')
    print('    @property')
    print('    def queries(self):')
    print('        return GraphQueriesClient(self._webclient)')
    print('')
    print('    @property')
    print('    def mutations(self):')
    print('        return GraphMutationsClient(self._webclient)')
    print('')
    print('    @property')
    print('    def subscriptions(self):')
    print('        return GraphSubscriptionsClient(self._webclient)')
    print('')
    print('#')
    print('# DO NOT EDIT, THIS FILE WAS AUTO-GENERATED, SEE HEADER')
    print('#')
    print('')


def _Main():
    options = _ParseArguments()
    _ConfigureLogging(options.loglevel)

    serverVersion, schema = _FetchServerVersionAndSchema(options.url, options.username, options.password)
    queryMethods = _DiscoverMethods(schema.query_type)
    mutationMethods = _DiscoverMethods(schema.mutation_type)
    subscriptionMethods = _DiscoverMethods(schema.subscription_type)

    _PrintClient(serverVersion, queryMethods, mutationMethods, subscriptionMethods)


if __name__ == "__main__":
    _Main()

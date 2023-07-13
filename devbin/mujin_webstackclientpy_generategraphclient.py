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
                }
                for argumentName, argument in field.args.items()
            ], key=lambda x: (x['parameterNullable'], x['parameterName'])),
            'description': field.description,
            'returnType': _DiscoverType(field.type),
        })
    return methods    

def _PrintMethod(queryOrMutation, operationName, parameters, description, returnType):
    if queryOrMutation == 'query' and operationName.startswith("List"):
        print('    @BreakLargeGraphQuery')
    builtinParameterNames = ('fields', 'timeout')
    print('    def %s(self, %s):' % (operationName, ', '.join([
        '%s=None' % parameter['parameterName'] if parameter['parameterNullable'] else parameter['parameterName']
        for parameter in parameters
        if parameter['parameterName'] not in builtinParameterNames
    ] + ['fields=None', 'timeout=None'])))
    if description:
        print('        """%s' % description)
        print('')
        print('        Args:')
        for parameter in parameters:
            if parameter['parameterName'] in builtinParameterNames:
                continue
            isOptionalString = ", optional" if parameter['parameterNullable'] else ""
            print('            %s (%s%s): %s' % (parameter['parameterName'], _FormatTypeForDocstring(parameter['parameterType']), isOptionalString, _IndentNewlines(parameter['parameterDescription'])))
        print('            fields (list or dict, optional): Specifies a subset of fields to return.')
        print('            timeout (float, optional): Number of seconds to wait for response.')
        print('')
        print('        Returns:')
        print('            %s: %s' % (_FormatTypeForDocstring(returnType['typeName']), _IndentNewlines(returnType['description'])))
        print('        """')
    print('        parameterNameTypeValues = [')
    for parameter in parameters:
        if parameter['parameterName'] in builtinParameterNames:
            continue
        print('            (\'%s\', \'%s\', %s),' % (parameter['parameterName'], parameter['parameterType'], parameter['parameterName']))
    print('        ]')
    print('        return self._CallSimpleGraphAPI(\'%s\', operationName=\'%s\', parameterNameTypeValues=parameterNameTypeValues, returnType=\'%s\', fields=fields, timeout=timeout)' % (queryOrMutation, operationName, returnType['baseTypeName']))

    if queryOrMutation == 'query' and operationName.startswith("List"):
        iteratorOperationName = operationName.replace("List", "Iterate", 1)
        print('')
        builtinParameterNames = ('fields', 'timeout')
        print('    def %s(self, %s):' % (iteratorOperationName, ', '.join([
            '%s=None' % parameter['parameterName'] if parameter['parameterNullable'] else parameter['parameterName']
            for parameter in parameters
            if parameter['parameterName'] not in builtinParameterNames
        ] + ['fields=None', 'timeout=None'])))
        if description:
            description = description.replace("List", "Iterate through", 1)
            print('        """%s' % description)
            print('')
            print('        Args:')
            for parameter in parameters:
                if parameter['parameterName'] in builtinParameterNames:
                    continue
                isOptionalString = ", optional" if parameter['parameterNullable'] else ""
                print('            %s (%s%s): %s' % (parameter['parameterName'], _FormatTypeForDocstring(parameter['parameterType']), isOptionalString, _IndentNewlines(parameter['parameterDescription'])))
            print('            fields (list or dict, optional): Specifies a subset of fields to return.')
            print('            timeout (float, optional): Number of seconds to wait for response.')
            print('')
            print('        Returns:')
            returnTypeName = _FormatTypeForDocstring(returnType['typeName'])
            returnTypeName = returnTypeName.replace('List', '')
            returnTypeName = returnTypeName.replace('ReturnValue', 'Iterator')
            print('            %s' % returnTypeName)
            print('        """')
        print('        args = [')
        for parameter in parameters:
            if parameter['parameterName'] in builtinParameterNames:
                continue
            if parameter['parameterNullable']:
                continue
            print('            %s,' % parameter['parameterName'])
        print('        ]')
        print('        kwargs = {')
        for parameter in parameters:
            if parameter['parameterName'] in builtinParameterNames:
                continue
            if not parameter['parameterNullable']:
                continue
            print('            \'%s\': %s,' % (parameter['parameterName'], parameter['parameterName']))
        print('            \'fields\': fields,')
        print('            \'timeout\': timeout,')
        print('        }')
        print('        return GraphQueryIterator(self.%s, *args, **kwargs)' % (operationName))


def _PrintClient(serverVersion, queryMethods, mutationMethods):
    print('# -*- coding: utf-8 -*-')
    print('#')
    print('# DO NOT EDIT, THIS FILE WAS AUTO-GENERATED')
    print('# GENERATED BY: %s' % os.path.basename(__file__))
    print('# GENERATED AGAINST: %s' % serverVersion)
    print('#')
    print('')
    print('from .webstackgraphclientutils import GraphClientBase')
    print('from .webstackgraphclientutils import BreakLargeGraphQuery, GraphQueryIterator')
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
    print('class GraphClient(GraphClientBase, GraphQueries, GraphMutations):')
    print('    pass')
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

    _PrintClient(serverVersion, queryMethods, mutationMethods)


if __name__ == "__main__":
    _Main()

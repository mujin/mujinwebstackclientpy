# -*- coding: utf-8 -*-

import pytest
import requests_mock
import random
import sys
import copy
import graphql

from mujinwebstackclient.webstackclient import WebstackClient
from mujinwebstackclient.webstackclientutils import QueryIterator, GetMaximumQueryLimit
from mujinwebstackclient.webstackgraphclientutils import GraphQueryIterator

def _RegisterMockGetScenesAPI(mocker, totalCount):
    """Dynamically mocks the webstack GetScenes API

    mocker (requests_mock.Mocker): Mocker object
    totalCount (int): The total number of scenes to be supported
    """
    def _GetResponse(request, context):
        offset = int(request.qs['offset'][0])
        limit = int(request.qs['limit'][0])

        # validate the limit
        if limit > GetMaximumQueryLimit(0):
            context.status_code = 400
            return

        context.status_code = 200
        return {
            'objects': [{'id': str(index)} for index in range(offset, min(offset + limit, totalCount))],
            'meta': {
                'total_count': totalCount,
                'limit': limit,
                'offset': offset,
            },
        }
    
    mocker.register_uri('GET', requests_mock.ANY, additional_matcher=lambda request: request.url.startswith('http://controller/api/v1/scene/'), json=_GetResponse)

def _RegisterMockListEnvironmentsAPI(mocker, totalCount):
    """Dynamically mocks the webstack ListEnvironments GraphQL API

    mocker (requests_mock.Mocker): Mocker object
    totalCount (int): The total number of environments to be supported
    """
    def _GetResponse(request, context):
        jsonRequest = request.json()
        rawQuery = jsonRequest.get('query')
        variables = jsonRequest.get('variables')

        # parse the query
        query = graphql.parse(rawQuery).definitions[0]

        # handle different versions of the library
        if sys.version_info.major > 2:
            assert query.operation.value == 'query'
        else:
            assert query.operation == 'query'

        listEnvironmentsSelection = query.selection_set.selections[0]
        assert listEnvironmentsSelection.name.value == 'ListEnvironments'

        # loop over the selected options arguments
        offset, first = None, None
        for argument in listEnvironmentsSelection.arguments:
            if argument.name.value != 'options':
                continue

            # handle different versions of the library
            variableNodeType = None
            if sys.version_info.major > 2:
                variableNodeType = graphql.VariableNode
            else:
                variableNodeType = graphql.language.ast.Variable

            # handle variables
            if isinstance(argument.value, variableNodeType):
                variableName = argument.value.name.value
                assert variableName in variables, 'missing variable %s in query' % variableName
                options = variables.get(variableName)
                for name in options:
                    if name == 'first':
                        first = options[name]
                    if name == 'offset':
                        offset = options[name]
            # handle directly embedded values
            else:
                for field in argument.value.fields:
                    if field.name.value == 'first':
                        first = int(field.value.value)
                    if field.name.value == 'offset':
                        offset = int(field.value.value)

        # validate the limit
        if first > GetMaximumQueryLimit(0):
            context.status_code = 400
            return
        
        # construct the return value
        result = {}
        for selection in listEnvironmentsSelection.selection_set.selections:
            if selection.name.value == 'environments':
                result.setdefault('data', {})
                result['data'].setdefault('ListEnvironments', {})
                result['data']['ListEnvironments']['environments'] = []
                # populate the environments
                for index in range(offset, min(offset + first, totalCount)):
                    environment = {}
                    for subSelection in selection.selection_set.selections:
                        if subSelection.name.value == '__typename':
                            environment['__typename'] = 'Environment'
                        if subSelection.name.value == 'id':
                            environment['id'] = str(index)
                    result['data']['ListEnvironments']['environments'].append(environment)
                continue
            if selection.name.value == 'meta':
                result.setdefault('data', {})
                result['data'].setdefault('ListEnvironments', {})
                result['data']['ListEnvironments']['meta'] = {'totalCount': totalCount}
                continue
            if selection.name.value == '__typename':
                result.setdefault('data', {})
                result['data'].setdefault('ListEnvironments', {})
                result['data']['ListEnvironments']['__typename'] = 'ListEnvironmentsReturnValue'

        context.status_code = 200
        return result

    mocker.register_uri('POST', requests_mock.ANY, additional_matcher=lambda request: request.url.startswith('http://controller/api/v2/graphql'), json=_GetResponse)

@pytest.mark.parametrize('url, username, password', [
    ('http://controller', 'mujin', 'mujin'),
    ('http://controller:8080', 'mujin', 'mujin'),
    ('http://127.0.0.1', 'testuser', 'pass'),
    ('http://127.0.0.1:8080', 'testuser', 'pass'),
])
def test_PingAndLogin(url, username, password):
    with requests_mock.Mocker() as mock:
        mock.head('%s/u/%s/' % (url, username))
        webclient = WebstackClient(url, username, password)
        webclient.Ping()
        webclient.Login()
        assert webclient.IsLoggedIn()

def test_RestartController():
    with requests_mock.Mocker() as mock:
        mock.post('http://controller/restartserver/')
        WebstackClient('http://controller', 'mujin', 'mujin').RestartController()

def test_GetScenes():
    with requests_mock.Mocker() as mock:
        _RegisterMockGetScenesAPI(mock, 101)
        scenes = WebstackClient('http://controller', 'mujin', 'mujin').GetScenes(limit=100)
        assert len(scenes) == 100
        assert scenes.offset == 0
        assert scenes.limit == 100
        assert scenes.totalCount == 101

def test_QueryIteratorAndLazyQuery():
    totalCount = 1000
    webstackclient = WebstackClient('http://controller', 'mujin', 'mujin')

    # iterate through all scenes
    with requests_mock.Mocker() as mock:
        _RegisterMockGetScenesAPI(mock, totalCount)

        # test iterator
        count = 0
        for index, scene in enumerate(QueryIterator(webstackclient.GetScenes)):
            count += 1
            assert scene['id'] == str(index)
        assert count == totalCount

        # test lazy query
        scenes = webstackclient.GetScenes()
        assert len(scenes) == totalCount
        for index in range(totalCount):
            assert scenes[index]['id'] == str(index)

    # iterate through all scenes with offset and limit
    with requests_mock.Mocker() as mock:
        _RegisterMockGetScenesAPI(mock, totalCount)

        initialOffset = 5
        initialLimit = 555

        # test iterator
        count = 0
        for index, scene in enumerate(QueryIterator(webstackclient.GetScenes, offset=initialOffset, limit=initialLimit)):
            count += 1
            assert scene['id'] == str(index + initialOffset)
        assert count == initialLimit

        # test lazy query
        scenes = webstackclient.GetScenes(offset=initialOffset, limit=initialLimit)
        assert len(scenes) == initialLimit
        for index in range(initialLimit):
            assert scenes[index]['id'] == str(index + initialOffset)

def test_GraphQueryIteratorAndLazyGraphQuery():
    totalCount = 1000
    webstackclient = WebstackClient('http://controller', 'mujin', 'mujin')

    # iterate through all environments
    with requests_mock.Mocker() as mock:
        _RegisterMockListEnvironmentsAPI(mock, totalCount)

        # test iterator
        count = 0
        for index, environment in enumerate(GraphQueryIterator(webstackclient.graphApi.ListEnvironments, fields={'environments': {'id': None}})):
            count += 1
            assert environment['id'] == str(index)
        assert count == totalCount

        # test iterator without field selection
        assert len(list(GraphQueryIterator(webstackclient.graphApi.ListEnvironments, fields={}))) == 0
        assert len(list(GraphQueryIterator(webstackclient.graphApi.ListEnvironments, fields=None))) == 0

        # test lazy query
        queryResult = webstackclient.graphApi.ListEnvironments(fields={'environments': {'id': None}})
        assert 'meta' not in queryResult
        assert '__typename' not in queryResult
        assert 'environments' in queryResult
        environments = queryResult['environments']
        assert len(environments) == totalCount
        for index in range(totalCount):
            assert environments[index]['id'] == str(index)

    # iterate through all environments with offset and limit
    with requests_mock.Mocker() as mock:
        _RegisterMockListEnvironmentsAPI(mock, totalCount)

        initialOffset = 5
        initialLimit = 555

        # test iterator
        count = 0
        for index, environment in enumerate(GraphQueryIterator(webstackclient.graphApi.ListEnvironments, fields={'environments': {'id': None}}, options={'offset': initialOffset, 'first': initialLimit})):
            count += 1
            assert environment['id'] == str(index + initialOffset)
        assert count == initialLimit

        # test iterator without field selection
        assert len(list(GraphQueryIterator(webstackclient.graphApi.ListEnvironments, fields={}, options={'offset': initialOffset, 'first': initialLimit}))) == 0
        assert len(list(GraphQueryIterator(webstackclient.graphApi.ListEnvironments, fields=None, options={'offset': initialOffset, 'first': initialLimit}))) == 0

        # test lazy query
        queryResult = webstackclient.graphApi.ListEnvironments(fields={'environments': {'id': None}}, options={'offset': initialOffset, 'first': initialLimit})
        assert 'meta' not in queryResult
        assert '__typename' not in queryResult
        assert 'environments' in queryResult
        environments = queryResult['environments']
        assert len(environments) == initialLimit
        for index in range(initialLimit):
            assert environments[index]['id'] == str(index + initialOffset)

    with requests_mock.Mocker() as mock:
        _RegisterMockListEnvironmentsAPI(mock, totalCount)

        # query with no fields
        queryResult = webstackclient.graphApi.ListEnvironments()
        assert queryResult == {
            '__typename': 'ListEnvironmentsReturnValue'
        }
 
        # query with empty fields
        queryResult = webstackclient.graphApi.ListEnvironments(fields={})
        assert queryResult == {
            '__typename': 'ListEnvironmentsReturnValue'
        }

        # query __typename
        queryResult = webstackclient.graphApi.ListEnvironments(fields={'__typename': None})
        assert queryResult == {
            '__typename': 'ListEnvironmentsReturnValue'
        }

        # query __typename in subselection
        queryResult = webstackclient.graphApi.ListEnvironments(fields={'environments':{'__typename': None}}, options={'first': 1})
        assert queryResult == {
            'environments': [
                {'__typename': 'Environment'},
            ]
        }
        queryResult = webstackclient.graphApi.ListEnvironments(fields={'environments':{'__typename': None}}, options={'first': 2})
        assert queryResult == {
            'environments': [
                {'__typename': 'Environment'},
                {'__typename': 'Environment'},
            ]
        }

        # with offset
        queryResult = webstackclient.graphApi.ListEnvironments(fields={'environments':{'id': None, '__typename': None}}, options={'first': 1, 'offset': totalCount*2})
        assert queryResult == {
            'environments': []
        }
        queryResult = webstackclient.graphApi.ListEnvironments(fields={'environments':{'id': None, '__typename': None}}, options={'first': 2, 'offset': 2})
        assert queryResult == {
            'environments': [
                {'id': '2', '__typename': 'Environment'},
                {'id': '3','__typename': 'Environment'},
            ]
        }

        # without __typename
        queryResult = webstackclient.graphApi.ListEnvironments(fields={'environments':{'id': None}}, options={'first': 1, 'offset': 0})
        assert queryResult == {
            'environments': [
                {'id': '0'}
            ]
        }
        queryResult = webstackclient.graphApi.ListEnvironments(fields={'environments':{'id': None}}, options={'first': 2, 'offset': 2})
        assert queryResult == {
            'environments': [
                {'id': '2'},
                {'id': '3'},
            ]
        }

        # query meta
        queryResult = webstackclient.graphApi.ListEnvironments(fields={'meta': {'totalCount': None}})
        assert queryResult == {
            'meta': {
                'totalCount': totalCount
            }
        }

def test_LazyQueryStandardListOperations():
    """test standard list operations
    """
    totalCount = 1000
    webstackclient = WebstackClient('http://controller', 'mujin', 'mujin')

    # iterate through all scenes
    with requests_mock.Mocker() as mock:
        _RegisterMockGetScenesAPI(mock, totalCount)

        testItem = {'id': 'testItem'}
        index = random.randint(0, totalCount - 1)
        allScenes = [{'id': str(item)} for item in range(0, totalCount)]

        # test negative index
        scenes = webstackclient.GetScenes()
        assert scenes[-100] == allScenes[-100]
        hasIndexError = False
        try:
            scenes[-totalCount-1]
        except IndexError:
            hasIndexError = True
        assert hasIndexError

        # test setter
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        scenes[index] = testItem
        expectedScenes[index] = testItem
        assert scenes == expectedScenes

        # test deletion
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        del scenes[index]
        del expectedScenes[index]
        assert scenes == expectedScenes

        # test append
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        scenes.append(testItem)
        expectedScenes.append(testItem)
        assert scenes == expectedScenes

        # test extend
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        scenes.extend([testItem])
        expectedScenes.extend([testItem])
        assert scenes == expectedScenes

        # test insert
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        scenes.insert(index, testItem)
        expectedScenes.insert(index, testItem)
        assert scenes == expectedScenes

        # test index
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        assert scenes.index(expectedScenes[index]) == expectedScenes.index(expectedScenes[index])

        # test pop
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        scenes.pop()
        expectedScenes.pop()
        assert scenes == expectedScenes

        # test count
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        assert scenes.count(expectedScenes[index]) == expectedScenes.count(expectedScenes[index])

        # test contain
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        assert (expectedScenes[index] in scenes) == (expectedScenes[index] in expectedScenes)

        # test remove
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        scenes.remove(expectedScenes[index])
        expectedScenes.remove(expectedScenes[index])
        assert scenes == expectedScenes

        # test reverse
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        scenes.reverse()
        expectedScenes.reverse()
        assert scenes == expectedScenes
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        for scene, expectedScene in zip(reversed(scenes), reversed(expectedScenes)):
            assert scene == expectedScene

        # test sort
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        if sys.version_info.major == 2: # python 2
            scenes.sort(reverse=True)
            expectedScenes.sort(reverse=True)
            assert scenes == expectedScenes

        # test addition
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        assert scenes + [testItem] == expectedScenes + [testItem]
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        scenes += [testItem]
        expectedScenes += [testItem]
        assert scenes == expectedScenes

        # test multiplication
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        assert scenes * 2 == expectedScenes * 2
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        assert 2 * scenes == 2 * expectedScenes
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        scenes *= 2
        expectedScenes *= 2
        assert scenes == expectedScenes

        # test slice getter
        start = 100
        end = 105
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        assert scenes[start:end] == expectedScenes[start:end]

        # test slice setter
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        scenes[start:end] = [testItem]
        expectedScenes[start:end] = [testItem]
        assert scenes == expectedScenes

        # test slice deletion
        scenes = webstackclient.GetScenes()
        expectedScenes = copy.copy(allScenes)
        del scenes[start:end]
        del expectedScenes[start:end]
        assert scenes == expectedScenes

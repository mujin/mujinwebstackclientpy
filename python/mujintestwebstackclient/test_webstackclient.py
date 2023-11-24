# -*- coding: utf-8 -*-

import pytest
import requests_mock
import json
import requests
import random
import sys

import mujinwebstackclient.webstackclientutils
from mujinwebstackclient.webstackclient import WebstackClient
from mujinwebstackclient.webstackclientutils import QueryIterator
from mujinwebstackclient.webstackgraphclientutils import GraphQueryIterator

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
        mock.get('http://controller/api/v1/scene/?format=json&limit=100&offset=0', json={
            'objects': [{} for i in range(101)],
            'meta': {
                'total_count': 101,
                'limit': 100,
                'offset': 0,
            },
        })
        scenes = WebstackClient('http://controller', 'mujin', 'mujin').GetScenes(limit=100)
        assert len(scenes) == 100
        assert scenes.offset == 0
        assert scenes.limit == 100
        assert scenes.totalCount == 101

def test_QueryIteratorAndLazyQuery():
    limit = mujinwebstackclient.webstackclientutils.MAXIMUM_QUERY_LIMIT
    totalCount = 1000
    webstackclient = WebstackClient('http://controller', 'mujin', 'mujin')

    # iterate through all scenes
    with requests_mock.Mocker() as mock:
        for offset in range(0, totalCount + 1, limit):
            queryUrl = 'http://controller/api/v1/scene/?format=json&limit={limit:d}&offset={offset:d}'.format(limit=limit, offset=offset)
            mock.get(queryUrl, json={
                'objects': [{'id': str(i)} for i in range(offset, min(offset + limit, totalCount))],
                'meta': {
                    'total_count': totalCount,
                    'limit': limit,
                    'offset': offset,
                },
            })

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
        initialOffset = 5
        initialLimit = 555
        for offset in range(initialOffset, initialOffset + initialLimit, limit):
            queryUrl = 'http://controller/api/v1/scene/?format=json&limit={limit:d}&offset={offset:d}'.format(limit=limit, offset=offset)
            mock.get(queryUrl, json={
                'objects': [{'id': str(i)} for i in range(offset, offset + limit)],
                'meta': {
                    'total_count': totalCount,
                    'limit': limit,
                    'offset': offset,
                },
            })

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
    limit = mujinwebstackclient.webstackclientutils.MAXIMUM_QUERY_LIMIT
    totalCount = 1000
    webstackclient = WebstackClient('http://controller', 'mujin', 'mujin')

    adapter = requests_mock.Adapter()

    def matcher(request):
        if request.path != "/api/v2/graphql":
            return None

        data = request.json()
        query = data.get('query')
        variables = data.get('variables')
        options = variables.get('options')
        offset = options.get('offset')
        first = options.get('first')
        
        if not query.startswith('query ListEnvironments'):
            return None
        if first != limit:
            return None
        if offset > totalCount:
            return None
        
        environments = [{'id': str(i)} for i in range(offset, min(offset + limit, totalCount))]
        response = requests.Response()
        response._content = json.dumps({
            'data': {
                'ListEnvironments': {
                    'meta': {'totalCount': totalCount},
                    'environments': environments,
                }
            }
        }).encode()

        response.status_code = 200
        return response

    adapter.add_matcher(matcher)

    # iterate through all environments
    with requests_mock.Mocker(adapter=adapter):
        # test iterator
        count = 0
        for index, environment in enumerate(GraphQueryIterator(webstackclient.graphApi.ListEnvironments, fields={'environments': {'id': None}})):
            count += 1
            assert environment['id'] == str(index)
        assert count == totalCount

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
    with requests_mock.Mocker(adapter=adapter):
        initialOffset = 5
        initialLimit = 555

        # test iterator
        count = 0
        for index, environment in enumerate(GraphQueryIterator(webstackclient.graphApi.ListEnvironments, fields={'environments': {'id': None}}, options={'offset': initialOffset, 'first': initialLimit})):
            count += 1
            assert environment['id'] == str(index + initialOffset)
        assert count == initialLimit

        # test lazy query
        queryResult = webstackclient.graphApi.ListEnvironments(fields={'environments': {'id': None}}, options={'offset': initialOffset, 'first': initialLimit})
        assert 'meta' not in queryResult
        assert '__typename' not in queryResult
        assert 'environments' in queryResult
        environments = queryResult['environments']
        assert len(environments) == initialLimit
        for index in range(initialLimit):
            assert environments[index]['id'] == str(index + initialOffset)

    adapter = requests_mock.Adapter()

    def matcher(request):
        if request.path != "/api/v2/graphql":
            return None

        query = request.json().get('query')
        expectedQueries = [
            'ListEnvironments(options: $options, resolveReferences: $resolveReferences, units: $units) { __typename }',
            'ListEnvironments(options: $options, resolveReferences: $resolveReferences, units: $units) {__typename, meta {totalCount}}',
            'ListEnvironments(options: $options, resolveReferences: $resolveReferences, units: $units) {meta {totalCount}, __typename}',
            'ListEnvironments(options: $options, resolveReferences: $resolveReferences, units: $units) {meta {totalCount}}',
        ]
        if all([expectedQuery not in query for expectedQuery in expectedQueries]):
            return None

        queryResult = {}
        if 'meta' in query:
            queryResult['meta'] = {'totalCount': totalCount}
        if '__typename' in query:
            queryResult['__typename'] = 'ListEnvironmentsReturnValue'

        response = requests.Response()
        response._content = json.dumps({'data': {'ListEnvironments': queryResult}}).encode()
        response.status_code = 200
        return response

    adapter.add_matcher(matcher)

    with requests_mock.Mocker(adapter=adapter):
        # query with no fields
        queryResult = webstackclient.graphApi.ListEnvironments()
        assert 'meta' not in queryResult
        assert '__typename' in queryResult
        assert 'environments' not in queryResult
        assert queryResult['__typename'] == 'ListEnvironmentsReturnValue'

        # query with empty fields
        queryResult = webstackclient.graphApi.ListEnvironments(fields={})
        assert 'meta' not in queryResult
        assert '__typename' in queryResult
        assert 'environments' not in queryResult
        assert queryResult['__typename'] == 'ListEnvironmentsReturnValue'

        # query __typename
        queryResult = webstackclient.graphApi.ListEnvironments(fields={'__typename': None})
        assert 'meta' not in queryResult
        assert '__typename' in queryResult
        assert 'environments' not in queryResult
        assert queryResult['__typename'] == 'ListEnvironmentsReturnValue'

        # query meta
        queryResult = webstackclient.graphApi.ListEnvironments(fields={'meta': {'totalCount': None}})
        assert 'meta' in queryResult
        assert '__typename' not in queryResult
        assert 'environments' not in queryResult
        assert queryResult['meta'].get('totalCount') == totalCount

def test_LazyQueryStandardListOperations():
    """test standard list operations
    """
    limit = mujinwebstackclient.webstackclientutils.MAXIMUM_QUERY_LIMIT
    totalCount = 1000
    webstackclient = WebstackClient('http://controller', 'mujin', 'mujin')

    # iterate through all scenes
    with requests_mock.Mocker() as mock:
        for offset in range(0, totalCount + 1, limit):
            queryUrl = 'http://controller/api/v1/scene/?format=json&limit={limit:d}&offset={offset:d}'.format(limit=limit, offset=offset)
            mock.get(queryUrl, json={
                'objects': [{'id': str(i)} for i in range(offset, min(offset + limit, totalCount))],
                'meta': {
                    'total_count': totalCount,
                    'limit': limit,
                    'offset': offset,
                },
            })

        testItem = {'id': 'testItem'}

        # test setter
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        index = random.randint(0, len(expectedScenes) - 1)
        scenes[index] = testItem
        expectedScenes[index] = testItem
        assert scenes == expectedScenes

        # test deletion
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        index = random.randint(0, len(expectedScenes) - 1)
        del scenes[index]
        del expectedScenes[index]
        assert scenes == expectedScenes

        # test append
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        scenes.append(testItem)
        expectedScenes.append(testItem)
        assert scenes == expectedScenes

        # test extend
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        scenes.extend([testItem])
        expectedScenes.extend([testItem])
        assert scenes == expectedScenes

        # test insert
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        index = random.randint(0, len(expectedScenes) - 1)
        scenes.insert(index, testItem)
        expectedScenes.insert(index, testItem)
        assert scenes == expectedScenes

        # test index
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        index = random.randint(0, len(expectedScenes) - 1)
        assert scenes.index(expectedScenes[index]) == expectedScenes.index(expectedScenes[index])

        # test pop
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        scenes.pop()
        expectedScenes.pop()
        assert scenes == expectedScenes

        # test count
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        index = random.randint(0, len(expectedScenes) - 1)
        assert scenes.count(expectedScenes[index]) == expectedScenes.count(expectedScenes[index])

        # test count
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        index = random.randint(0, len(expectedScenes) - 1)
        assert (expectedScenes[index] in scenes) == (expectedScenes[index] in expectedScenes)

        # test remove
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        index = random.randint(0, len(expectedScenes) - 1)
        scenes.remove(expectedScenes[index])
        expectedScenes.remove(expectedScenes[index])
        assert scenes == expectedScenes

        # test reverse
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        scenes.reverse()
        expectedScenes.reverse()
        assert scenes == expectedScenes
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        for scene, expectedScene in zip(reversed(scenes), reversed(expectedScenes)):
            assert scene == expectedScene

        # test sort
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        if sys.version_info.major == 2:
            # python 2
            scenes.sort(reverse=True)
            expectedScenes.sort(reverse=True)
            assert scenes == expectedScenes

        # test addition
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        assert scenes + [testItem] == expectedScenes + [testItem]
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        scenes += [testItem]
        expectedScenes += [testItem]
        assert scenes == expectedScenes

        # test multiplication
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        assert scenes * 2 == expectedScenes * 2
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        assert 2 * scenes == 2 * expectedScenes
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        scenes *= 2
        expectedScenes *= 2
        assert scenes == expectedScenes

        # test slice getter
        start = 100
        end = 105
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        assert scenes[start:end] == expectedScenes[start:end]

        # test slice setter
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        scenes[start:end] = [testItem]
        expectedScenes[start:end] = [testItem]
        assert scenes == expectedScenes

        # test slice deletion
        scenes = webstackclient.GetScenes()
        expectedScenes = [{'id': str(i)} for i in range(0, totalCount)]
        del scenes[start:end]
        del expectedScenes[start:end]
        assert scenes == expectedScenes

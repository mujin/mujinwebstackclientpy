# -*- coding: utf-8 -*-

import pytest
import requests_mock
import json
import requests

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
        for offset in range(0, totalCount, limit):
            queryUrl = 'http://controller/api/v1/scene/?format=json&limit={limit:d}&offset={offset:d}'.format(limit=limit, offset=offset)
            mock.get(queryUrl, json={
                'objects': [{'id': str(i)} for i in range(offset, offset + limit)],
                'meta': {
                    'total_count': totalCount,
                    'limit': limit,
                    'offset': offset,
                },
            })
        queryUrl = 'http://controller/api/v1/scene/?format=json&limit={limit:d}&offset={offset:d}'.format(limit=limit, offset=totalCount)
        mock.get(queryUrl, json={
            'objects': [],
            'meta': {
                'total_count': totalCount,
                'limit': limit,
                'offset': totalCount,
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
        count = 0
        for index in range(totalCount):
            count += 1
            assert scenes[index]['id'] == str(index)
        assert count == totalCount

        # modify the data, trigger FetchAll function
        scenes = webstackclient.GetScenes()
        scenes.append(1)
        assert len(scenes) == totalCount + 1
        for index in range(totalCount):
            assert scenes[index]['id'] == str(index)
        assert scenes[-1] == 1

    # iterate through all scenes with offset and limit
    with requests_mock.Mocker() as mock:
        initialOffset = 5
        initialLimit = 500
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
        count = 0
        for index in range(initialLimit):
            count += 1
            assert scenes[index]['id'] == str(index + initialOffset)
        assert count == initialLimit

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
        if offset % limit != 0:
            return None
        if offset > totalCount:
            return None
        
        if offset < totalCount:
            environments = [{'id': str(i)} for i in range(offset, offset + limit)]
        else:
            environments = []

        response = requests.Response()
        response._content = json.dumps(
            {
                'data': {
                    'ListEnvironments': {
                        'meta': {
                            'totalCount': totalCount
                        },
                        'environments': environments,
                    }
                }
            }
        ).encode()

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
        data = webstackclient.graphApi.ListEnvironments(fields={'environments': {'id': None}})
        assert 'meta' not in data
        assert '__typename' not in data
        assert 'environments' in data
        environments = data['environments']
        count = 0
        for index in range(totalCount):
            count += 1
            assert environments[index]['id'] == str(index)
        assert count == totalCount

        # modify the data, trigger FetchAll function
        data = webstackclient.graphApi.ListEnvironments(fields={'environments': {'id': None}})
        assert 'meta' not in data
        assert '__typename' not in data
        assert 'environments' in data
        environments = data['environments']
        environments.append(1)
        assert len(environments) == totalCount + 1
        for index in range(totalCount):
            assert environments[index]['id'] == str(index)
        assert environments[-1] == 1

    initialOffset = 5
    initialLimit = 500
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
        if (offset - 5) % limit != 0:
            return None
        if offset >= initialOffset + initialLimit:
            return None
        
        environments = [{'id': str(i)} for i in range(offset, offset + limit)]
        response = requests.Response()
        response._content = json.dumps(
            {
                'data': {
                    'ListEnvironments': {
                        'meta': {
                            'totalCount': totalCount
                        },
                        'environments': environments,
                    }
                }
            }
        ).encode()

        response.status_code = 200
        return response
    adapter.add_matcher(matcher)

    # iterate through all environments with offset and limit
    with requests_mock.Mocker(adapter=adapter):
        # test iterator
        count = 0
        for index, environment in enumerate(GraphQueryIterator(webstackclient.graphApi.ListEnvironments, fields={'environments': {'id': None}}, options={'offset': initialOffset, 'first': initialLimit})):
            count += 1
            assert environment['id'] == str(index + initialOffset)
        assert count == initialLimit

        # test lazy query
        data = webstackclient.graphApi.ListEnvironments(fields={'environments': {'id': None}}, options={'offset': initialOffset, 'first': initialLimit})
        assert 'meta' not in data
        assert '__typename' not in data
        assert 'environments' in data
        environments = data['environments']
        count = 0
        for index in range(initialLimit):
            count += 1
            assert environments[index]['id'] == str(index + initialOffset)
        assert count == initialLimit

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
        if offset % limit != 0:
            return None
        if offset > totalCount:
            return None
        expectedQueries = [
            'ListEnvironments(options: $options, resolveReferences: $resolveReferences, units: $units) { __typename }',
            'ListEnvironments(options: $options, resolveReferences: $resolveReferences, units: $units) {meta {totalCount}, __typename}',
            'ListEnvironments(options: $options, resolveReferences: $resolveReferences, units: $units) {__typename, meta {totalCount}}',
        ]
        if all([expectedQuery not in query for expectedQuery in expectedQueries]):
            return None
        
        response = requests.Response()
        response._content = json.dumps(
            {
                'data': {
                    'ListEnvironments': {
                        '__typename': 'ListEnvironmentsReturnValue',
                    }
                }
            }
        ).encode()

        response.status_code = 200
        return response
    adapter.add_matcher(matcher)

    # query with no fields or query __typename
    with requests_mock.Mocker(adapter=adapter):
        data = webstackclient.graphApi.ListEnvironments()
        assert 'meta' not in data
        assert '__typename' in data
        assert 'environments' not in data
        assert data['__typename'] == 'ListEnvironmentsReturnValue'

        data = webstackclient.graphApi.ListEnvironments(fields={})
        assert 'meta' not in data
        assert '__typename' in data
        assert 'environments' not in data
        assert data['__typename'] == 'ListEnvironmentsReturnValue'

        data = webstackclient.graphApi.ListEnvironments(fields={'__typename': None})
        assert 'meta' not in data
        assert '__typename' in data
        assert 'environments' not in data
        assert data['__typename'] == 'ListEnvironmentsReturnValue'

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
        if offset % limit != 0:
            return None
        if offset > totalCount:
            return None
        if 'ListEnvironments(options: $options, resolveReferences: $resolveReferences, units: $units) {meta {totalCount}}' not in query:
            return None
        
        response = requests.Response()
        response._content = json.dumps(
            {
                'data': {
                    'ListEnvironments': {
                        'meta': {
                            'totalCount': totalCount
                        },
                    }
                }
            }
        ).encode()

        response.status_code = 200
        return response
    adapter.add_matcher(matcher)

    # query meta data
    with requests_mock.Mocker(adapter=adapter):
        data = webstackclient.graphApi.ListEnvironments(fields={'meta': {'totalCount': None}})
        assert 'meta' in data
        assert '__typename' not in data
        assert 'environments' not in data
        assert data['meta'].get('totalCount') == totalCount

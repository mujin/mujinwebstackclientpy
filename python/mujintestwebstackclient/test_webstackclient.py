# -*- coding: utf-8 -*-

import pytest
import requests_mock

from mujinwebstackclient.webstackclient import WebstackClient
import mujinwebstackclient.webstackclientutils
from mujinwebstackclient.webstackclientutils import QueryIterator

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

def test_QueryIterator():
    limit = mujinwebstackclient.webstackclientutils.MAXIMUM_QUERY_LIMIT
    totalCount = 1000
    webstackclient = WebstackClient('http://controller', 'mujin', 'mujin')

    # iterate through all scenes
    with requests_mock.Mocker() as mock:
        for offset in range(0, totalCount+limit, limit):
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

        count = 0
        for index, scene in enumerate(QueryIterator(webstackclient.GetScenes)):
            count += 1
            assert scene['id'] == str(index)
        assert count == totalCount

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

        count = 0
        for index, scene in enumerate(QueryIterator(webstackclient.GetScenes, offset=initialOffset, limit=initialLimit)):
            count += 1
            assert scene['id'] == str(index + initialOffset)
        assert count == initialLimit


def test_LazyQuery():
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

        scenes = webstackclient.GetScenes()
        count = 0
        for index in range(totalCount):
            count += 1
            assert scenes[index]['id'] == str(index)
        assert count == totalCount

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

        scenes = webstackclient.GetScenes(offset=initialOffset, limit=initialLimit)
        count = 0
        for index in range(initialLimit):
            count += 1
            assert scenes[index]['id'] == str(index + initialOffset)
        assert count == initialLimit

    # modify the data, trigger FetchAll function
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

        scenes = webstackclient.GetScenes()
        scenes.append(1)
        assert len(scenes) == totalCount + 1
        for index in range(totalCount):
            assert scenes[index]['id'] == str(index)
        assert scenes[-1] == 1

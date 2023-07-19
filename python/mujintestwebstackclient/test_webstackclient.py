# -*- coding: utf-8 -*-

import pytest
import requests_mock

from mujinwebstackclient.webstackclient import WebstackClient


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
            'objects': [],
            'meta': {
                'total_count': 101,
                'limit': 100,
                'offset': 0,
            },
        })
        scenes = WebstackClient('http://controller', 'mujin', 'mujin').GetScenes(limit=100)
        assert len(scenes) == 0
        assert scenes.offset == 0
        assert scenes.limit == 100
        assert scenes.totalCount == 101

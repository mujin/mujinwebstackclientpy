# -*- coding: utf-8 -*-

import pytest

from mujinwebstackclient import uriutils


@pytest.mark.parametrize(
    'uri, expected',
    [
        ('mujin:/test.mujin.dae', 'mujin'),
        ('file:/test.mujin.dae', 'file'),
    ],
)
def test_GetSchemeFromURI(uri, expected):
    assert uriutils.GetSchemeFromURI(uri) == expected


@pytest.mark.parametrize(
    'uri, fragmentSeparator, expected',
    [
        ('mujin:/测试_test.mujin.dae', uriutils.FRAGMENT_SEPARATOR_AT, ''),
        ('mujin:/测试_test.mujin.dae@body0_motion', uriutils.FRAGMENT_SEPARATOR_AT, 'body0_motion'),
        ('mujin:/测试_test.mujin.dae#body0_motion', uriutils.FRAGMENT_SEPARATOR_AT, ''),
    ],
)
def test_GetFragmentFromURI(uri, fragmentSeparator, expected):
    assert uriutils.GetFragmentFromURI(uri, fragmentSeparator=fragmentSeparator) == expected


@pytest.mark.parametrize(
    'uri, fragmentSeparator, expected',
    [
        ('mujin:/测试_test..mujin.dae@body0_motion', uriutils.FRAGMENT_SEPARATOR_AT, '%E6%B5%8B%E8%AF%95_test..mujin.dae@body0_motion'),
        ('mujin:/测试_test..mujin.dae@body0_motion', uriutils.FRAGMENT_SEPARATOR_SHARP, '%E6%B5%8B%E8%AF%95_test..mujin.dae%40body0_motion'),
        ('mujin:/private/s/gittest.mujin.dae', uriutils.FRAGMENT_SEPARATOR_SHARP, 'private%2Fs%2Fgittest.mujin.dae'),
    ],
)
def test_GetPrimaryKeyFromURI(uri, fragmentSeparator, expected):
    assert uriutils.GetPrimaryKeyFromURI(uri, fragmentSeparator=fragmentSeparator) == expected


@pytest.mark.parametrize(
    'filename, mujinPath, expected',
    [
        ('/data/detection/测试_test.mujin.dae', '/data/detection', '%E6%B5%8B%E8%AF%95_test.mujin.dae'),
        ('/data/u/mujin/测试_test.mujin.dae', '/data/detection', '%2Fdata%2Fu%2Fmujin%2F%E6%B5%8B%E8%AF%95_test.mujin.dae'),
        ('/abcdefg/test.mujin.dae', '/abc', '%2Fabcdefg%2Ftest.mujin.dae'),
        ('/data/media/mujin/private/s/gittest.mujin.dae', '/data/media/mujin', 'private%2Fs%2Fgittest.mujin.dae'),
    ],
)
def test_GetPrimaryKeyFromFilename(filename, mujinPath, expected):
    assert uriutils.GetPrimaryKeyFromFilename(filename, mujinPath=mujinPath) == expected


@pytest.mark.parametrize(
    'uri, fragmentSeparator, newFragmentSeparator, expected',
    [
        ('mujin:/test.mujin.dae@body0_motion', uriutils.FRAGMENT_SEPARATOR_AT, uriutils.FRAGMENT_SEPARATOR_SHARP, 'mujin:/test.mujin.dae#body0_motion'),
        ('mujin:/test.mujin.dae@body0_motion', uriutils.FRAGMENT_SEPARATOR_AT, uriutils.FRAGMENT_SEPARATOR_EMPTY, 'mujin:/test.mujin.dae'),
    ],
)
def test_GetURIFromURI(uri, fragmentSeparator, newFragmentSeparator, expected):
    assert uriutils.GetURIFromURI('mujin:/test.mujin.dae@body0_motion', fragmentSeparator=fragmentSeparator, newFragmentSeparator=newFragmentSeparator) == expected


@pytest.mark.parametrize(
    'primaryKey, primaryKeySeparator, fragmentSeparator, expected',
    [
        ('%E6%B5%8B%E8%AF%95_test..mujin.dae@body0_motion', uriutils.PRIMARY_KEY_SEPARATOR_AT, uriutils.FRAGMENT_SEPARATOR_SHARP, 'mujin:/测试_test..mujin.dae#body0_motion'),
    ],
)
def test_GetURIFromPrimaryKey(primaryKey, primaryKeySeparator, fragmentSeparator, expected):
    assert uriutils.GetURIFromPrimaryKey(primaryKey, primaryKeySeparator=primaryKeySeparator, fragmentSeparator=fragmentSeparator) == expected


@pytest.mark.parametrize(
    'filename, mujinPath, expected',
    [
        ('/data/detection/test.mujin.dae', '/data/detection', 'mujin:/test.mujin.dae'),
        ('/data/detection/test.mujin.dae', '/dat', 'mujin:/data/detection/test.mujin.dae'),
    ],
)
def test_GetURIFromFilename(filename, mujinPath, expected):
    assert uriutils.GetURIFromFilename(filename, mujinPath=mujinPath) == expected


@pytest.mark.parametrize(
    'primaryKey, primaryKeySeparator, expected',
    [
        ('%E6%B5%8B%E8%AF%95_test..mujin.dae@body0_motion', uriutils.PRIMARY_KEY_SEPARATOR_AT, '测试_test..mujin.dae'),
    ],
)
def test_GetFilenameFromPrimaryKey(primaryKey, primaryKeySeparator, expected):
    assert uriutils.GetFilenameFromPrimaryKey(primaryKey, primaryKeySeparator=primaryKeySeparator) == expected


@pytest.mark.parametrize(
    'uri, mujinPath, fragmentSeparator, expected',
    [
        ('mujin:/\u691c\u8a3c\u52d5\u4f5c1_121122.mujin.dae', '/var/www/media/u/testuser', uriutils.FRAGMENT_SEPARATOR_EMPTY, '/var/www/media/u/testuser/検証動作1_121122.mujin.dae'),
    ],
)
def test_GetFilenameFromURI(uri, mujinPath, fragmentSeparator, expected):
    assert uriutils.GetFilenameFromURI(uri, mujinPath=mujinPath, fragmentSeparator=fragmentSeparator) == expected


@pytest.mark.parametrize(
    'partType, suffix, expected',
    [
        ('测试_test', '.tar.gz', '测试_test.tar.gz'),
    ],
)
def test_GetFilenameFromPartType(partType, suffix, expected):
    assert uriutils.GetFilenameFromPartType(partType, suffix=suffix) == expected


@pytest.mark.parametrize(
    'primaryKey, expected',
    [
        ('%E6%B5%8B%E8%AF%95_test.mujin.dae', '测试_test'),
    ],
)
def test_GetPartTypeFromPrimaryKey(primaryKey, expected):
    assert uriutils.GetPartTypeFromPrimaryKey(primaryKey) == expected


@pytest.mark.parametrize(
    'partType, suffix, expected',
    [
        ('测试_test', '.mujin.dae', '%E6%B5%8B%E8%AF%95_test.mujin.dae'),
    ],
)
def test_GetPrimaryKeyFromPartType(partType, suffix, expected):
    assert uriutils.GetPrimaryKeyFromPartType(partType, suffix=suffix) == expected


@pytest.mark.parametrize(
    'partType, suffix, expected',
    [
        ('测试_test', '.mujin.dae', 'mujin:/测试_test.mujin.dae'),
    ],
)
def test_GetURIFromPartType(partType, suffix, expected):
    assert uriutils.GetURIFromPartType(partType, suffix=suffix) == expected


@pytest.mark.parametrize(
    'filename, mujinPath, suffix, expected',
    [
        ('/data/detection/测试_test.mujin.dae', '/data/detection', '.mujin.dae', '测试_test'),
        ('/data/detection/测试_test.mujin.dae', '/data/dete', '.mujin.dae', '/data/detection/测试_test'),
    ],
)
def test_GetPartTypeFromFilename(filename, mujinPath, suffix, expected):
    assert uriutils.GetPartTypeFromFilename(filename, mujinPath=mujinPath, suffix=suffix) == expected


@pytest.mark.parametrize(
    'uri, fragmentSeparator,  expected',
    [
        ('mujin:/测试_test.mujin.dae@body0_motion', uriutils.FRAGMENT_SEPARATOR_AT, '测试_test@body0_motion'),
        ('mujin:/测试_test.mujin.dae', uriutils.FRAGMENT_SEPARATOR_AT, '测试_test'),
        ('mujin:/test.mujin.dae', uriutils.FRAGMENT_SEPARATOR_AT, 'test'),
    ],
)
def test_GetPartTypeFromURI(uri, fragmentSeparator, expected):
    assert uriutils.GetPartTypeFromURI(uri, fragmentSeparator=fragmentSeparator) == expected

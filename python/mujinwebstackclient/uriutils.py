# -*- coding: utf-8 -*-
# Copyright (C) 2018 MUJIN Inc

"""
This file contains conversion functions between the following things:

- URI (mujin:/somefolder/somefile.mujin.dae) (utf8/unicode+special urlquoted) (could have fragment) (file://abc/xxx.mujin.dae#body0_motion)
- PrimaryKey (somefolder%2Fsomefile.mujin.dae) (ascii+urlquoted) (could have fragment) (mitsubishi%2Fmitsubishi-rv-7f.mujin.dae@body0_motion) (enforce return type to be str)
- Filename (somefolder/somefile.mujin.dae) (utf8/unicode) (should not have fragment)
- PartType (somefolder/somefile) (utf8/unicode) (can have fragment)
- EnvironmentID (somefolder/somefile) (utf8/unicode) (should not have fragment)
- BodyID (body0_motion) (utf8/unicode) (same as fragment)

All public functions in this file should be in the form of Get*From*, take fragementseparator as keyword argument as necessary, take allowfragment as necessary
# All other functions should be internal to this file, prefixed with _

The outside world uses this specifier to signify a FRAGMENT_SEPARATOR_SHARP specifier. This is needed because FRAGMENT_SEPARATOR_SHARP in URL parsing is a special role
"""

try:
    from urllib.parse import quote, unquote
except ImportError:
    from urllib import quote, unquote

import os
import six

from . import URIError
from . import urlparse
from . import _

import logging

log = logging.getLogger(__name__)


def _EnsureUnicode(data):
    if not isinstance(data, six.string_types):
        raise URIError(_('data %r is not a text or binary') % data)

    return six.ensure_text(data, 'utf-8')

    return data


def _EnsureUTF8(data):
    if not isinstance(data, six.string_types):
        raise URIError(_('data %r is not a text or binary') % data)

    return six.ensure_str(data, 'utf-8')

    return data


EMPTY_STRING_UNICODE = ''


EMPTY_STRING_UTF8 = ''


FRAGMENT_SEPARATOR_AT = '@'


FRAGMENT_SEPARATOR_SHARP = '#'


FRAGMENT_SEPARATOR_EMPTY = ''


PRIMARY_KEY_SEPARATOR_AT = '@'


PRIMARY_KEY_SEPARATOR_SHARP = '#'


PRIMARY_KEY_SEPARATOR_EMPTY = ''


SCHEME_MUJIN = 'mujin'


SCHEME_FILE = 'file'


def _Unquote(primaryKey):
    return _EnsureUnicode(unquote(primaryKey))


def _Quote(primaryKey):
    assert isinstance(primaryKey, six.text_type)
    return _EnsureUTF8(quote(_EnsureUTF8(primaryKey), safe=''))


def _ParseURIFast(uri, fragmentSeparator):
    """Mujin uri is unicode and special characters like  #, ? and @ will be part of the path

    input:
        uri: A unicode str
        fragmentSeparator: The separator to find the fragment
    output:
        ParseResult object which has the utf-8 decoded path part.

    uri will include 5 parts <scheme>://<netloc>/<path>?<query>#<fragment>
    mujinuri only have scheme which is mujin:/ . Other schemes will use standard python library to parse.
    mujinuri will not have  # as fragment part because we use @ as separator to separate, like: abc.mujin.dae@body0_motion

    >>> print(_ParseURI(u'mujin:/测试_test.mujin.dae', fragmentSeparator=FRAGMENT_SEPARATOR_AT).path)
    /测试_test.mujin.dae
    >>> _ParseURI(u'mujin:/测试_test.mujin.dae@body0_motion', fragmentSeparator=FRAGMENT_SEPARATOR_EMPTy).fragment
    ''
    >>> print(_ParseURI(u'mujin:/测试_test.mujin.dae@body0_motion', fragmentSeparator=FRAGMENT_SEPARATOR_SHARP).path)
    /测试_test.mujin.dae@body0_motion
    """
    uri = _EnsureUnicode(uri)
    colonindex = uri.find(':')
    if colonindex < 0:
        # no ':', so scheme is empty
        scheme = ''
        rest = uri
    else:
        scheme = uri[:colonindex]
        rest = uri[(colonindex + 1) :]
    if scheme != SCHEME_MUJIN:
        # For rfc urlparse, make sure fragment_separator is #
        # if fragmentSeparator != FRAGMENT_SEPARATOR_SHARP:
        #     raise URIError(_('fragment separator %r not supported for current scheme: %s') % (fragmentSeparator, uri))
        r = urlparse.urlparse(uri, allow_fragments=bool(fragmentSeparator))

        # If scheme is not mujin specified, use the standard uri parse
        # TODO (binbin): figure out who calls this with non-mujin scheme
        # TODO (ziyan): simon claim that there is conversion between mujin scheme and file scheme, all of them are done inside openrave, please verify, maybe remove in this case
        if r.scheme and r.scheme != SCHEME_FILE:
            raise URIError(_('scheme not supported %r: %s') % (scheme, uri))

        # Make all uri path, no matter what scheme it is, to be unicode.
        return _EnsureUnicode(r.scheme), _EnsureUnicode(r.netloc), _EnsureUnicode(r.path), _EnsureUnicode(r.params), _EnsureUnicode(r.query), _EnsureUnicode(r.fragment)

    # It's a mujinuri
    if rest.startswith('//'):
        # usually we need to split hostname from url
        # for now mujin uri doesn't have definition of hostname in uri
        raise URIError(_('mujin scheme has no hostname defined %s') % uri)

    path = rest
    fragment = EMPTY_STRING_UNICODE
    if fragmentSeparator and fragmentSeparator in rest:
        # Split by the last seen fragmentSeparator
        path, fragment = rest.rsplit(fragmentSeparator, 1)

    return scheme, EMPTY_STRING_UNICODE, path, EMPTY_STRING_UNICODE, EMPTY_STRING_UNICODE, fragment


def _ParseURI(uri, fragmentSeparator):
    scheme, netloc, path, params, query, fragment = _ParseURIFast(uri, fragmentSeparator)
    return urlparse.ParseResult(
        scheme=scheme,
        netloc=netloc,
        path=path,
        params=params,
        query=query,
        fragment=fragment,
    )


def _UnparseURI(parts, fragmentSeparator):
    """Compose a uri. This function will call urlunparse if scheme is not mujin.

    parts is a ParseResult or a tuple which has six parts (scheme, netloc, path, params, query, fragment)

    input:
        parts: A six-element tuple including scheme, netloc, url/path, params, query and fragment
    output:
        unicode
    """
    scheme = parts.scheme
    if scheme != SCHEME_MUJIN:
        # TODO(binbin): also verify who calls this with non-mujin scheme
        if scheme and scheme != SCHEME_FILE:
            raise URIError(_('scheme not supported %r: %r') % (scheme, parts))

        # For rfc urlparse, make sure fragment_separator is  #
        if fragmentSeparator != FRAGMENT_SEPARATOR_SHARP:
            raise URIError(_('fragment separator %r not supported for current scheme: %r') % (fragmentSeparator, parts))
        return urlparse.urlunparse(parts)  # urlunparse will return unicode if any of the parts is unicode

    assert len(parts.netloc) == 0
    assert len(parts.params) == 0
    assert len(parts.query) == 0
    path = parts.path
    if path and not path.startswith('/'):
        path = '/' + path
    fragment = parts.fragment
    if fragment:
        assert fragmentSeparator in (FRAGMENT_SEPARATOR_AT, FRAGMENT_SEPARATOR_SHARP)
        path = path + fragmentSeparator + fragment
    return scheme + ':' + path


def GetSchemeFromURI(uri, **kwargs):
    """Return the scheme of URI

    >>> GetSchemeFromURI('mujin:/test.mujin.dae')
    u'mujin'
    >>> GetSchemeFromURI('file:/test.mujin.dae')
    u'file'
    """
    return MujinResourceIdentifier(uri=uri, **kwargs).scheme


def GetFragmentFromURI(uri, **kwargs):
    """Return the fragment of URI
    >>> GetFragmentFromURI(u'mujin:/测试_test.mujin.dae', fragmentSeparator=FRAGMENT_SEPARATOR_AT)
    ''
    >>> GetFragmentFromURI(u'mujin:/测试_test.mujin.dae@body0_motion', fragmentSeparator=FRAGMENT_SEPARATOR_AT)
    u'body0_motion'
    >>> GetFragmentFromURI(u'mujin:/测试_test.mujin.dae#body0_motion', fragmentSeparator=FRAGMENT_SEPARATOR_AT)
    ''
    >>> GetFragmentFromURI(u'mujin:/测试_test.mujin.dae#body0_motion', fragmentSeparator=FRAGMENT_SEPARATOR_SHARP)
    u'body0_motion'
    """
    return MujinResourceIdentifier(uri=uri, **kwargs).fragment


def GetPrimaryKeyFromURI(uri, fragmentSeparator=FRAGMENT_SEPARATOR_AT, primaryKeySeparator=PRIMARY_KEY_SEPARATOR_AT, **kwargs):
    """
    input:
        uri: A mujin scheme uri which is utf-8 decoded unicode.
    output:
        primaryKey is utf-8 encoded and quoted.

    >>> GetPrimaryKeyFromURI(u'mujin:/测试_test..mujin.dae@body0_motion', fragmentSeparator=FRAGMENT_SEPARATOR_AT)
    '%E6%B5%8B%E8%AF%95_test..mujin.dae@body0_motion'
    >>> GetPrimaryKeyFromURI(u'mujin:/测试_test..mujin.dae@body0_motion', fragmentSeparator=FRAGMENT_SEPARATOR_SHARP)
    '%E6%B5%8B%E8%AF%95_test..mujin.dae%40body0_motion'
    """
    kwargs['fragmentSeparator'] = fragmentSeparator
    kwargs['primaryKeySeparator'] = primaryKeySeparator
    return MujinResourceIdentifier(uri=uri, **kwargs).primaryKey


def GetPrimaryKeyFromFilename(filename, **kwargs):
    """Extract primaryKey from filename .
    input:
        filename: a utf-8 decoded unicode without quote. need to remove mujinPath if it's given.

    >>> GetPrimaryKeyFromFilename('/data/detection/测试_test.mujin.dae', '/data/detection')
    '%E6%B5%8B%E8%AF%95_test.mujin.dae'
    >>> GetPrimaryKeyFromFilename('/data/u/mujin/测试_test.mujin.dae', '/data/detection')
    '/data/u/mujin/%E6%B5%8B%E8%AF%95_test.mujin.dae'
    >>> GetPrimaryKeyFromFilename('/abcdefg/test.mujin.dae', '/abc')
    '/abcdefg/test.mujin.dae'
    """
    return MujinResourceIdentifier(filename=filename, **kwargs).primaryKey


def GetURIFromURI(uri, newFragmentSeparator=None, **kwargs):
    """Compose a new uri from old one
    input:
        uri: A utf-8 decoded unicode uri string.
        fragmentSeparator: The separator used in old uri
        newFragmentSeparator: The new fragment separator used in new uri.
    output:
        uri: A utf-8 decoded unicode uri string.

    >>> GetURIFromURI(u'mujin:/test.mujin.dae@body0_motion', fragmentSeparator=FRAGMENT_SEPARATOR_AT, newFragmentSeparator=FRAGMENT_SEPARATOR_SHARP)
    u'mujin:/test.mujin.dae#body0_motion'
    >>> GetURIFromURI(u'mujin:/test.mujin.dae@body0_motion', fragmentSeparator=FRAGMENT_SEPARATOR_AT, newFragmentSeparator=FRAGMENT_SEPARATOR_EMPTY)
    u'mujin:/test.mujin.dae'
    """
    mri = MujinResourceIdentifier(uri=uri, **kwargs)
    if newFragmentSeparator:
        mri = mri.WithFragmentSeparator(newFragmentSeparator)
    else:
        mri = mri.WithoutFragment()
    return mri.uri


def GetEmptyURIFromWebURI(uri):
    """Compose a new uri from a Web URI without the fragment
    input:
        uri: a utf-8 decoded unicode uri string.
    output:
        uri: a utf-8 decoded unicode uri string.

    >>> GetEmptyURIFromWebURI(u'mujin:/test.mujin.dae@body0_motion')
    u'mujin:/test.mujin.dae'
    """
    mri = MujinResourceIdentifier(uri=uri, fragmentSeparator=FRAGMENT_SEPARATOR_AT)
    mri = mri.WithoutFragment()
    return mri.uri


def GetURIFromPrimaryKey(primaryKey, **kwargs):
    """Given the encoded primary key (utf-8 encoded and quoted), returns the unicode URL.
    input:

    >>> print(GetURIFromPrimaryKey('%E6%B5%8B%E8%AF%95_test..mujin.dae@body0_motion', primaryKeySeparator=PRIMARY_KEY_SEPARATOR_AT, fragmentSeparator=FRAGMENT_SEPARATOR_SHARP))
    mujin:/测试_test..mujin.dae#body0_motion
    >>> print(GetURIFromPrimaryKey('%E6%B5%8B%E8%AF%95_test..mujin.dae@body0_motion', primaryKeySeparator=PRIMARY_KEY_SEPARATOR_AT, fragmentSeparator=FRAGMENT_SEPARATOR_AT))
    mujin:/测试_test..mujin.dae@body0_motion
    """
    return MujinResourceIdentifier(primaryKey=primaryKey, **kwargs).uri


def GetURIFromFilename(filename, **kwargs):
    """Compose a mujin uri from filename.

    >>> GetURIFromFilename(u'/data/detection/test.mujin.dae', u'/data/detection')
    u'mujin:/test.mujin.dae'
    >>> GetURIFromFilename(u'/data/detection/test.mujin.dae', u'/dat')
    u'mujin:/data/detection/test.mujin.dae'
    """
    return MujinResourceIdentifier(filename=filename, **kwargs).uri


def GetFilenameFromPrimaryKey(primaryKey, **kwargs):
    """return filename from primary key
    input:
        primaryKey: utf-8 encoded str.

    output:
        filename: utf-8 decoded unicode

    >>> print(GetFilenameFromPrimaryKey('%E6%B5%8B%E8%AF%95_test..mujin.dae@body0_motion', FRAGMENT_SEPARATOR_AT))
    测试_test..mujin.dae
    """
    return MujinResourceIdentifier(primaryKey=primaryKey, **kwargs).filename


def GetFilenameFromURI(uri, **kwargs):
    """returns the filesystem path that the URI points to.

    input:
        uri: A utf-8 decoded unicode. if uri is mujin scheme, will join mujin path. otherwise it will directly use parsed path result.

    output:
        filename: A utf-8 decode unicode

    >>> print(GetFilenameFromURI(u'mujin:/\u691c\u8a3c\u52d5\u4f5c1_121122.mujin.dae',u'/var/www/media/u/testuser')[1])
    /var/www/media/u/testuser/検証動作1_121122.mujin.dae
    """
    return MujinResourceIdentifier(uri=uri, **kwargs).filename


def GetFilenameFromPartType(partType, **kwargs):
    """Unquote partType to get filename, if withsuffix is True, add the .mujin.dae suffix

    input:
        partType: A utf-8 decoded unicode
    output:
        filename: A utf-8 decoded unicode

    >>> print(GetFilenameFromPartType(u'测试_test', suffix=u'.tar.gz'))
    测试_test.tar.gz
    >>> print(GetFilenameFromPartType(u'测试_test'))
    测试_test
    """
    return MujinResourceIdentifier(partType=partType, **kwargs).filename


def GetPartTypeFromPrimaryKey(primaryKey, **kwargs):
    """Return a unicode partype
    input:
        primaryKey: A utf-8 encoded str(quoted).
    output:
        partType: A utf-8 decoded unicode

    >>> print(GetPartTypeFromPrimaryKey('%E6%B5%8B%E8%AF%95_test.mujin.dae'))
    测试_test
    """
    return MujinResourceIdentifier(primaryKey=primaryKey, **kwargs).partType


def GetPrimaryKeyFromPartType(partType, **kwargs):
    """

    input:
        partType: A utf-8 decoded unicode

    output:
        primaryKey: A utf-8 encoded str (quoted).

    >>> GetPrimaryKeyFromPartType(u'测试_test', suffix='.mujin.dae')
    '%E6%B5%8B%E8%AF%95_test.mujin.dae'
    >>> GetPrimaryKeyFromPartType(u'测试_test')
    '%E6%B5%8B%E8%AF%95_test'
    """
    return MujinResourceIdentifier(partType=partType, **kwargs).primaryKey


def GetURIFromPartType(partType, **kwargs):
    return MujinResourceIdentifier(partType=partType, **kwargs).uri


def GetPartTypeFromURI(uri, **kwargs):
    return MujinResourceIdentifier(uri=uri, **kwargs).partType


def GetPartTypeFromFilename(filename, **kwargs):
    """
    input:
        filename: A utf-8 decoded unicode
    output:
        primaryKey: A utf-8 encoded str (quoted)

    >>> print(GetPartTypeFromFilename(u'/data/detection/测试_test.mujin.dae', mujinPath=u'/data/detection', suffix=u'.mujin.dae'))
    测试_test
    >>> print(GetPartTypeFromFilename(u'/data/detection/测试_test.mujin.dae', mujinPath=u'/data/dete', suffix=u'.mujin.dae'))
    /data/detection/测试_test
    """
    return MujinResourceIdentifier(filename=filename, **kwargs).partType


class MujinResourceIdentifier(object):
    _fragmentSeparator = FRAGMENT_SEPARATOR_EMPTY
    _primaryKeySeparator = PRIMARY_KEY_SEPARATOR_EMPTY
    _suffix = EMPTY_STRING_UNICODE
    _scheme = SCHEME_MUJIN
    _mujinPath = EMPTY_STRING_UNICODE
    _primaryKey = EMPTY_STRING_UTF8
    _fragment = EMPTY_STRING_UNICODE

    def __init__(self, **kwargs):
        # scheme=SCHEME_MUJIN, fragment=EMPTY_STRING_UNICODE, uri=EMPTY_STRING_UNICODE, primaryKey=EMPTY_STRING_UTF8, partType=EMPTY_STRING_UNICODE, filename=EMPTY_STRING_UNICODE, suffix=EMPTY_STRING_UNICODE, mujinPath=EMPTY_STRING_UNICODE, fragmentSeparator=FRAGMENT_SEPARATOR_EMPTY, primaryKeySeparator=PRIMARY_KEY_SEPARATOR_EMPTY

        self.mujinPath = kwargs.pop('mujinPath', None) or EMPTY_STRING_UNICODE
        self.scheme = kwargs.pop('scheme', SCHEME_MUJIN)
        self.fragment = kwargs.pop('fragment', EMPTY_STRING_UNICODE)
        self.suffix = kwargs.pop('suffix', EMPTY_STRING_UNICODE)
        self.fragmentSeparator = kwargs.pop('fragmentSeparator', FRAGMENT_SEPARATOR_EMPTY)
        self.primaryKeySeparator = kwargs.pop('primaryKeySeparator', PRIMARY_KEY_SEPARATOR_EMPTY)

        if 'primaryKey' in kwargs:
            assert 'uri' not in kwargs
            assert 'partType' not in kwargs
            assert 'filename' not in kwargs
            self._InitFromPrimaryKey(_EnsureUTF8(kwargs.pop('primaryKey')))
        elif 'uri' in kwargs:
            assert 'partType' not in kwargs
            assert 'filename' not in kwargs
            assert 'primaryKey' not in kwargs
            self._InitFromURI(_EnsureUnicode(kwargs.pop('uri')))
        elif 'partType' in kwargs:
            assert 'uri' not in kwargs
            assert 'filename' not in kwargs
            assert 'primaryKey' not in kwargs
            self._InitFromPartType(_EnsureUnicode(kwargs.pop('partType')))
        elif 'filename' in kwargs:
            assert 'uri' not in kwargs
            assert 'partType' not in kwargs
            assert 'primaryKey' not in kwargs
            self._InitFromFilename(_EnsureUnicode(kwargs.pop('filename')))
        else:
            raise URIError(_('Lack of parameters. initialization must include one of uri, primaryKey, partType or filename'))

        # Guess suffix based on primary key. Look for last occurrence of .mujin.
        if not self._suffix:
            primaryKey = _EnsureUnicode(self._primaryKey)
            index = primaryKey.rfind('.mujin.')
            if index >= 0:
                self._suffix = primaryKey[index:]

        if kwargs:
            log.warn('left over arguments to MujinResourceIdentifier constructor are ignored: %r', kwargs)

    def _InitFromURI(self, uri):
        parts = _ParseURI(uri, fragmentSeparator=self._fragmentSeparator)

        self._scheme = parts.scheme
        self._fragment = parts.fragment

        filename = EMPTY_STRING_UNICODE
        if self._scheme == 'file':
            if os.path.commonprefix([self._mujinPath, parts.path]) != self._mujinPath:
                log.debug('scheme is file, but file absolute path is different from given mujinPath: %s', uri)
                filename = parts.path  # path might be relative
            else:
                filename = parts.path[len(self._mujinPath) :]  # is logic really necessary?
        elif self._scheme == 'mujin':
            filename = parts.path[1:]
        elif self._scheme:  # allow empty scheme
            raise URIError(_("scheme %s isn't supported from uri %r") % (parts.scheme, uri))

        self._InitFromFilename(filename)

    def _InitFromPrimaryKey(self, primaryKey):
        self._primaryKey = primaryKey
        if self._primaryKeySeparator and self._primaryKeySeparator in primaryKey:
            self._primaryKey, fragment = primaryKey.rsplit(self._primaryKeySeparator, 1)
            self._fragment = _EnsureUnicode(fragment)

    def _InitFromPartType(self, partType):
        if self._fragmentSeparator:
            partTypeSegments = partType.rsplit(self._fragmentSeparator, 1)
            basePartType = partTypeSegments[0]
            if len(partTypeSegments) > 1:
                self._fragment = _EnsureUnicode(partTypeSegments[1])
        else:
            basePartType = partType
        self._primaryKey = _Quote(basePartType + self._suffix)

    def _InitFromFilename(self, filename):
        if self._mujinPath and filename.startswith(self._mujinPath):
            filename = filename[len(self._mujinPath) :]
        self._primaryKey = _Quote(filename)

    @property
    def scheme(self):
        return self._scheme

    @scheme.setter
    def scheme(self, value):
        self._scheme = _EnsureUnicode(value)

    @property
    def fragment(self):
        return self._fragment

    @fragment.setter
    def fragment(self, value):
        self._fragment = _EnsureUnicode(value)

    @property
    def bodyId(self):
        return self._fragment

    @bodyId.setter
    def bodyId(self, value):
        self._fragment = _EnsureUnicode(value)

    @property
    def suffix(self):
        return self._suffix

    @suffix.setter
    def suffix(self, value):
        self._suffix = _EnsureUnicode(value)

    @property
    def mujinPath(self):
        return self._mujinPath

    @mujinPath.setter
    def mujinPath(self, value):
        value = _EnsureUnicode(value)
        if value and not value.endswith('/'):
            value += '/'
        self._mujinPath = value

    @property
    def primaryKeySeparator(self):
        return self._primaryKeySeparator

    @primaryKeySeparator.setter
    def primaryKeySeparator(self, value):
        self._primaryKeySeparator = _EnsureUTF8(value)

    @property
    def fragmentSeparator(self):
        return self._fragmentSeparator

    @fragmentSeparator.setter
    def fragmentSeparator(self, value):
        self._fragmentSeparator = _EnsureUnicode(value)

    @property
    def primaryKey(self):
        if self._fragment and self._primaryKeySeparator:
            return self._primaryKey + self._primaryKeySeparator + _EnsureUTF8(self._fragment)
        else:
            return self._primaryKey

    @property
    def uri(self):
        """Same as GetURIFromPrimaryKey"""
        return _UnparseURI(self.parseResult, fragmentSeparator=self._fragmentSeparator)

    @property
    def parseResult(self):
        path = _Unquote(self._primaryKey)
        if not path.startswith('/') and path:
            path = '/' + path
        return urlparse.ParseResult(
            scheme=self._scheme,
            netloc=EMPTY_STRING_UNICODE,
            path=path,
            params=EMPTY_STRING_UNICODE,
            query=EMPTY_STRING_UNICODE,
            fragment=self._fragment,
        )

    @property
    def environmentId(self):
        suffix = _EnsureUTF8(self._suffix)
        if suffix and self._primaryKey.endswith(suffix):
            return _Unquote(self._primaryKey[: -len(suffix)])
        return _Unquote(self._primaryKey)

    @environmentId.setter
    def environmentId(self, value):
        self._primaryKey = _Quote(_EnsureUnicode(value) + self._suffix)

    @property
    def filename(self):
        if not self._mujinPath:
            return self.environmentId + self._suffix
        return os.path.join(self._mujinPath, self.environmentId + self._suffix)

    @property
    def partType(self):
        if self._fragment:
            return self.environmentId + self._fragmentSeparator + self._fragment
        return self.environmentId

    @property
    def kwargs(self):
        return {
            'fragmentSeparator': self._fragmentSeparator,
            'primaryKeySeparator': self._primaryKeySeparator,
            'suffix': self._suffix,
            'scheme': self._scheme,
            'mujinPath': self._mujinPath,
            'primaryKey': self._primaryKey,
            'fragment': self._fragment,
        }

    def Clone(self, **kwargs):
        mri = MujinResourceIdentifier(**self.kwargs)
        for key, value in kwargs.items():
            setattr(mri, key, value)
        return mri

    def WithFragmentSeparator(self, fragmentSeparator):
        return self.Clone(fragmentSeparator=fragmentSeparator)

    def WithPrimaryKeySeparator(self, primaryKeySeparator):
        return self.Clone(primaryKeySeparator=primaryKeySeparator)

    def WithMujinPath(self, mujinPath):
        """
        >>> MujinResourceIdentifier(uri=u'file:/var/www/test.mujin.dae').filename
        u'/var/www/test.mujin.dae'
        >>> MujinResourceIdentifier(uri=u'file:/var/www/test.mujin.dae').filename
        u'/var/www/test.mujin.dae'
        >>> MujinResourceIdentifier(uri=u'file:/var/www/test.mujin.dae', mujinPath='/var/www').filename
        u'test.mujin.dae'
        >>> MujinResourceIdentifier(uri=u'file:/var/www/test.mujin.dae', mujinPath='/var/www').filename
        u'/var/www/test.mujin.dae'
        >>> MujinResourceIdentifier(primaryKey='test.mujin.dae').WithMujinPath(u'/data/u').filename
        u'/data/u/test.mujin.dae'
        >>> MujinResourceIdentifier(primaryKey='test.mujin.dae@body0_motion.mujin.dae').WithMujinPath(u'/data/u').filename
        u'/data/u/test.mujin.dae@body0_motion.mujin.dae'
        >>> MujinResourceIdentifier(primaryKey='test.mujin.dae@body0_motion.mujin.dae', primaryKeySeparator=PRIMARY_KEY_SEPARATOR_AT).WithMujinPath(u'/data/u').filename
        u'/data/u/test.mujin.dae'
        >>> MujinResourceIdentifier(filename='object.tar.gz', suffix=u'.tar.gz').WithMujinPath(u'/data/u').filename
        u'/data/u/object.tar.gz'
        """
        return self.Clone(mujinPath=mujinPath)

    def WithSuffix(self, suffix):
        """
        >>> MujinResourceIdentifier(uri=u'file:/var/www/test.mujin.dae').WithSuffix(u'.tar.gz').filename
        u'/var/www/test.tar.gz'
        """
        return self.Clone(suffix=suffix)

    def WithFragment(self, fragment=EMPTY_STRING_UNICODE):
        return self.Clone(fragment=fragment)

    def WithoutFragment(self):
        """
        >>> MujinResourceIdentifier(primaryKey='test.mujin.dae@body0_motion.mujin.dae', primaryKeySeparator=PRIMARY_KEY_SEPARATOR_AT).WithoutFragment().primaryKey
        'test.mujin.dae'
        >>> MujinResourceIdentifier(primaryKey='test.mujin.dae@body0_motion.mujin.dae', primaryKeySeparator=PRIMARY_KEY_SEPARATOR_AT).WithoutFragment().fragment
        ''
        >>> MujinResourceIdentifier(primaryKey='test.mujin.dae@body0_motion.mujin.dae', primaryKeySeparator=PRIMARY_KEY_SEPARATOR_AT).WithoutFragment().uri
        u'mujin:/test.mujin.dae'
        """
        return self.WithFragment()

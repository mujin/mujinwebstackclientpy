# -*- coding: utf-8 -*-
# Copyright (C) 2012-2015 MUJIN Inc
"""
Mujin webstack client
"""

# System imports
import os
import datetime
import base64
from email.utils import parsedate

import six
from typing import List, Tuple, Any, Dict # noqa: F401

# Mujin imports
from . import WebstackClientError
from . import controllerwebclientraw
from . import ugettext as _
from . import json
from . import urlparse
from . import uriutils
from . import webstackgraphclient
from .webstackclientutils import UseLazyQuery

# Logging
import logging
log = logging.getLogger(__name__)


def GetFilenameFromURI(uri, mujinpath):
    """Returns the filesystem path that the URI points to.
    :param uri: points to mujin:/ resource

    example:

      GetFilenameFromURI(u'mujin:/\u691c\u8a3c\u52d5\u4f5c1_121122.mujin.dae',u'/var/www/media/u/testuser')
      returns: (ParseResult(scheme=u'mujin', netloc='', path=u'/\u691c\u8a3c\u52d5\u4f5c1_121122.mujin.dae', params='', query='', fragment=''), u'/var/www/media/u/testuser/\u691c\u8a3c\u52d5\u4f5c1_121122.mujin.dae')
    """
    mri = uriutils.MujinResourceIdentifier(uri=uri, mujinPath=mujinpath, fragmentSeparator=uriutils.FRAGMENT_SEPARATOR_AT)
    return mri.parseResult, mri.filename


def GetURIFromPrimaryKey(pk):
    """Given the encoded primary key (has to be str object), returns the unicode URL.
    If pk is a unicode object, will use inside url as is. Otherwise it will be decoded.
    example:

      GetURIFromPrimaryKey('%E6%A4%9C%E8%A8%BC%E5%8B%95%E4%BD%9C1_121122')
      returns: u'mujin:/\u691c\u8a3c\u52d5\u4f5c1_121122.mujin.dae'
    """
    return uriutils.GetURIFromPrimaryKey(pk, primaryKeySeparator=uriutils.PRIMARY_KEY_SEPARATOR_AT, fragmentSeparator=uriutils.FRAGMENT_SEPARATOR_AT)


def GetUnicodeFromPrimaryKey(pk):
    """Given the encoded primary key (has to be str object), returns the unicode string.
    If pk is a unicode object, will return the string as is.

    example:

      GetUnicodeFromPrimaryKey('%E6%A4%9C%E8%A8%BC%E5%8B%95%E4%BD%9C1_121122')
      returns: u'\u691c\u8a3c\u52d5\u4f5c1_121122'
    """
    return uriutils.GetFilenameFromPrimaryKey(pk, primaryKeySeparator=uriutils.PRIMARY_KEY_SEPARATOR_AT)

def GetPrimaryKeyFromURI(uri):
    """
    example:

      GetPrimaryKeyFromURI(u'mujin:/\u691c\u8a3c\u52d5\u4f5c1_121122.mujin.dae')
      returns u'%E6%A4%9C%E8%A8%BC%E5%8B%95%E4%BD%9C1_121122'
    """
    return six.ensure_text(uriutils.GetPrimaryKeyFromURI(uri, uriutils.FRAGMENT_SEPARATOR_AT, uriutils.PRIMARY_KEY_SEPARATOR_AT), 'utf-8')


def _FormatHTTPDate(dt):
    """Return a string representation of a date according to RFC 1123 (HTTP/1.1).

    The supplied date must be in UTC.
    """
    weekday = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][dt.weekday()]
    month = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][dt.month - 1]
    return '%s, %02d %s %04d %02d:%02d:%02d GMT' % (weekday, dt.day, month, dt.year, dt.hour, dt.minute, dt.second)


class WebstackClient(object):
    """Client for the Mujin Controller's web stack, using API v1 (REST) or API v2 (GraphQL).
    """

    class ObjectsWrapper(list):
        """Wraps response for list of objects. Provides extra meta data.
        """
        _meta = None  # Meta dict returned from server

        def __init__(self, data):
            super(WebstackClient.ObjectsWrapper, self).__init__(data['objects'])
            self._meta = data['meta']

        @property
        def totalCount(self):
            return self._meta['total_count']

        @property
        def limit(self):
            return self._meta['limit']

        @property
        def offset(self):
            return self._meta['offset']

    _webclient = None
    _userinfo = None  # A dict storing user info, like locale

    controllerurl = ''  # URl to controller
    controllerusername = ''  # Username to login with
    controllerpassword = ''  # Password to login with

    controllerIp = ''  # Hostname of the controller web server
    controllerPort = 80  # Port of the controller web server

    def __init__(self, controllerurl='http://127.0.0.1', controllerusername='', controllerpassword='', author=None, userAgent=None, additionalHeaders=None, unixEndpoint=None):
        """Logs into the Mujin controller.

        Args:
            controllerurl (str): URL of the mujin controller, e.g. http://controller14
            controllerusername (str): Username of the mujin controller, e.g. testuser
            controllerpassword (str): Password of the mujin controller
            userAgent (str): User agent to be sent on each request
            additionalHeaders (dict): Additional HTTP headers to be included in requests
            unixEndpoint (str): Unix socket endpoint for communicating with HTTP server over unix socket
        """

        # Parse controllerurl
        scheme, netloc, path, params, query, fragment = urlparse.urlparse(controllerurl)

        # Parse any credential in the url
        if '@' in netloc:
            creds, netloc = netloc.rsplit('@', 1)
            self.controllerusername, self.controllerpassword = creds.split(':', 1)

        # Parse IP (better: hostname) and port
        self.controllerIp = netloc.split(':', 1)[0]
        self.controllerPort = 80
        if ':' in netloc:
            hostname, port = netloc.split(':')
            self.controllerIp = hostname
            self.controllerPort = int(port)

        self.controllerurl = urlparse.urlunparse((scheme, netloc, '', '', '', ''))
        self.controllerusername = controllerusername or self.controllerusername
        self.controllerpassword = controllerpassword or self.controllerpassword

        self._userinfo = {
            'username': self.controllerusername,
            'locale': os.environ.get('LANG', ''),
        }
        self._webclient = controllerwebclientraw.ControllerWebClientRaw(self.controllerurl, self.controllerusername, self.controllerpassword, author=author, userAgent=userAgent, additionalHeaders=additionalHeaders, unixEndpoint=unixEndpoint)

    def __del__(self):
        self.Destroy()

    def Destroy(self):
        self.SetDestroy()

        if self._webclient is not None:
            self._webclient.Destroy()
            self._webclient = None

    def SetDestroy(self):
        webclient = self._webclient
        if webclient is not None:
            webclient.SetDestroy()

    def SetLocale(self, locale):
        self._userinfo['locale'] = locale
        self._webclient.SetLocale(locale)

    def SetUserAgent(self, userAgent):
        """Override user agent string sent on each HTTP request
        """
        self._webclient.SetUserAgent(userAgent)

    def SetAuthor(self, author):
        """Override author header sent on each HTTP request
        """
        self._webclient.SetAuthor(author)

    @property
    def graphApi(self):
        return webstackgraphclient.GraphClient(self._webclient)

    def RestartController(self):
        """Restarts controller
        """
        self._webclient.Request('POST', '/restartserver/', timeout=1)
        # No reason to check response since it's probably an error (server is restarting after all)

    def IsLoggedIn(self):
        return True

    def Login(self, timeout=5):
        """Force webclient to login if it is not currently logged in. Useful for checking that the credential works.
        """
        self.Ping(timeout=timeout)

    def Ping(self, timeout=5):
        """Sends a dummy HEAD request to api endpoint
        """
        response = self._webclient.Request('HEAD', u'/u/%s/' % self.controllerusername, timeout=timeout)
        if response.status_code != 200:
            raise WebstackClientError(_('Failed to ping controller, status code is %d') % response.status_code, response=response)
        return response

    def GetServerVersion(self, timeout=5):
        """Pings server and gets version

        :return: server version in tuple (major, minor, patch, commit)
        """
        response = self.Ping(timeout=timeout)
        serverString = response.headers.get('Server', '')
        if not serverString.startswith('mujinwebstack/'):
            return (0, 0, 0, 'unknown')
        serverVersion = serverString[len('mujinwebstack/'):]
        serverVersionParts = serverVersion.split('+', 1)
        if len(serverVersionParts) == 1:
            # handle old format 1.2.3.commitHash
            serverVersionMajor, serverVersionMinor, serverVersionPatch, serverVersionCommit = serverVersionParts[0].split('.', 3)
        else:
            # handle new format 1.2.3+commitHash
            serverVersionMajor, serverVersionMinor, serverVersionPatch = serverVersionParts[0].split('.', 2)
            serverVersionCommit = serverVersionParts[1]
        return (int(serverVersionMajor), int(serverVersionMinor), int(serverVersionPatch), serverVersionCommit)

    def SetLogLevel(self, componentLevels, timeout=5):
        """Set webstack log level

        :param componentLevels: Mapping from component name to level name, for example {"some.specific.component": "DEBUG"}
                                If component name is empty string, it sets the root logger
                                If level name is empty string, it unsets the level previously set
        """
        response = self._webclient.Request('POST', '/loglevel/', json={'componentLevels': componentLevels}, timeout=timeout)
        if response.status_code != 200:
            raise WebstackClientError(_('failed to set webstack log level, status code is: %d') % response.status_code, response=response)

    #
    # Scene related
    #

    def UploadSceneFile(self, f, timeout=5):
        """Uploads a file managed by file handle f
        """
        return self.UploadFile(f, timeout=timeout)['filename']

    @UseLazyQuery
    def GetScenes(self, fields=None, offset=0, limit=0, timeout=5, **kwargs):
        """List all available scene on controller
        """
        params = {
            'offset': offset,
            'limit': limit,
        }
        params.update(kwargs)
        return self.ObjectsWrapper(self._webclient.APICall('GET', u'scene/', fields=fields, timeout=timeout, params=params))

    def GetScene(self, pk, fields=None, timeout=5):
        """Returns requested scene
        """
        return self._webclient.APICall('GET', u'scene/%s/' % pk, fields=fields, timeout=timeout)

    def GetObject(self, pk, fields=None, timeout=5):
        """Returns requested object
        """
        return self._webclient.APICall('GET', u'object/%s/' % pk, fields=fields, timeout=timeout)

    def SetObject(self, pk, objectdata, fields=None, timeout=5):
        """Do partial update on object resource
        """
        return self._webclient.APICall('PUT', u'object/%s/' % pk, data=objectdata, fields=fields, timeout=timeout)

    def GetRobot(self, pk, fields=None, timeout=5):
        """Returns requested robot
        """
        return self._webclient.APICall('GET', u'robot/%s/' % pk, fields=fields, timeout=timeout)

    def SetRobot(self, pk, robotdata, fields=None, timeout=5):
        """Do partial update on robot resource
        """
        return self._webclient.APICall('PUT', u'robot/%s/' % pk, data=robotdata, fields=fields, timeout=timeout)

    #
    # Scene related
    #

    def CreateScene(self, scenedata, fields=None, timeout=5):
        return self._webclient.APICall('POST', u'scene/', data=scenedata, fields=fields, timeout=timeout)

    def SetScene(self, scenepk, scenedata, fields=None, timeout=5):
        return self._webclient.APICall('PUT', u'scene/%s/' % scenepk, data=scenedata, fields=fields, timeout=timeout)

    def DeleteScene(self, scenepk, timeout=5):
        return self._webclient.APICall('DELETE', u'scene/%s/' % scenepk, timeout=timeout)

    def DeleteAllScenes(self, timeout=5):
        return self._webclient.APICall('DELETE', u'scene/', timeout=timeout)

    #
    # InstObject related
    #

    def CreateSceneInstObject(self, scenepk, instobjectdata, fields=None, timeout=5):
        return self._webclient.APICall('POST', u'scene/%s/instobject/' % scenepk, data=instobjectdata, fields=fields, timeout=timeout)

    def GetSceneInstObjects(self, scenepk, fields=None, timeout=5):
        """Returns the instance objects of the scene
        """
        return self.ObjectsWrapper(self._webclient.APICall('GET', u'scene/%s/instobject/' % scenepk, fields=fields, params={'limit': 0}, timeout=timeout))

    def GetSceneInstObject(self, scenepk, instobjectpk, fields=None, timeout=5):
        """Returns the instance objects of the scene
        """
        return self._webclient.APICall('GET', u'scene/%s/instobject/%s' % (scenepk, instobjectpk), fields=fields, timeout=timeout)

    def SetSceneInstObject(self, scenepk, instobjectpk, instobjectdata, fields=None, timeout=5):
        """Sets the instobject values via a WebAPI PUT call
        :param instobjectdata: key-value pairs of the data to modify on the instobject
        """
        return self._webclient.APICall('PUT', u'scene/%s/instobject/%s/' % (scenepk, instobjectpk), data=instobjectdata, fields=fields, timeout=timeout)

    def DeleteSceneInstObject(self, scenepk, instobjectpk, timeout=5):
        return self._webclient.APICall('DELETE', u'scene/%s/instobject/%s/' % (scenepk, instobjectpk), timeout=timeout)

    #
    # IKParam related
    #

    def CreateObjectIKParam(self, objectpk, ikparamdata, fields=None, timeout=5):
        return self._webclient.APICall('POST', u'object/%s/ikparam/' % objectpk, data=ikparamdata, fields=fields, timeout=timeout)

    def SetObjectIKParam(self, objectpk, ikparampk, ikparamdata, fields=None, timeout=5):
        """Sets the instobject values via a WebAPI PUT call
        :param instobjectdata: key-value pairs of the data to modify on the instobject
        """
        return self._webclient.APICall('PUT', u'object/%s/ikparam/%s/' % (objectpk, ikparampk), data=ikparamdata, fields=fields, timeout=timeout)

    def DeleteObjectIKParam(self, objectpk, ikparampk, timeout=5):
        return self._webclient.APICall('DELETE', u'object/%s/ikparam/%s/' % (objectpk, ikparampk), timeout=timeout)

    #
    # GraspSet related
    #

    def CreateObjectGraspSet(self, objectpk, graspsetdata, fields=None, timeout=5):
        return self._webclient.APICall('POST', u'object/%s/graspset/' % objectpk, data=graspsetdata, fields=fields, timeout=timeout)

    def SetObjectGraspSet(self, objectpk, graspsetpk, graspsetdata, fields=None, timeout=5):
        """Sets the instobject values via a WebAPI PUT call
        :param instobjectdata: key-value pairs of the data to modify on the instobject
        """
        return self._webclient.APICall('PUT', u'object/%s/graspset/%s/' % (objectpk, graspsetpk), data=graspsetdata, fields=fields, timeout=timeout)

    def DeleteObjectGraspSet(self, objectpk, graspsetpk, timeout=5):
        return self._webclient.APICall('DELETE', u'object/%s/graspset/%s/' % (objectpk, graspsetpk), timeout=timeout)

    #
    # PositionConfiguration related
    #

    def CreateObjectPositionConfiguration(self, objectpk, positionConfigurationData, fields=None, timeout=5):
        return self._webclient.APICall('POST', u'object/%s/positionConfiguration/' % objectpk, data=positionConfigurationData, fields=fields, timeout=timeout)

    def SetObjectPositionConfiguration(self, objectpk, positionConfigurationPk, positionConfigurationData, fields=None, timeout=5):
        return self._webclient.APICall('PUT', u'object/%s/positionConfiguration/%s/' % (objectpk, positionConfigurationPk), data=positionConfigurationData, fields=fields, timeout=timeout)

    def DeleteObjectPositionConfiguration(self, objectpk, positionConfigurationPk, timeout=5):
        return self._webclient.APICall('DELETE', u'object/%s/positionConfiguration/%s/' % (objectpk, positionConfigurationPk), timeout=timeout)

    #
    # Link related
    #

    def CreateObjectLink(self, objectpk, linkdata, fields=None, timeout=5):
        return self._webclient.APICall('POST', u'object/%s/link/' % objectpk, data=linkdata, fields=fields, timeout=timeout)

    def SetObjectLink(self, objectpk, linkpk, linkdata, fields=None, timeout=5):
        """Sets the instobject values via a WebAPI PUT call

        :param instobjectdata: key-value pairs of the data to modify on the instobject
        """
        return self._webclient.APICall('PUT', u'object/%s/link/%s/' % (objectpk, linkpk), data=linkdata, fields=fields, timeout=timeout)

    def GetObjectLinks(self, objectpk, fields=None, timeout=5):
        """Returns the instance objects of the scene
        """
        return self._webclient.APICall('GET', u'object/%s/link/' % (objectpk), fields=fields, timeout=timeout)

    def GetObjectLink(self, objectpk, linkpk, fields=None, timeout=5):
        """Returns the instance objects of the scene
        """
        return self._webclient.APICall('GET', u'object/%s/link/%s/' % (objectpk, linkpk), fields=fields, timeout=timeout)

    def DeleteObjectLink(self, objectpk, linkpk, timeout=5):
        return self._webclient.APICall('DELETE', u'object/%s/link/%s/' % (objectpk, linkpk), timeout=timeout)

    #
    # Attachment related
    #

    def CreateObjectAttachment(self, objectpk, attachmentdata, fields=None, timeout=5):
        return self._webclient.APICall('POST', u'object/%s/attachment/' % objectpk, data=attachmentdata, fields=fields, timeout=timeout)

    def SetObjectAttachment(self, objectpk, attachmentpk, attachmentdata, fields=None, timeout=5):
        return self._webclient.APICall('PUT', u'object/%s/attachment/%s/' % (objectpk, attachmentpk), data=attachmentdata, fields=fields, timeout=timeout)

    def DeleteObjectAttachment(self, objectpk, attachmentpk, timeout=5):
        return self._webclient.APICall('DELETE', u'object/%s/attachment/%s/' % (objectpk, attachmentpk), timeout=timeout)

    #
    # Geometry related
    #

    def CreateObjectGeometry(self, objectpk, geometrydata, fields=None, timeout=5):
        return self._webclient.APICall('POST', u'object/%s/geometry/' % objectpk, data=geometrydata, fields=fields, timeout=timeout)

    def SetObjectGeometry(self, objectpk, geometrypk, geometrydata, fields=None, timeout=5):
        """Sets the instobject values via a WebAPI PUT call

        :param instobjectdata: key-value pairs of the data to modify on the instobject
        """
        return self._webclient.APICall('PUT', u'object/%s/geometry/%s/' % (objectpk, geometrypk), data=geometrydata, fields=fields, timeout=timeout)

    def GetObjectGeometryData(self, objectpk, geometrypk, mesh=False, fields=None, timeout=5):
        """Returns the instance objects of the scene
        """
        params = {}
        if mesh:
            params['mesh'] = '1'
        return self._webclient.APICall('GET', u'object/%s/geometry/%s/' % (objectpk, geometrypk), params=params, fields=fields, timeout=timeout)

    def SetObjectGeometryMesh(self, objectpk, geometrypk, data, formathint='stl', unit='mm', timeout=5):
        """Upload binary file content of a cad file to be set as the mesh for the geometry
        """
        assert (formathint == 'stl')  # for now, only support stl

        headers = {
            'Content-Type': 'application/sla',
        }
        params = {'unit': unit}
        return self._webclient.APICall('PUT', u'object/%s/geometry/%s/' % (objectpk, geometrypk), params=params, data=data, headers=headers, timeout=timeout)

    def DeleteObjectGeometry(self, objectpk, geometrypk, timeout=5):
        return self._webclient.APICall('DELETE', u'object/%s/geometry/%s/' % (objectpk, geometrypk), timeout=timeout)

    def GetObjectGeometries(self, objectpk, mesh=False, fields=None, timeout=5):
        params = {}
        if mesh:
            params['mesh'] = '1'
        return self._webclient.APICall('GET', u'object/%s/geometry/' % objectpk, params=params, fields=fields, timeout=timeout)['geometries']

    #
    # Object Tools related
    #

    def GetRobotTools(self, robotpk, fields=None, timeout=5):
        return self._webclient.APICall('GET', u'robot/%s/tool/' % robotpk, fields=fields, timeout=timeout)['tools']

    def GetRobotTool(self, robotpk, toolpk, fields=None, timeout=5):
        return self._webclient.APICall('GET', u'robot/%s/tool/%s/' % (robotpk, toolpk), fields=fields, timeout=timeout)

    def CreateRobotTool(self, robotpk, tooldata, fields=None, timeout=5):
        return self._webclient.APICall('POST', u'robot/%s/tool/' % robotpk, data=tooldata, fields=fields, timeout=timeout)

    def SetRobotTool(self, robotpk, toolpk, tooldata, fields=None, timeout=5):
        """Sets the tool values via a WebAPI PUT call
        :param tooldata: key-value pairs of the data to modify on the tool
        """
        return self._webclient.APICall('PUT', u'robot/%s/tool/%s/' % (robotpk, toolpk), data=tooldata, fields=fields, timeout=timeout)

    def DeleteRobotTool(self, robotpk, toolpk, timeout=5):
        return self._webclient.APICall('DELETE', u'robot/%s/tool/%s/' % (robotpk, toolpk), timeout=timeout)

    #
    # InstObject Tools related
    #

    def GetInstRobotTools(self, scenepk, instobjectpk, fields=None, timeout=5):
        return self._webclient.APICall('GET', u'scene/%s/instobject/%s/tool/' % (scenepk, instobjectpk), fields=fields, timeout=timeout)['tools']

    def GetInstRobotTool(self, scenepk, instobjectpk, toolpk, fields=None, timeout=5):
        return self._webclient.APICall('GET', u'scene/%s/instobject/%s/tool/%s' % (scenepk, instobjectpk, toolpk), fields=fields, timeout=timeout)

    def CreateInstRobotTool(self, scenepk, instobjectpk, tooldata, fields=None, timeout=5):
        return self._webclient.APICall('POST', u'scene/%s/instobject/%s/tool/' % (scenepk, instobjectpk), data=tooldata, fields=fields, timeout=timeout)

    def SetInstRobotTool(self, scenepk, instobjectpk, toolpk, tooldata, fields=None, timeout=5):
        """Sets the tool values via a WebAPI PUT call
        :param tooldata: key-value pairs of the data to modify on the tool
        """
        return self._webclient.APICall('PUT', u'scene/%s/instobject/%s/tool/%s/' % (scenepk, instobjectpk, toolpk), data=tooldata, fields=fields, timeout=timeout)

    def DeleteInstRobotTool(self, scenepk, instobjectpk, toolpk, timeout=5):
        return self._webclient.APICall('DELETE', u'scene/%s/instobject/%s/tool/%s/' % (scenepk, instobjectpk, toolpk), timeout=timeout)

    #
    # Attached sensors related
    #

    def CreateRobotAttachedSensor(self, robotpk, attachedsensordata, fields=None, timeout=5):
        return self._webclient.APICall('POST', u'robot/%s/attachedsensor/' % robotpk, data=attachedsensordata, fields=fields, timeout=timeout)

    def GetRobotAttachedSensors(self, robotpk, timeout=5):
        return self._webclient.APICall('GET', u'robot/%s/attachedsensor/' % robotpk, timeout=timeout)['attachedsensors']

    def SetRobotAttachedSensor(self, robotpk, attachedsensorpk, attachedsensordata, fields=None, timeout=5):
        """Sets the attachedsensor values via a WebAPI PUT call

        :param attachedsensordata: key-value pairs of the data to modify on the attachedsensor
        """
        return self._webclient.APICall('PUT', u'robot/%s/attachedsensor/%s/' % (robotpk, attachedsensorpk), data=attachedsensordata, fields=fields, timeout=timeout)

    def SetRobotAttachedActuator(self, robotpk, attachedactuatorpk, attachedacturtordata, fields=None, timeout=5):
        """Sets the attachedactuatorpk values via a WebAPI PUT call

        :param attachedacturtordata: key-value pairs of the data to modify on the attachedactuator
        """
        return self._webclient.APICall('PUT', u'robot/%s/attachedactuator/%s/' % (robotpk, attachedactuatorpk), data=attachedacturtordata, fields=fields, timeout=timeout)

    def DeleteRobotAttachedSensor(self, robotpk, attachedsensorpk, timeout=5):
        return self._webclient.APICall('DELETE', u'robot/%s/attachedsensor/%s/' % (robotpk, attachedsensorpk), timeout=timeout)

    #
    # Gripper info related
    #

    def CreateRobotGripperInfo(self, robotpk, gripperInfoData, fields=None, timeout=5):
        return self._webclient.APICall('POST', u'robot/%s/gripperInfo/' % robotpk, data=gripperInfoData, fields=fields, timeout=timeout)

    def GetRobotGripperInfos(self, robotpk, timeout=5):
        return self._webclient.APICall('GET', u'robot/%s/gripperInfo/' % robotpk, timeout=timeout)['gripperInfos']

    def GetRobotGripperInfo(self, robotpk, gripperinfopk, timeout=5):
        return self._webclient.APICall('GET', u'robot/%s/gripperInfo/%s/' % (robotpk, gripperinfopk), timeout=timeout)

    def SetRobotGripperInfo(self, robotpk, gripperinfopk, gripperInfoData, fields=None, timeout=5):
        """Sets the gripper values via a WebAPI PUT call

        :param gripperInfoData: key-value pairs of the data to modify on the gripper
        """
        return self._webclient.APICall('PUT', u'robot/%s/gripperInfo/%s/' % (robotpk, gripperinfopk), data=gripperInfoData, fields=fields, timeout=timeout)

    def DeleteRobotGripperInfo(self, robotpk, gripperinfopk, timeout=5):
        return self._webclient.APICall('DELETE', u'robot/%s/gripperInfo/%s/' % (robotpk, gripperinfopk), timeout=timeout)

    #
    # Connected body related
    #

    def CreateRobotConnectedBody(self, robotpk, connectedBodyData, fields=None, timeout=5):
        return self._webclient.APICall('POST', u'robot/%s/connectedBody/' % robotpk, data=connectedBodyData, fields=fields, timeout=timeout)

    def GetRobotConnectedBodies(self, robotpk, timeout=5):
        return self._webclient.APICall('GET', u'robot/%s/connectedBody/' % robotpk, timeout=timeout)['connectedBodies']

    def GetRobotConnectedBody(self, robotpk, connectedBodyPk, timeout=5):
        return self._webclient.APICall('GET', u'robot/%s/connectedBody/%s/' % (robotpk, connectedBodyPk), timeout=timeout)

    def SetRobotConnectedBody(self, robotpk, connectedBodyPk, connectedBodyData, fields=None, timeout=5):
        """Sets the connected body values via a WebAPI PUT call

        :param connectedBodyData: key-value pairs of the data to modify on the connected body
        """
        return self._webclient.APICall('PUT', u'robot/%s/connectedBody/%s/' % (robotpk, connectedBodyPk), data=connectedBodyData, fields=fields, timeout=timeout)

    def DeleteRobotConnectedBody(self, robotpk, connectedBodyPk, timeout=5):
        return self._webclient.APICall('DELETE', u'robot/%s/connectedBody/%s/' % (robotpk, connectedBodyPk), timeout=timeout)

    #
    # Task related
    #

    @UseLazyQuery
    def GetSceneTasks(self, scenepk, fields=None, offset=0, limit=0, tasktype=None, timeout=5):
        params = {
            'offset': offset,
            'limit': limit,
        }
        if tasktype:
            params['tasktype'] = tasktype
        return self.ObjectsWrapper(self._webclient.APICall('GET', u'scene/%s/task/' % scenepk, fields=fields, timeout=timeout, params=params))

    def GetSceneTask(self, scenepk, taskpk, fields=None, timeout=5):
        return self._webclient.APICall('GET', u'scene/%s/task/%s/' % (scenepk, taskpk), fields=fields, timeout=timeout)

    def CreateSceneTask(self, scenepk, taskdata, fields=None, timeout=5):
        return self._webclient.APICall('POST', u'scene/%s/task/' % scenepk, data=taskdata, fields=fields, timeout=timeout)

    def SetSceneTask(self, scenepk, taskpk, taskdata, fields=None, timeout=5):
        self._webclient.APICall('PUT', u'scene/%s/task/%s/' % (scenepk, taskpk), data=taskdata, fields=fields, timeout=timeout)

    def DeleteSceneTask(self, scenepk, taskpk, timeout=5):
        self._webclient.APICall('DELETE', u'scene/%s/task/%s/' % (scenepk, taskpk), timeout=timeout)

    def RunSceneTaskAsync(self, scenepk, taskpk, fields=None, timeout=5):
        """
        :return: {'jobpk': 'xxx', 'msg': 'xxx'}
        """
        data = {
            'scenepk': scenepk,
            'target_pk': taskpk,
            'resource_type': 'task',
        }
        return self._webclient.APICall('POST', u'job/', data=data, expectedStatusCode=200, timeout=timeout)

    #
    # Result related
    #

    def GetResult(self, resultpk, fields=None, timeout=5):
        return self._webclient.APICall('GET', u'planningresult/%s/' % resultpk, fields=fields, timeout=timeout)

    def GetBinpickingResult(self, resultpk, fields=None, timeout=5):
        assert (UserWarning)
        return self._webclient.APICall('GET', u'binpickingresult/%s' % resultpk, fields=fields, timeout=timeout)

    def GetResultProgram(self, resultpk, programtype=None, format='dat', timeout=5):
        params = {'format': format}
        if programtype is not None and len(programtype) > 0:
            params['type'] = programtype
        # Custom http call because APICall currently only supports json
        response = self._webclient.Request('GET', u'/api/v1/planningresult/%s/program/' % resultpk, params=params, timeout=timeout)
        assert (response.status_code == 200)
        return response.content

    def SetResult(self, resultpk, resultdata, fields=None, timeout=5):
        self._webclient.APICall('PUT', u'planningresult/%s/' % resultpk, data=resultdata, fields=fields, timeout=timeout)

    def DeleteResult(self, resultpk, timeout=5):
        self._webclient.APICall('DELETE', u'planningresult/%s/' % resultpk, timeout=timeout)

    #
    # Job related
    #

    @UseLazyQuery
    def GetJobs(self, fields=None, offset=0, limit=0, timeout=5):
        return self.ObjectsWrapper(self._webclient.APICall('GET', u'job/', fields=fields, timeout=timeout, params={
            'offset': offset,
            'limit': limit,
        }))

    def DeleteJob(self, jobpk, timeout=5):
        """Cancels the job with the corresponding jobpk
        """
        self._webclient.APICall('DELETE', u'job/%s/' % jobpk, timeout=timeout)

    def DeleteJobs(self, timeout=5):
        """Cancels all jobs
        """
        # Cancel on the zmq configure socket first
        self._webclient.APICall('DELETE', u'job/', timeout=timeout)

    #
    # Cycle Log
    #

    def CreateLogEntries(self, logEntries, timeout=5):
        # type: (List[Tuple[str, Any, Dict[str, bytes]]], int) -> Any
        files = []
        for logType, logEntry, attachments in logEntries:
            files.append((u'logEntry/%s' % logType, ('', json.dumps(logEntry), 'application/json')))
            if attachments is not None:
                for attachmentName, attachmentData in six.iteritems(attachments):
                    files.append((u'attachment', (attachmentName, attachmentData)))
        return self._webclient.APICall('POST', u'logEntry', files=files, timeout=timeout, apiVersion='v2')

    #
    # Controller State
    #

    def GetControllerState(self, controllerId, fields=None, timeout=3):
        return self._webclient.APICall('GET', u'controllerState/%s/' % controllerId, fields=fields, timeout=timeout)

    #
    # Geometry related
    #

    def GetObjectGeometry(self, objectpk, timeout=5):
        """Return list of geometries (a dictionary with keys: positions, indices) of the given object
        """
        import numpy
        response = self._webclient.APICall('GET', u'object/%s/scenejs/' % objectpk, timeout=timeout)
        geometries = []
        for encodedGeometry in response['geometries']:
            geometry = {}
            positions = numpy.fromstring(base64.b64decode(encodedGeometry['positions_base64']), dtype=float)
            positions = positions.reshape(len(positions) // 3, 3)
            geometry['positions'] = positions
            indices = numpy.fromstring(base64.b64decode(encodedGeometry['indices_base64']), dtype=numpy.uint32)
            indices = indices.reshape(len(indices) // 3, 3)
            geometry['indices'] = indices
            geometries.append(geometry)
        return geometries

    #
    # File related
    #

    def UploadFile(self, f, filename=None, timeout=10):
        """Uploads a file managed by file handle f
        Returns:
            (dict) json response
        """
        data = {}
        if filename:
            data['filename'] = filename
        response = self._webclient.Request('POST', '/fileupload', files={'file': f}, data=data, timeout=timeout)
        if response.status_code in (200,):
            try:
                return response.json()
            except Exception as e:
                log.exception('failed to upload file: %s', e)
        raise WebstackClientError(response.content.decode('utf-8'), response=response)

    def UploadFiles(self, files, timeout=60):
        """Uploads a list of files

        Args:
            files (list): list of files in the form of [
                    ('myObject.mujin.msgpack', fileLikeObj),
                    ('files/myObject/subfolder/test.jpg', fileLikeObj),
                    ('files/myObject/subfolder/test2.jpg', fileLikeObj),
                ]
        Returns:
            (dict) json response
        """
        response = self._webclient.Request('POST', '/fileupload', files=[
            ('files', (filename, f))
            for filename, f in files
        ], timeout=timeout)
        if response.status_code in (200,):
            try:
                return response.json()
            except Exception as e:
                log.exception('failed to upload files: %s', e)
        raise WebstackClientError(response.content.decode('utf-8'))

    def DeleteFile(self, filename, timeout=10):
        response = self._webclient.Request('POST', '/file/delete/', data={'filename': filename}, timeout=timeout)
        if response.status_code in (200,):
            try:
                return response.json()['filename']
            except Exception as e:
                log.exception('failed to delete file: %s', e)
        raise WebstackClientError(response.content.decode('utf-8'), response=response)

    def DeleteFiles(self, filenames, timeout=10):
        response = self._webclient.Request('POST', '/file/delete/', data={'filenames': filenames}, timeout=timeout)
        if response.status_code in (200,):
            try:
                return response.json()['filenames']
            except Exception as e:
                log.exception('failed to delete file: %s', e)
        raise WebstackClientError(response.content.decode('utf-8'), response=response)

    def ListFiles(self, dirname='', timeout=2):
        response = self._webclient.Request('GET', '/file/list/', params={'dirname': dirname}, timeout=timeout)
        if response.status_code in (200, 404):
            try:
                return response.json()
            except Exception as e:
                log.exception('failed to delete file: %s', e)
        raise WebstackClientError(response.content.decode('utf-8'), response=response)

    def FileExists(self, path, timeout=5):
        """Check if a file exists on server
        """
        response = self._webclient.Request('HEAD', u'/u/%s/%s' % (self.controllerusername, path.rstrip('/')), timeout=timeout)
        if response.status_code not in [200, 301, 404]:
            raise WebstackClientError(_('Failed to check file existence, status code is %d') % response.status_code, response=response)
        return response.status_code != 404

    def DownloadFile(self, filename, ifmodifiedsince=None, timeout=5):
        """Downloads a file given filename

        :return: A streaming response
        """
        headers = {}
        if ifmodifiedsince:
            headers['If-Modified-Since'] = _FormatHTTPDate(ifmodifiedsince)
        response = self._webclient.Request('GET', u'/u/%s/%s' % (self.controllerusername, filename), headers=headers, stream=True, timeout=timeout)
        if ifmodifiedsince and response.status_code == 304:
            return response
        if response.status_code != 200:
            raise WebstackClientError(response.content.decode('utf-8'), response=response)
        return response

    def FlushAndDownloadFile(self, filename, timeout=5):
        """Flush and perform a HEAD operation on the given filename to retrieve metadata.

        :return: A streaming response
        """
        response = self._webclient.Request('GET', '/file/download/', params={'filename': filename}, stream=True, timeout=timeout)
        if response.status_code != 200:
            raise WebstackClientError(response.content.decode('utf-8'), response=response)
        return response

    def FlushAndHeadFile(self, filename, timeout=5):
        """Flush and perform a HEAD operation on the given filename to retrieve metadata.

        :return: A dict containing "modified (datetime.datetime)" and "size (int)"
        """
        response = self._webclient.Request('HEAD', '/file/download/', params={'filename': filename}, timeout=timeout)
        if response.status_code != 200:
            raise WebstackClientError(_('Failed to check file existence, status code is %d') % response.status_code, response=response)
        return {
            'modified': datetime.datetime(*parsedate(response.headers['Last-Modified'])[:6]),
            'size': int(response.headers['Content-Length']),
        }

    def HeadFile(self, filename, timeout=5):
        """Perform a HEAD operation on the given filename to retrieve metadata.

        :return: A dict containing "modified (datetime.datetime)" and "size (int)"
        """
        path = u'/u/%s/%s' % (self.controllerusername, filename.rstrip('/'))
        response = self._webclient.Request('HEAD', path, timeout=timeout)
        if response.status_code not in [200]:
            raise WebstackClientError(_('Failed to check file existence, status code is %d') % response.status_code, response=response)
        return {
            'modified': datetime.datetime(*parsedate(response.headers['Last-Modified'])[:6]),
            'size': int(response.headers['Content-Length']),
            'hash': response.headers.get('X-Content-SHA1'),
        }

    def FlushCache(self, timeout=5):
        """Flush pending changes in cache to disk
        """
        response = self._webclient.Request('POST', '/flushcache/', timeout=timeout)
        if response.status_code != 200:
            raise WebstackClientError(response.content.decode('utf-8'), response=response)

    # 
    # Blob related
    # 

    def DownloadBlob(self, blobId, timeout=5):
        """Downloads a blob with given id

        :return: A streaming response
        """
        response = self._webclient.Request('GET', u'/api/v2/blob/%s' % blobId, stream=True, timeout=timeout)
        if response.status_code == 404:
            raise WebstackClientError(_('Blob "%s" does not exist, status code is %d') % (blobId, response.status_code), response=response)
        if response.status_code == 204:
            raise WebstackClientError(_('Blob "%s" has no content, status code is %d') % (blobId, response.status_code), response=response)
        if response.status_code != 200:
            raise WebstackClientError(response.content.decode('utf-8'), response=response)
        return response

    #
    # Log related
    #

    def GetUserLog(self, category, level='DEBUG', keyword=None, limit=None, cursor=None, includecursor=False, forward=False, timeout=2):
        """Get the user log from the controller.
        """
        params = {
            'keyword': (keyword or '').strip(),
            'cursor': (cursor or '').strip(),
            'includecursor': 'true' if includecursor else 'false',
            'forward': 'true' if forward else 'false',
            'limit': str(limit or 0),
            'level': level,
        }

        response = self._webclient.Request('GET', '/log/user/%s/' % category, params=params, timeout=timeout)
        if response.status_code != 200:
            raise WebstackClientError(_('Failed to retrieve user log, status code is %d') % response.status_code, response=response)
        return response.json()
    
    def DownloadSignalLog(self, limit=None, cursor=None, includecursor=False, forward=False, timeout=2):
        """Get the signal log from the controller.

        Returns a stream response, so have to use 
        
        for chunk in GetSignalLog().iter_content(chunk_size=10000):
            if chunk:
                f.write(chunk)
        
        """
        params = {
            'cursor': (cursor or '').strip(),
            'includecursor': 'true' if includecursor else 'false',
            'forward': 'true' if forward else 'false',
            'limit': str(limit or 0),
        }
        
        response = self._webclient.Request('GET', '/log/plcsignal/', params=params, timeout=timeout, stream=True)
        if response.status_code != 200:
            raise WebstackClientError(_('Failed to retrieve user log, status code is %d') % response.status_code, response=response)
        return response
    
    #
    # Query list of scenepks based on barcdoe field
    #

    def QueryScenePKsByBarcodes(self, barcodes, timeout=2):
        response = self._webclient.Request('GET', '/query/barcodes/', params={'barcodes': ','.join(barcodes)})
        if response.status_code != 200:
            raise WebstackClientError(_('Failed to query scenes based on barcode, status code is %d') % response.status_code, response=response)
        return response.json()

    #
    # Report stats to registration controller
    #

    def ReportStats(self, data, timeout=5):
        response = self._webclient.Request('POST', '/stats/', data=json.dumps(data), headers={'Content-Type': 'application/json'}, timeout=timeout)
        if response.status_code != 200:
            raise WebstackClientError(_('Failed to upload stats, status code is %d') % response.status_code, response=response)

    #
    # Config.
    #

    def GetConfig(self, filename=None, timeout=5):
        """Retrieve configuration file content from controller.

        :param filename: optional, can be one of controllersystem.conf, binpickingsystem.conf, teachworkersystem.conf, robotbridges.conf.json
        :return: configuration file content dictionary 
        """
        path = '/config/'
        if filename:
            path = '/config/%s/' % filename
        response = self._webclient.Request('GET', path, timeout=timeout)
        if response.status_code != 200:
            raise WebstackClientError(_('Failed to retrieve configuration from controller, status code is %d') % response.status_code, response=response)
        return response.json()

    def HeadConfig(self, filename, timeout=5):
        """Perform a HEAD operation on the given configuration filename to retrieve metadata.

        :return: A dict containing "modified (datetime.datetime)" and "size (int)"
        """
        path = '/config/'
        if filename:
            path = '/config/%s/' % filename
        response = self._webclient.Request('HEAD', path, timeout=timeout)
        if response.status_code != 200:
            raise WebstackClientError(_('Failed to check configuration existence, status code is %d') % response.status_code, response=response)
        return {
            'modified': datetime.datetime(*parsedate(response.headers['Last-Modified'])[:6]),
        }

    def SetConfig(self, data, filename=None, timeout=5):
        """Set configuration file content to controller.

        :param data: content dictionary in its entirety
        :param filename: optional, can be one of controllersystem.conf, binpickingsystem.conf, teachworkersystem.conf, robotbridges.conf.json
        """
        path = '/config/'
        if filename:
            path = '/config/%s/' % filename
        response = self._webclient.Request('PUT', path, data=json.dumps(data), headers={'Content-Type': 'application/json'}, timeout=timeout)
        if response.status_code not in (200, 202):
            raise WebstackClientError(_('Failed to set configuration to controller, status code is %d') % response.status_code, response=response)

    def DeleteConfig(self, filename, timeout=5):
        """Delete configuration file on controller.
        :param filename: filename of the configuration file to delete
        """
        path = '/config/%s/' % filename
        response = self._webclient.Request('DELETE', path, timeout=timeout)
        if response.status_code not in (200, 204):
            raise WebstackClientError(_('Failed to delete configuration on controller, status code is %d') % response.status_code, response=response)

    def GetSystemInfo(self, timeout=3):
        response = self._webclient.Request('GET', '/systeminfo/')
        if response.status_code != 200:
            raise WebstackClientError(_('Failed to retrieve system info from controller, status code is %d') % response.status_code, response=response)
        return response.json()

    #
    # Reference Object PKs.
    #
    def ModifySceneAddReferenceObjectPK(self, scenepk, referenceobjectpk, timeout=5):
        return self.ModifySceneAddReferenceObjectPKs(scenepk, [referenceobjectpk], timeout=timeout)

    def ModifySceneAddReferenceObjectPKs(self, scenepk, referenceobjectpks, timeout=5):
        """
        Add multiple referenceobjectpks to the scene.
        """
        response = self._webclient.Request('POST', '/referenceobjectpks/add/', data=json.dumps({
            'scenepk': scenepk,
            'referenceobjectpks': referenceobjectpks,
        }), headers={'Content-Type': 'application/json'}, timeout=timeout)
        if response.status_code != 200:
            raise WebstackClientError(_('Failed to add referenceobjectpks %r to scene %r, status code is %d') % (referenceobjectpks, scenepk, response.status_code), response=response)

    def ModifySceneRemoveReferenceObjectPK(self, scenepk, referenceobjectpk, timeout=5):
        return self.ModifySceneRemoveReferenceObjectPKs(scenepk, [referenceobjectpk], timeout=timeout)

    def ModifySceneRemoveReferenceObjectPKs(self, scenepk, referenceobjectpks, timeout=5):
        """
        Remove multiple referenceobjectpks from the scene.
        """
        response = self._webclient.Request('POST', '/referenceobjectpks/remove/', data=json.dumps({
            'scenepk': scenepk,
            'referenceobjectpks': referenceobjectpks,
        }), headers={'Content-Type': 'application/json'}, timeout=timeout)
        if response.status_code != 200:
            raise WebstackClientError(_('Failed to remove referenceobjectpks %r from scene %r, status code is %d') % (referenceobjectpks, scenepk, response.status_code), response=response)

    #
    # ITL program related
    #

    @UseLazyQuery
    def GetITLPrograms(self, fields=None, offset=0, limit=0, timeout=5, **kwargs):
        params = {
            'offset': offset,
            'limit': limit,
        }
        params.update(kwargs)
        return self.ObjectsWrapper(self._webclient.APICall('GET', u'itl/', fields=fields, timeout=timeout, params=params))

    def GetITLProgram(self, programName, fields=None, timeout=5):
        """Throws exception if program does not exist."""
        return self._webclient.APICall('GET', u'itl/%s/' % programName, fields=fields, timeout=timeout)

    def CreateITLProgram(self, data, fields=None, timeout=5):
        return self._webclient.APICall('POST', u'itl/', data=data, fields=fields, timeout=timeout)

    def SetITLProgram(self, programName, data, fields=None, timeout=5):
        self._webclient.APICall('PUT', u'itl/%s/' % programName, data=data, fields=fields, timeout=timeout)

    def DeleteITLProgram(self, programName, timeout=5):
        self._webclient.APICall('DELETE', u'itl/%s/' % programName, timeout=timeout)

    def DeleteAllITLPrograms(self, timeout=5):
        return self._webclient.APICall('DELETE', u'itl/', timeout=timeout)

    #
    # Backup restore
    #

    def Backup(self, saveconfig=True, savemedia=True, backupscenepks=None, saveapps=True, saveitl=True, savedetection=False, savecalibration=False, savedebug=False, timeout=600):
        """Downloads a backup file

        :param saveconfig: Whether we want to include configs in the backup, defaults to True
        :param savemedia: Whether we want to include media files in the backup, defaults to True
        :param saveapps: Whether we want to include web apps in the backup, defaults to True
        :param saveitl: Whether we want to include itl programs in the backup, defaults to True
        :param savedetection: Whether we want to include detection files in the backup, defaults to False
        :param savecalibration: Whether we want to include calibration files in the backup, defaults to False
        :param savedebug: Whether we want to include debug files in the backup, defaults to False
        :param backupscenepks: List of scenes to backup, defaults to None
        :param timeout: Amount of time in seconds to wait before failing, defaults to 600
        :raises WebstackClientError: If request wasn't successful
        :return: A streaming response to the backup file
        """
        response = self._webclient.Request('GET', '/backup/', stream=True, params={
            'media': 'true' if savemedia else 'false',
            'config': 'true' if saveconfig else 'false',
            'apps': 'true' if saveapps else 'false',
            'itl': 'true' if saveitl else 'false',
            'detection': 'true' if savedetection else 'false',
            'calibration': 'true' if savecalibration else 'false',
            'debug': 'true' if savedebug else 'false',
            'backupScenePks': ','.join(backupscenepks) if backupscenepks else None,
        }, timeout=timeout)
        if response.status_code != 200:
            raise WebstackClientError(response.content.decode('utf-8'), response=response)
        return response

    def Restore(self, file, restoreconfig=True, restoremedia=True, restoreapps=True, restoreitl=True, timeout=600):
        """Uploads a previously downloaded backup file to restore

        :param file: Backup filer in tarball format
        :param restoreconfig: Whether we want to restore the configs, defaults to True
        :param restoremedia: Whether we want to restore the media data, defaults to True
        :param restoreapps: Whether we want to restore the web apps, defaults to True
        :param restoreitl: Whether we want to restore the itl programs, defaults to True
        :param timeout: Amount of time in seconds to wait before failing, defaults to 600
        :raises WebstackClientError: If request wasn't successful
        :return: JSON response
        """
        response = self._webclient.Request('POST', '/backup/', files={'file': file}, params={
            'media': 'true' if restoremedia else 'false',
            'config': 'true' if restoreconfig else 'false',
            'apps': 'true' if restoreapps else 'false',
            'itl': 'true' if restoreitl else 'false',
        }, timeout=timeout)
        if response.status_code in (200,):
            try:
                return response.json()
            except Exception as e:
                log.exception('failed to restore: %s', e)
        raise WebstackClientError(response.content.decode('utf-8'), response=response)

    #
    # Debugging related
    #

    def GetDebugResources(self, timeout=5):
        """returns available debug resources from controller

        :param timeout: Amount of time in seconds to wait before failing, defaults to 5
        :return: Available debug resources
        """
        return self.ObjectsWrapper(self._webclient.APICall('GET', u'debug/', timeout=timeout))

    def DownloadDebugResource(self, debugresourcepk, downloadSizeLimit=100*1024*1024, timeout=10):
        """downloads contents of the given debug resource

        :param debugresourcepk: Exact name of the debug resource to download
        :param downloadSizeLimit: Limit of the size of the debug resource to download, defaults to 100*1024*1024 bytes
        :param timeout: Amount of time in seconds to wait before failing, defaults to 10
        :raises WebstackClientError: If request wasn't successful
        :return: Contents of the requested resource
        """
        # custom http call because APICall currently only supports json
        # params is used to store query parameters and passed to the request
        params = {
            'sizeLimit' : downloadSizeLimit
        }
        response = self._webclient.Request('GET', '/api/v1/debug/%s/download/' % debugresourcepk, stream=True, timeout=timeout, params=params)
        if response.status_code != 200:
            raise WebstackClientError(response.content.decode('utf-8'), response=response)
        return response

    def GetSchema(self, schemaId, timeout=10):
        """Look up json schema by schemaId
        """
        response = self._webclient.Request('GET', '/schema/%s/%s.json' % (self._userinfo['locale'], schemaId))
        if response.status_code != 200:
            raise WebstackClientError(response.content.decode('utf-8'), response=response)
        return response.json()

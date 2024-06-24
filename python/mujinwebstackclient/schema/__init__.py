# -*- coding: utf-8 -*-

from .. import _

filterSchema = {
    'type': 'object',
    'properties': {
        'operation': {
            'type': 'string',
            'enum': ['constant', 'pointer', 'not', 'isNull', 'notNull', 'and', 'or', 'equal', 'notEqual', 'less', 'lessEqual', 'greater', 'greaterEqual', 'in', 'notIn', 'like', 'insensitiveLike', 'regexMatch', 'startsWith', 'insensitiveStartsWith', 'endsWith', 'insensitiveEndsWith', 'contains', 'insensitiveContains', 'plus', 'minus', 'multiply', 'divide', 'mod', 'concatenate'],
            'description': _('Operation of the filter.')
        },
        'operands': {
            'type': 'array',
            'items': {'$refs': '#'},
            'description': _('Operands of the operation.')
        },
        'field': {
            'type': 'array',
            'items': {
                'type': ['string', 'integer'],
                'default': '',
            },
            'description': _('A path of either string or int to a (nested) field.')
        },
        'value': {
        }
    },
    'required': ['operation']
}
filterSchema['properties']['operands']['items'] = filterSchema

webStackConfigurationSchema = {
    'type': 'object',
    'typeName': 'WebStackConfiguration',
    'description': _('WebStack specific configuration.'),
    'properties': {
        'sync': {
            'type': 'object',
            'typeName': 'SyncWebStackConfiguration',
            'description': _('The configuration for syncing resources with other controllers.'),
            'properties': {
                'remotes': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'typeName': 'RemoteWebStack',
                        'description': _('Remote WebStack configuration.'),
                        'properties': {
                            'url': {
                                'type': 'string',
                                'description': _('URL of the remote WebStack.'),
                            },
                            'username': {
                                'type': 'string',
                                'description': _('Username of the remote WebStack.'),
                            },
                            'password': {
                                'type': 'string',
                                'description': _('Password of the remote WebStack.'),
                            },
                            'pullInterval': {
                                'type': 'string',
                                'description': _('Pulling interval for this remote, overwrites global default if set.\nValid time units are "ns", "us" (or "µs"), "ms", "s", "m", "h", "d", "w", "y".'),
                            },
                            'configurationFilter': dict(
                                filterSchema,
                                description=_('Configuration syncing filter for this remote, overwrites global default if set.')
                            ),
                            'environmentFilter': dict(
                                filterSchema,
                                description=_('Environment syncing filter for this remote, overwrites global default if set.')
                            ),
                        }
                    },
                    'description': _('List of remote WebStacks to sync with.')
                },
                'pullInterval': {
                    'type': 'string',
                    'description': _('Pulling interval. Pulling is disabled if this field is not set.\nValid time units are "ns", "us" (or "µs"), "ms", "s", "m", "h", "d", "w", "y".'),
                },
                'configurationFilter': dict(
                    filterSchema,
                    description=_('Configuration syncing filter, configurations are not synced if this filter is not set.')
                ),
                'environmentFilter': dict(
                    filterSchema,
                    description=_('Environment syncing filter, environments are not synced if this filter is not set.')
                ),
            }
        }
    }
}

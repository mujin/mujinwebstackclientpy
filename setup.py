# -*- coding: utf-8 -*-
# Copyright (C) 2012-2014 MUJIN Inc
from distutils.core import setup
try:
    from mujinbuildcommon.distributions import Distribution
except (ImportError, SyntaxError):
    from distutils.dist import Distribution

version = {}
exec(open('python/mujinwebstackclient/version.py').read(), version)

setup(
    distclass=Distribution,
    name='mujinwebstackclient',
    version=version['__version__'],
    packages=['mujinwebstackclient', 'mujinwebstackclient.schema'],
    package_dir={'mujinwebstackclient': 'python/mujinwebstackclient'},
    data_files=[
        # using scripts= will cause the first line of the script being modified for python2 or python3
        # put the scripts in data_files will copy them as-is
        ('bin', [
            'bin/mujin_webstackclientpy_applyconfig.py',
            'bin/mujin_webstackclientpy_runshell.py',
            'bin/mujin_webstackclientpy_downloaddata.py',
        ]),
    ],
    schema=[
        # 'mujinwebstackclient.schema.webstackConfigSchema',  # NOTE: we don't support $refs and recursive python object
    ],
    locale_dir='locale',
    license='Apache License, Version 2.0',
    long_description=open('README.md').read(),
    # flake8 compliance configuration
    enable_flake8=True,  # Enable checks
    fail_on_flake=True,  # Fail builds when checks fail
    install_requires=[],
)

# -*- coding: utf-8 -*-
# Copyright (C) 2012-2023 Mujin Inc.
import os
import subprocess
from distutils.core import setup
from setuptools.command.build_py import build_py
try:
    from mujincommon.setuptools import Distribution
except (ImportError, SyntaxError):
    from distutils.dist import Distribution

version = {}
exec(open('python/mujinwebstackclient/version.py').read(), version)


def generate():
    introspect_binary = os.path.join(os.environ.get(
        'JHBUILD_PREFIXES', '/opt'), 'bin', 'mujin_webstack_introspect')
    if not os.path.exists(introspect_binary):
        print('Cannot find webstack introspect binary, skip generation')
        return

    version_text = subprocess.check_output([introspect_binary, '-v'])
    if not version_text.startswith(b'mujin_webstack_introspect version '):
        print('Unexpected webstack version text, abort')
        return

    version_text = version_text[len(b'mujin_webstack_introspect version '):]

    with open('python/mujinwebstackclient/controllergraphclient.py', 'rb') as file:
        for line in file:
            if line.startswith(b'# GENERATED AGAINST: mujinwebstack/'):
                if line[len(b'# GENERATED AGAINST: mujinwebstack/'):] == version_text:
                    print('Newest graph client version, skip generation')
                    return
                else:
                    break

    process = subprocess.Popen(introspect_binary, stderr=subprocess.PIPE)
    try:
        while True:
            line = process.stderr.readline()
            if not line:
                print('Introspect process EOF unexpectedly')
                return
            if b'running and serving endpoint' in line:
                break
        generated = subprocess.check_output(
            ['python3', 'devbin/mujin_webstackclientpy_generategraphclient.py', '--url', 'http://127.0.0.1:8000'])
    finally:
        process.kill()
        process.wait()

    with open('python/mujinwebstackclient/controllergraphclient.py', 'wb') as file:
        file.write(generated)


class build_with_gen(build_py):
    def run(self):
        generate()
        build_py.run(self)


setup(
    distclass=Distribution,
    name='mujinwebstackclient',
    version=version['__version__'],
    cmdclass={'build_py': build_with_gen},
    packages=['mujinwebstackclient'],
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
    locale_dir='locale',
    license='Apache License, Version 2.0',
    long_description=open('README.md').read(),
    # flake8 compliance configuration
    enable_flake8=True,  # Enable checks
    fail_on_flake=True,  # Fail builds when checks fail
    install_requires=[],
)
